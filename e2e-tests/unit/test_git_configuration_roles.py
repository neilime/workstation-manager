"""Exercise Git setup without modifying Chezmoi-managed Git configuration."""

from __future__ import annotations

import json
import os
import pathlib
import pwd
import subprocess
import sys

import pytest

ROLES_DIRECTORY = (
    pathlib.Path(__file__).parents[2] / "ansible/collections/ansible_collections/neilime/workstation_setup" / "roles"
)
FINGERPRINT = "0123456789ABCDEF0123456789ABCDEF0123456789"
SIGNING_SETTINGS = {
    "user.signingkey": FINGERPRINT,
    "gpg.format": "openpgp",
    "commit.gpgsign": "true",
    "tag.gpgsign": "true",
}


@pytest.fixture(
    name="git_configuration",
    params=[
        ("gpg_keys/tasks/git_signing.yml", SIGNING_SETTINGS),
        ("development_tooling/tasks/git.yml", {"gc.auto": "6700"}),
    ],
    ids=["signing", "automatic-gc"],
)
def fixture_git_configuration(
    tmp_path: pathlib.Path, request: pytest.FixtureRequest
) -> tuple[pathlib.Path, dict[str, str], dict[str, str]]:
    """Create an isolated target home containing a Chezmoi-managed .gitconfig."""
    task_file, expected_settings = request.param
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
                    "tasks": [{"ansible.builtin.import_tasks": str(ROLES_DIRECTORY / task_file)}],
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
    return tmp_path, env, expected_settings


def apply_configuration(
    fixture: tuple[pathlib.Path, dict[str, str], dict[str, str]], *, check: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run production Git tasks using the fixture home and collection path."""
    root, env, _ = fixture
    command = ["ansible-playbook", "-i", "localhost,", str(root / "playbook.json")]
    if check:
        command.append("--check")
    return subprocess.run(command, env=env, capture_output=True, text=True, check=False, timeout=60)


@pytest.mark.parametrize("existing_config", [False, True])
def test_configuration_preserves_dotfiles_and_other_git_settings(git_configuration, existing_config: bool) -> None:
    """Apply effective settings without changing .gitconfig or unrelated settings."""
    root, env, expected_settings = git_configuration
    home = root / "home"
    original = (home / ".gitconfig").read_bytes()
    git_config = home / ".config/git/config"
    if existing_config:
        git_config.parent.mkdir(mode=0o700)
        git_config.write_text("[alias]\n\tfixture = status\n[gc]\n\tauto = 0\n")
    result = apply_configuration(git_configuration)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (home / ".gitconfig").read_bytes() == original
    assert (home / ".config").stat().st_mode & 0o777 == 0o700
    assert git_config.stat().st_mode & 0o777 == 0o600
    # Use the query syntax supported by Ubuntu 24.04's Git 2.43.
    for key, expected in {
        "user.name": "Fixture",
        **({"alias.fixture": "status", "gc.auto": "0"} if existing_config else {}),
        **expected_settings,
    }.items():
        value = subprocess.check_output(["git", "config", "--get", key], cwd=root, env=env, text=True)
        assert value.strip() == expected
    repeated = apply_configuration(git_configuration)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout
    assert (home / ".gitconfig").read_bytes() == original


@pytest.mark.parametrize("existing_config", [False, True])
def test_configuration_check_mode_does_not_create_or_modify_git_config(
    git_configuration, existing_config: bool
) -> None:
    """A preview must preserve both absent and existing user config files."""
    root, _, _ = git_configuration
    home = root / "home"
    original = (home / ".gitconfig").read_bytes()
    git_config = home / ".config/git/config"
    existing_content = "[gc]\n\tauto = 0\n"
    if existing_config:
        git_config.parent.mkdir(mode=0o700)
        git_config.write_text(existing_content)
    result = apply_configuration(git_configuration, check=True)
    assert result.returncode == 0, result.stdout + result.stderr
    if existing_config:
        assert git_config.read_text() == existing_content
    else:
        assert not git_config.exists()
    assert (home / ".gitconfig").read_bytes() == original
