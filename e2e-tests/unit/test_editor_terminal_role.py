"""Exercise VS Code host-terminal setup in isolated homes through real Ansible."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

COLLECTIONS_PATH = pathlib.Path(__file__).parents[2] / "ansible/collections"


def apply(root: pathlib.Path, *, check: bool = False, editor_packages=None) -> subprocess.CompletedProcess[str]:
    """Configure only the fixture's editor settings, without launching Flatpak or Zsh."""

    (root / "ansible.cfg").write_text("[defaults]\n")
    playbook = root / "playbook.json"
    playbook.write_text(
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
                            "user": {"name": "fixture-user", "home": str(root / "home")},
                            "development": {
                                "editor_packages": ["com.visualstudio.code"]
                                if editor_packages is None
                                else editor_packages,
                            },
                        },
                    },
                    "roles": ["neilime.workstation_setup.editor_terminal"],
                }
            ]
        )
    )
    arguments = ["ansible-playbook", "--inventory", "localhost,", str(playbook)]
    if check:
        arguments.append("--check")
    return subprocess.run(
        arguments,
        cwd=root,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(root),
            "ANSIBLE_CONFIG": str(root / "ansible.cfg"),
            "ANSIBLE_HOME": str(root / ".ansible"),
            "ANSIBLE_COLLECTIONS_PATH": str(COLLECTIONS_PATH),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def settings_path(root: pathlib.Path) -> pathlib.Path:
    """Use the Flatpak application's actual user-config location."""

    return root / "home/.var/app/com.visualstudio.code/config/Code/User/settings.json"


def test_fresh_installation_creates_a_private_idempotent_terminal_configuration(tmp_path):
    """Setup must expose host Zsh even before VS Code has been opened once."""

    result = apply(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    path = settings_path(tmp_path)
    assert json.loads(path.read_text())["terminal.integrated.defaultProfile.linux"] == "zsh (host)"
    assert path.stat().st_mode & 0o777 == 0o600
    repeat = apply(tmp_path)
    assert repeat.returncode == 0, repeat.stdout + repeat.stderr
    assert "changed=0" in repeat.stdout


def test_existing_settings_comments_permissions_and_symlinks_are_preserved(tmp_path):
    """Settings managed through a dotfile symlink must retain the link and private attributes."""

    path = settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    source = tmp_path / "personal-settings.json"
    source.write_text(
        '{\n  // preserve this\n  "editor.fontSize": 19,\n  "fixture.secret": "synthetic-private-marker",\n}\n'
    )
    source.chmod(0o640)
    path.symlink_to(source)
    result = apply(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert path.is_symlink()
    assert "// preserve this" in source.read_text()
    assert '"editor.fontSize": 19' in source.read_text()
    assert path.stat().st_mode & 0o777 == 0o640
    assert "synthetic-private-marker" not in result.stdout + result.stderr


@pytest.mark.parametrize("existing", [False, True])
def test_check_mode_does_not_create_or_modify_settings(tmp_path, existing):
    """A preview should report changes without creating directories or changing editor settings."""

    path = settings_path(tmp_path)
    original = '{"editor.fontSize": 19}\n'
    if existing:
        path.parent.mkdir(parents=True)
        path.write_text(original)
    result = apply(tmp_path, check=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "changed=1" in result.stdout
    assert path.exists() == existing
    if existing:
        assert path.read_text() == original
    else:
        assert not (tmp_path / "home").exists()


@pytest.mark.parametrize("packages", [[], ["other.editor"]])
def test_other_editors_do_not_receive_vscode_configuration(tmp_path, packages):
    """Editor selection must gate the configuration without introducing Flatpak user files."""

    result = apply(tmp_path, editor_packages=packages)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "home").exists()


def test_invalid_settings_stop_setup_without_overwriting_the_file(tmp_path):
    """An invalid settings file must produce a useful failure instead of replacing personal preferences."""

    path = settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    original = '{"synthetic-private-marker":'
    path.write_text(original)
    result = apply(tmp_path)
    assert result.returncode != 0
    assert "Cannot configure VS Code terminal" in result.stdout
    assert "synthetic-private-marker" not in result.stdout + result.stderr
    assert path.read_text() == original
