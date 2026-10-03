"""Exercise backup and restore paths with isolated homes and real Ansible roles."""

from __future__ import annotations

import json
import os
import pathlib
import pwd
import subprocess
import sys
import tarfile

import pytest

WORKSPACE = pathlib.Path(__file__).parents[2]


def run_role(root: pathlib.Path, role: str, variables: dict, *, check: bool = False) -> subprocess.CompletedProcess:
    """Run only filesystem recovery against disposable fixtures, without workstation setup."""

    # Isolated role fixtures repeat Ansible play and environment declarations.
    # pylint: disable=duplicate-code
    configuration = root / "ansible.cfg"
    configuration.write_text("[defaults]\n")
    playbook = root / "playbook.json"
    playbook.write_text(
        json.dumps(
            [
                {
                    "hosts": "localhost",
                    "gather_facts": False,
                    "vars": {
                        "ansible_python_interpreter": sys.executable,
                        "workstation_restore_target_user_name": pwd.getpwuid(os.getuid()).pw_name,
                        **variables,
                    },
                    "roles": [role],
                }
            ]
        )
    )
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": str(root),
        "ANSIBLE_HOME": str(root / ".ansible"),
        "ANSIBLE_CONFIG": str(configuration),
        "ANSIBLE_COLLECTIONS_PATH": str(WORKSPACE / "ansible/collections"),
        "WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR": str(root / "backup"),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    arguments = ["ansible-playbook", "-i", "localhost,", "-c", "local", str(playbook)]
    if check:
        arguments.append("--check")
    return subprocess.run(arguments, env=environment, cwd=root, capture_output=True, text=True, timeout=60, check=False)
    # pylint: enable=duplicate-code


@pytest.mark.parametrize("config_present", [False, True])
def test_backup_restores_projects_to_documents_with_or_without_user_config(tmp_path, config_present):
    """A missing optional config source must not change where project files are recovered."""

    source_home = tmp_path / "source-home"
    project = source_home / "Documents/dev-projects/client"
    project.mkdir(parents=True)
    (project / "local-note.txt").write_text("archived local work\n")
    if config_present:
        configuration = source_home / ".config/workstation-manager/settings.json"
        configuration.parent.mkdir(parents=True)
        configuration.write_text('{"fixture": true}\n')
    result = run_role(
        tmp_path,
        "neilime.workstation_backup.state",
        {
            "workstation_backup_timestamp": "fixture",
            "workstation_manager_resolved": {"user": {"home": str(source_home)}},
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    archive_path = tmp_path / "backup/workstation-manager-backup-fixture.tar.gz"
    with tarfile.open(archive_path) as archive:
        assert "Documents/dev-projects/client/local-note.txt" in archive.getnames()
    target_home = tmp_path / "target-home"
    target_home.mkdir()
    result = run_role(
        tmp_path,
        "neilime.workstation_restore.state",
        {"workstation_restore_archive": str(archive_path), "workstation_restore_target_user_home": str(target_home)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (target_home / "Documents/dev-projects/client/local-note.txt").read_text() == "archived local work\n"
    assert not (target_home / "dev-projects").exists()
    if config_present:
        assert (target_home / ".config/workstation-manager/settings.json").read_text() == '{"fixture": true}\n'


@pytest.mark.parametrize("source_relative", ["Documents/dev-projects", ".config/workstation-manager"])
@pytest.mark.parametrize("check", [False, True])
@pytest.mark.parametrize("manifest_present", [False, True])
def test_restore_recovers_single_source_archives_in_the_original_home_subdirectory(
    tmp_path, source_relative, check, manifest_present
):
    """Existing archives relative to Documents or .config must retain their intended destination."""

    source = tmp_path / "source-home" / source_relative
    source.mkdir(parents=True)
    (source / "recovery.txt").write_text("archived file\n")
    archive_path = tmp_path / "recovery.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(source, arcname=source.name)
    if manifest_present:
        label = "dev-projects" if source.name == "dev-projects" else "workstation-manager-user-config"
        (tmp_path / "recovery.manifest.txt").write_text(f"include\t{label}\t{source}\n")
    target_home = tmp_path / "target-home"
    target_home.mkdir()
    result = run_role(
        tmp_path,
        "neilime.workstation_restore.state",
        {"workstation_restore_archive": str(archive_path), "workstation_restore_target_user_home": str(target_home)},
        check=check,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    if check:
        assert not list(target_home.iterdir())
    else:
        assert (target_home / source_relative / "recovery.txt").read_text() == "archived file\n"
        assert not (target_home / source.name).exists()


def test_shortened_project_archive_rejects_redirected_documents_before_extraction(tmp_path):
    """Planning a corrected destination must still protect the managed home boundary."""

    source = tmp_path / "source-home/Documents/dev-projects"
    source.mkdir(parents=True)
    (source / "recovery.txt").write_text("archived file\n")
    archive_path = tmp_path / "recovery.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(source, arcname="dev-projects")
    target_home = tmp_path / "target-home"
    target_home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (target_home / "Documents").symlink_to(outside, target_is_directory=True)
    result = run_role(
        tmp_path,
        "neilime.workstation_restore.state",
        {"workstation_restore_archive": str(archive_path), "workstation_restore_target_user_home": str(target_home)},
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "escapes the target home" in result.stdout
    assert not list(outside.iterdir())
    assert not (target_home / "dev-projects").exists()


@pytest.fixture(name="git_archive")
def fixture_git_archive(tmp_path, monkeypatch) -> dict:
    """Archive local changes and serve a real Git origin through an isolated SSH stub."""
    # Fixture Git identity and environment repeat across isolated repository tests.
    # pylint: disable=duplicate-code
    origin = tmp_path / "origin"
    origin.mkdir()
    environment = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    }

    def git(*arguments: str) -> str:
        return subprocess.check_output(["git", *arguments], cwd=origin, env=environment, text=True).strip()

    git("init", "--quiet", "--initial-branch=main")
    (origin / "tracked.txt").write_text("remote-base\n")
    git("add", ".")
    git("commit", "--quiet", "-m", "Initial revision")
    initial_commit = git("rev-parse", "HEAD")
    git("checkout", "--quiet", "-b", "topic")
    (origin / "topic.txt").write_text("topic-branch\n")
    git("add", ".")
    git("commit", "--quiet", "-m", "Topic revision")
    git("checkout", "--quiet", "main")

    source = tmp_path / "source-home/Documents/dev-projects/client"
    source.mkdir(parents=True)
    (source / "tracked.txt").write_text("remote-base\nlocal-change\n")
    (source / "local-note.txt").write_text("local-untracked\n")
    with tarfile.open(tmp_path / "recovery.tar.gz", "w:gz") as archive:
        archive.add(source, arcname="Documents/dev-projects/client")
    (tmp_path / "target-home").mkdir()

    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    ssh = binary_directory / "ssh"
    ssh.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, shlex, sys\n"
        "root = pathlib.Path(__file__).resolve().parent.parent\n"
        "args = sys.argv[1:]\n"
        "if '-V' in args or '-G' in args:\n"
        "    sys.exit(0)\n"
        "with (root / 'ssh-calls.jsonl').open('a') as calls:\n"
        "    calls.write(json.dumps({'args': args, 'home': os.environ['HOME'],\n"
        "                            'prompt': os.environ.get('GIT_TERMINAL_PROMPT')}) + '\\n')\n"
        "if (root / 'reject-ssh').exists():\n"
        "    print('Host key verification failed.', file=sys.stderr)\n"
        "    sys.exit(255)\n"
        "command = shlex.split(args[-1])\n"
        "if command[0] != 'git-upload-pack':\n"
        "    sys.exit(2)\n"
        "os.execvp(command[0], command)\n"
    )
    ssh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{binary_directory}:{os.environ['PATH']}")
    remote_url = f"fixture@git.example.invalid:{origin}"
    return {
        "relative_path": "client",
        "branch": "topic",
        "head_commit": initial_commit,
        "primary_remote_name": "upstream",
        "primary_remote_url": remote_url,
        "remotes": [{"name": "upstream", "url": remote_url}, {"name": "secondary", "url": str(origin)}],
    }
    # pylint: enable=duplicate-code


def restore_git_archive(root: pathlib.Path, repository: dict, *, check: bool = False) -> subprocess.CompletedProcess:
    """Restore the fixture archive and recorded Git metadata using the production role."""
    (root / "recovery.git-repositories.json").write_text(json.dumps([repository]))
    return run_role(
        root,
        "neilime.workstation_restore.state",
        {
            "workstation_restore_archive": str(root / "recovery.tar.gz"),
            "workstation_restore_target_user_home": str(root / "target-home"),
        },
        check=check,
    )


@pytest.mark.parametrize("branch", ["topic", ""])
def test_git_reattachment_configures_noninteractive_ssh_and_preserves_worktree(tmp_path, git_archive, branch):
    """SSH clones must accept new hosts, honor Git metadata, and overlay archived changes."""
    git_archive["branch"] = branch
    result = restore_git_archive(tmp_path, git_archive)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"status": "reattached"' in result.stdout
    project = tmp_path / "target-home/Documents/dev-projects/client"
    assert (project / "tracked.txt").read_text() == "remote-base\nlocal-change\n"
    assert (project / "local-note.txt").read_text() == "local-untracked\n"
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

    def git(*arguments: str) -> str:
        return subprocess.check_output(["git", "-C", str(project), *arguments], env=environment, text=True).strip()

    assert git("branch", "--show-current") == branch
    assert git("remote", "get-url", "upstream") == git_archive["primary_remote_url"]
    assert git("remote", "get-url", "secondary") == git_archive["remotes"][1]["url"]
    if branch:
        assert (project / "topic.txt").read_text() == "topic-branch\n"
    else:
        assert git("rev-parse", "HEAD") == git_archive["head_commit"]
    calls = [json.loads(line) for line in (tmp_path / "ssh-calls.jsonl").read_text().splitlines()]
    assert calls
    for call in calls:
        assert "StrictHostKeyChecking=accept-new" in call["args"]
        assert "BatchMode=yes" in call["args"]
        assert call["home"] == str(tmp_path / "target-home")
        assert call["prompt"] == "0"
    assert not project.with_name("client.workstation-manager-restore-overlay").exists()
    git("switch", "main")
    assert git("branch", "--show-current") == "main"
    assert git("config", "--get", "branch.main.remote") == "upstream"
    assert git("config", "--get", "branch.main.merge") == "refs/heads/main"
    assert (project / "tracked.txt").read_text() == "remote-base\nlocal-change\n"
    assert (project / "local-note.txt").read_text() == "local-untracked\n"
    assert git("config", "--get", "remote.upstream.fetch") == "+refs/heads/*:refs/remotes/upstream/*"


def test_git_reattachment_preserves_restored_files_after_ssh_rejection(tmp_path, git_archive):
    """A rejected SSH connection must be reported without losing archived worktree files."""
    (tmp_path / "reject-ssh").touch()
    result = restore_git_archive(tmp_path, git_archive)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Host key verification failed" in result.stdout
    assert '"status": "failed"' in result.stdout
    project = tmp_path / "target-home/Documents/dev-projects/client"
    assert (project / "tracked.txt").read_text() == "remote-base\nlocal-change\n"
    assert (project / "local-note.txt").read_text() == "local-untracked\n"
    assert not (project / ".git").exists()
    assert not project.with_name("client.workstation-manager-restore-overlay").exists()


def test_git_restore_check_mode_does_not_connect_or_extract(tmp_path, git_archive):
    """A restore preview must leave project files and SSH host trust untouched."""
    result = restore_git_archive(tmp_path, git_archive, check=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not list((tmp_path / "target-home").iterdir())
    assert not (tmp_path / "ssh-calls.jsonl").exists()
