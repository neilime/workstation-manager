"""Exercise Git signing setup without modifying Chezmoi-managed Git configuration."""

from __future__ import annotations

import json
import os
import pathlib
import pwd
import subprocess
import sys

import pytest

TASK_FILE = (
    pathlib.Path(__file__).parents[2]
    / "ansible/collections/ansible_collections/neilime/workstation_setup"
    / "roles/gpg_keys/tasks/git_signing.yml"
)
FINGERPRINT = "0123456789ABCDEF0123456789ABCDEF0123456789"


@pytest.fixture(name="git_signing")
def fixture_git_signing(tmp_path: pathlib.Path) -> tuple[pathlib.Path, dict[str, str]]:
    """Create an isolated target home containing a Chezmoi-managed .gitconfig."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".config").mkdir(mode=0o700)
    (home / ".gitconfig").write_text("# managed by Chezmoi\n[user]\n\tname = Fixture\n")
    config = tmp_path / "ansible.cfg"
    config.write_text("[defaults]\n")
    (tmp_path / "playbook.json").write_text(
        json.dumps(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "vars": {
                        "ansible_python_interpreter": sys.executable,
                        "workstation_manager_use_become": False,
                        "workstation_manager_resolved": {
                            "user": {"name": pwd.getpwuid(os.getuid()).pw_name, "home": str(home)},
                        },
                        "gpg_keys_signing_fingerprint": FINGERPRINT,
                    },
                    "tasks": [{"ansible.builtin.import_tasks": str(TASK_FILE)}],
                }
            ]
        )
    )
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "LC_ALL": "C.UTF-8",
        "GIT_CONFIG_NOSYSTEM": "1",
        "ANSIBLE_CONFIG": str(config),
        "ANSIBLE_HOME": str(tmp_path / ".ansible"),
        "ANSIBLE_COLLECTIONS_PATH": os.environ.get(
            "ANSIBLE_COLLECTIONS_PATH", str(pathlib.Path.home() / ".ansible/collections")
        ),
    }
    return tmp_path, env


def apply_signing(
    fixture: tuple[pathlib.Path, dict[str, str]], *, check: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run the production signing tasks using the fixture home and collection path."""
    root, env = fixture
    command = ["ansible-playbook", "-i", "localhost,", str(root / "playbook.json")]
    if check:
        command.append("--check")
    return subprocess.run(command, env=env, capture_output=True, text=True, check=False, timeout=60)


@pytest.mark.parametrize("existing_config", [False, True])
def test_signing_preserves_dotfiles_and_other_git_settings(git_signing, existing_config: bool) -> None:
    """Configure effective signing without changing .gitconfig or unrelated settings."""
    root, env = git_signing
    home = root / "home"
    original = (home / ".gitconfig").read_bytes()
    git_config = home / ".config/git/config"
    if existing_config:
        git_config.parent.mkdir(mode=0o700)
        git_config.write_text("[alias]\n\tfixture = status\n")
    result = apply_signing(git_signing)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (home / ".gitconfig").read_bytes() == original
    assert (home / ".config").stat().st_mode & 0o777 == 0o700
    assert git_config.stat().st_mode & 0o777 == 0o600
    # Use the query syntax supported by Ubuntu 24.04's Git 2.43.
    for key, expected in {
        "user.name": "Fixture",
        "user.signingkey": FINGERPRINT,
        "gpg.format": "openpgp",
        "commit.gpgsign": "true",
        "tag.gpgsign": "true",
        **({"alias.fixture": "status"} if existing_config else {}),
    }.items():
        value = subprocess.check_output(["git", "config", "--get", key], cwd=root, env=env, text=True)
        assert value.strip() == expected
    repeated = apply_signing(git_signing)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout
    assert (home / ".gitconfig").read_bytes() == original


def test_signing_check_mode_does_not_create_or_modify_git_config(git_signing) -> None:
    """A fresh-machine preview must preserve both user config files."""
    root, _ = git_signing
    home = root / "home"
    original = (home / ".gitconfig").read_bytes()
    result = apply_signing(git_signing, check=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (home / ".config/git/config").exists()
    assert (home / ".gitconfig").read_bytes() == original
