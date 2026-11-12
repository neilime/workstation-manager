"""Verify private disk storage, command lifecycle, and real tmpfiles lock handling."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
from ansible_test_helpers import (
    SETUP_ROLES,
    ansible_environment,
    desktop_variables,
    run_playbook,
    write_local_playbook,
)

ROLE = SETUP_ROLES / "temporary_storage"
COMMAND = ROLE / "files/scratch.py"
RULE = ROLE / "files/workstation-manager-scratch.conf"


@pytest.fixture(name="scratch")
def scratch_fixture(tmp_path):
    """Keep commands, cleanup, and persistent data inside an isolated home."""
    home = tmp_path / 'home with spaces and "100%"'
    home.mkdir()
    environment = {**os.environ, "HOME": str(home), "TMPDIR": "/tmp"}
    root = home / ".cache/workstation-manager/scratch"
    return home, root, environment


def clean(root, environment):
    """Run the installed rule with zero age so tests need no wall-clock ageing."""
    rule = root.parent / "fixture.conf"
    rule.write_text(RULE.read_text().replace("1d", "0"))
    return subprocess.run(
        ["systemd-tmpfiles", "--user", "--clean", str(rule)],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )


def wait_for(path):
    """Bound synchronization with test-owned subprocesses."""
    deadline = time.monotonic() + 10
    while not path.exists():
        if time.monotonic() > deadline:
            pytest.fail(f"Timed out waiting for {path}")
        time.sleep(0.05)


@pytest.mark.parametrize("status", [0, 7])
def test_command_preserves_context_and_cleans_its_disposable_files(scratch, status):
    """Success and failure preserve streams, cwd, status, and unrelated source files."""
    home, root, environment = scratch
    source = home / "unpublished.txt"
    source.write_text("keep")
    script = (
        "import os,pathlib,sys;"
        "p=pathlib.Path(os.environ['TMPDIR']);"
        "assert p.stat().st_mode & 0o777 == 0o700;"
        "assert pathlib.Path.cwd() == pathlib.Path.home();"
        "(p/'scratch').write_text('discard');"
        "print(p);print('diagnostic',file=sys.stderr);"
        f"sys.exit({status})"
    )
    result = subprocess.run(
        [sys.executable, str(COMMAND), "--", sys.executable, "-c", script],
        cwd=home,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == status, result.stderr
    assert Path(result.stdout.strip()).parent == root
    assert result.stderr == "diagnostic\n"
    assert not list(root.iterdir())
    assert source.read_text() == "keep"
    assert environment["TMPDIR"] == "/tmp"


def test_daily_cleanup_preserves_locked_commands_and_unmanaged_data(scratch):
    """The actual tmpfiles cleaner skips active tasks and never follows scratch links."""
    home, root, environment = scratch
    ready, release = home / "ready", home / "release"
    script = """
import os, pathlib, time
home = pathlib.Path.home()
scratch = pathlib.Path(os.environ["TMPDIR"])
(scratch / "active").write_text("keep while active")
(home / "ready").write_text(str(scratch))
while not (home / "release").exists():
    time.sleep(0.05)
"""
    worker = subprocess.Popen([sys.executable, str(COMMAND), sys.executable, "-c", script], env=environment)
    try:
        wait_for(ready)
        active = Path(ready.read_text())
        abandoned = root / "task-abandoned"
        abandoned.mkdir()
        (abandoned / "discard").write_text("discard")
        checkout = home / "project"
        checkout.mkdir()
        (checkout / ".git").mkdir()
        (checkout / "unpublished").write_text("keep")
        (abandoned / "checkout-link").symlink_to(checkout, target_is_directory=True)

        clean(root, environment)

        assert (active / "active").read_text() == "keep while active"
        assert not abandoned.exists()
        assert (checkout / "unpublished").read_text() == "keep"
        release.touch()
        assert worker.wait(timeout=10) == 0
        assert not active.exists()
    finally:
        release.touch()
        if worker.poll() is None:
            worker.terminate()
        worker.wait(timeout=10)


def test_surviving_child_keeps_its_inherited_cleanup_lease(scratch):
    """A child retaining the directory lock prevents deletion after its parent exits."""
    home, root, environment = scratch
    release = home / "release"
    child_script = """
import pathlib, time
home = pathlib.Path.home()
(home / "child-ready").touch()
while not (home / "release").exists():
    time.sleep(0.05)
"""
    script = (
        "import os,pathlib,subprocess,sys;"
        "(pathlib.Path.home()/'scratch-path').write_text(os.environ['TMPDIR']);"
        f"subprocess.Popen([sys.executable,'-c',{child_script!r}],close_fds=False)"
    )
    try:
        result = subprocess.run(
            [sys.executable, str(COMMAND), sys.executable, "-c", script],
            env=environment,
            check=False,
            timeout=10,
        )
        assert result.returncode == 0
        wait_for(home / "child-ready")
        directory = Path((home / "scratch-path").read_text())
        assert directory.exists()
        clean(root, environment)
        assert directory.exists()
    finally:
        release.touch()
    deadline = time.monotonic() + 10
    while directory.exists() and time.monotonic() < deadline:
        clean(root, environment)
        time.sleep(0.05)
    assert not directory.exists()


def test_scratch_rejects_ram_backed_storage():
    """A HOME on tmpfs cannot silently turn disposable writes back into RAM use."""
    with tempfile.TemporaryDirectory(dir="/dev/shm") as home:
        result = subprocess.run(
            [sys.executable, str(COMMAND), sys.executable, "-c", "raise AssertionError('must not run')"],
            env={**os.environ, "HOME": home},
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        assert result.returncode != 0
        assert "must be on disk" in result.stderr


def test_scratch_rejects_redirected_storage(scratch):
    """A symlink cannot redirect the managed scratch root into unrelated user data."""
    home, root, environment = scratch
    root.parent.mkdir(parents=True)
    root.symlink_to(home, target_is_directory=True)
    result = subprocess.run(
        [sys.executable, str(COMMAND), "true"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode != 0
    assert "private directory" in result.stderr
    assert home.exists()


def test_role_installs_previews_and_converges_without_a_user_bus(tmp_path):
    """Setup installs private storage and persistent timer enablement without a desktop."""
    home = tmp_path / "managed home"
    playbook = write_local_playbook(
        tmp_path / "playbook.json",
        [{"ansible.builtin.import_role": {"name": "neilime.workstation_setup.temporary_storage"}}],
        desktop_variables(home),
    )
    command = ["ansible-playbook", "-i", "localhost,", str(playbook)]
    environment = ansible_environment(tmp_path)
    preview = run_playbook([*command, "--check"], environment)
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert not home.exists()

    result = run_playbook(command, environment)
    assert result.returncode == 0, result.stdout + result.stderr
    root = home / ".cache/workstation-manager/scratch"
    assert root.stat().st_mode & 0o777 == 0o700
    executable = home / ".local/bin/workstation-manager-scratch"
    assert executable.stat().st_mode & 0o777 == 0o755
    assert executable.stat().st_uid == os.getuid()
    installed = subprocess.run(
        [str(executable), sys.executable, "-c", "import os; print(os.environ['TMPDIR'])"],
        env={**environment, "HOME": str(home)},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert installed.returncode == 0, installed.stderr
    assert Path(installed.stdout.strip()).parent == root
    assert not Path(installed.stdout.strip()).exists()
    assert (home / ".config/user-tmpfiles.d/workstation-manager-scratch.conf").read_text() == RULE.read_text()
    timer = home / ".config/systemd/user/timers.target.wants/workstation-manager-scratch-clean.timer"
    assert timer.resolve().is_file()
    repeated = run_playbook(command, environment)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout

    unrelated = home / "unmanaged-cache"
    unrelated.mkdir()
    sentinel = unrelated / "keep"
    sentinel.write_text("keep")
    (home / ".config/user-tmpfiles.d/unrelated.conf").write_text('e "%h/unmanaged-cache" - - - 0\n')
    service = home / ".config/systemd/user/workstation-manager-scratch-clean.service"
    invocation = next(
        line.removeprefix("ExecStart=") for line in service.read_text().splitlines() if line.startswith("ExecStart=")
    )
    subprocess.run(
        [argument.replace("%h", str(home)) for argument in shlex.split(invocation)],
        env={**environment, "HOME": str(home)},
        check=True,
        timeout=10,
    )
    assert sentinel.read_text() == "keep"
