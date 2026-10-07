"""Verify archive progress streams through Ansible before the task completes."""

from __future__ import annotations

import json
import os
import pathlib
import selectors
import subprocess
import tarfile
from time import monotonic

import pytest
from ansible_test_helpers import ansible_environment, run_playbook, write_local_playbook

pytestmark = pytest.mark.integration


@pytest.fixture(name="archive_fixture")
def archive_fixture_builder(tmp_path):
    """Build a disposable real archive task without workstation state or credentials."""

    source = tmp_path / "source with spaces"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True, capture_output=True)
    (source / ".gitignore").write_text("ignored-dependencies/\n*.private\n")
    ignored = source / "ignored-dependencies"
    ignored.mkdir()
    (ignored / "excluded.txt").write_text("synthetic-excluded-marker\n")
    (source / "ignored.private").write_text("synthetic-excluded-marker\n")
    (source / "payload.bin").write_bytes(os.urandom(8 * 1024 * 1024))
    (source / "linked-payload").symlink_to("payload.bin")
    for directory in (".git", "node_modules"):
        (source / directory).mkdir(exist_ok=True)
        (source / directory / "excluded.txt").write_text("synthetic-excluded-marker\n")
    destination = tmp_path / "backup.tar.gz"
    playbook = tmp_path / "playbook.json"
    write_local_playbook(
        playbook,
        [
            {
                "name": "Create backup archive",
                "neilime.workstation_backup.archive_with_progress": {
                    "path": [str(source)],
                    "dest": str(destination),
                    "exclusion_patterns": ["*/.git/*", "*/node_modules/*"],
                },
            }
        ],
        {},
    )
    environment = ansible_environment(
        tmp_path, PYTHONUNBUFFERED="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1"
    )
    return playbook, destination, environment


@pytest.mark.parametrize("relative", [False, True])
def test_progress_streams_before_archive_creation_finishes(archive_fixture, relative):
    """Users must see progress while the real archive module is still running."""

    playbook, destination, environment = archive_fixture
    if relative:
        content = json.loads(playbook.read_text())
        content[0]["tasks"][0]["neilime.workstation_backup.archive_with_progress"]["dest"] = destination.name
        playbook.write_text(json.dumps(content))
    output = b""
    with subprocess.Popen(
        ["ansible-playbook", "-i", "localhost,", "-c", "local", str(playbook)],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    ) as process:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                deadline = monotonic() + 60
                while monotonic() < deadline:
                    if not selector.select(timeout=1):
                        continue
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        break
                    output += chunk
                    if b"Creating backup archive: preparing files" in output:
                        assert process.poll() is None, output.decode()
                        break
                assert b"Creating backup archive: preparing files" in output, output.decode()
            remainder, _stderr = process.communicate(timeout=60)
            output += remainder
            assert process.returncode == 0, output.decode()
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
    assert b"MiB written, elapsed" in output
    assert b"synthetic-excluded-marker" not in output
    assert destination.stat().st_mode & 0o777 == 0o600
    with tarfile.open(destination, "r:gz") as archive:
        assert any(name.endswith("/payload.bin") for name in archive.getnames())
        assert not any(name.endswith("/excluded.txt") for name in archive.getnames())
        assert any(member.issym() and member.linkname == "payload.bin" for member in archive.getmembers())


@pytest.mark.parametrize("check,no_log", [(True, False), (False, True)])
def test_preview_and_sensitive_tasks_do_not_display_progress(archive_fixture, check, no_log):
    """Check mode must avoid writes, and no_log must suppress the action's output."""

    playbook, destination, environment = archive_fixture
    content = json.loads(playbook.read_text())
    content[0]["tasks"][0]["no_log"] = no_log
    playbook.write_text(json.dumps(content))
    command = ["ansible-playbook", "-i", "localhost,", "-c", "local", str(playbook)]
    if check:
        command.append("--check")
    result = run_playbook(command, environment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Creating backup archive:" not in result.stdout
    assert destination.exists() is not check


def test_archive_failure_remains_fatal(archive_fixture):
    """Progress must stop and propagate the writer's failure."""

    playbook, destination, environment = archive_fixture
    content = json.loads(playbook.read_text())
    content[0]["tasks"][0]["neilime.workstation_backup.archive_with_progress"]["dest"] = str(
        destination.parent / "missing/backup.tar.gz"
    )
    playbook.write_text(json.dumps(content))
    result = run_playbook(["ansible-playbook", "-i", "localhost,", "-c", "local", str(playbook)], environment)
    assert result.returncode != 0
    assert "Creating backup archive: preparing files" in result.stdout
    assert "FAILED!" in result.stdout
    assert not destination.exists()


def test_repeat_backup_reports_no_change_and_keeps_a_valid_archive(archive_fixture):
    """The real action/module boundary must preserve idempotence and repeat progress."""

    playbook, destination, environment = archive_fixture
    command = ["ansible-playbook", "-i", "localhost,", "-c", "local", str(playbook)]
    for expected_changes in (1, 0):
        result = run_playbook(command, environment)
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"changed={expected_changes}" in result.stdout
        assert "MiB written, elapsed" in result.stdout
        assert not pathlib.Path(str(destination) + ".partial").exists()
        with tarfile.open(destination, "r:gz") as archive:
            assert any(name.endswith("/payload.bin") for name in archive.getnames())
