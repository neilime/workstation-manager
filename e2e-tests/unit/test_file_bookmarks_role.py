"""Exercise Files bookmark setup in an isolated managed user's home."""

from __future__ import annotations

import json
import os
import pathlib
import pwd
import subprocess
import sys

import pytest
from ansible.parsing.dataloader import DataLoader

TASK_DIRECTORY = (
    pathlib.Path(__file__).parents[2]
    / "ansible/collections/ansible_collections/neilime/workstation_setup/roles/gnome_preferences/tasks"
)


@pytest.fixture(name="bookmarks_setup")
def fixture_bookmarks_setup(tmp_path: pathlib.Path) -> tuple[pathlib.Path, dict[str, str]]:
    """Run the GNOME bookmark task entrypoint without touching the desktop."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".config").mkdir(mode=0o700)
    task = next(
        task
        for task in DataLoader().load_from_file(str(TASK_DIRECTORY / "main.yml"))
        if task.get("ansible.builtin.import_tasks") == "file_bookmarks.yml"
    )
    task["ansible.builtin.import_tasks"] = str(TASK_DIRECTORY / "file_bookmarks.yml")
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
                            "user": {
                                "name": pwd.getpwuid(os.getuid()).pw_name,
                                "home": str(home),
                                "projects_directory": "{{ fixture_projects_directory }}",
                            },
                        },
                    },
                    "tasks": [task],
                }
            ]
        )
    )
    config = tmp_path / "ansible.cfg"
    config.write_text("[defaults]\n")
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "XDG_CONFIG_HOME": str(tmp_path / "ide-config"),
        "LC_ALL": "C.UTF-8",
        "ANSIBLE_CONFIG": str(config),
        "ANSIBLE_HOME": str(tmp_path / ".ansible"),
    }
    return tmp_path, environment


def run_setup(
    fixture: tuple[pathlib.Path, dict[str, str]], projects: pathlib.Path, *, check: bool = False
) -> subprocess.CompletedProcess[str]:
    """Apply the production bookmark tasks to the fixture's projects directory."""
    root, environment = fixture
    command = [
        "ansible-playbook",
        "--inventory",
        "localhost,",
        str(root / "playbook.json"),
        "--extra-vars",
        json.dumps({"fixture_projects_directory": str(projects)}),
    ]
    if check:
        command.append("--check")
    return subprocess.run(command, env=environment, capture_output=True, text=True, check=False, timeout=60)


@pytest.mark.parametrize("directory", ["home/Documents/dev-projects", "custom projects/café #1%"])
@pytest.mark.parametrize("existing_label", [None, "", "/ My projects"])
def test_setup_preserves_bookmarks_and_is_idempotent(bookmarks_setup, directory, existing_label) -> None:
    """Add an encoded project URI once, preserving existing entries and labels."""
    root, _ = bookmarks_setup
    projects = root / directory
    projects.mkdir(parents=True)
    bookmarks = root / "home/.config/gtk-3.0/bookmarks"
    bookmarks.parent.mkdir(mode=0o750)
    original = f"{projects.as_uri()}-other Other projects\nfile:///tmp/Documents Documents\n"
    if existing_label is not None:
        original += f"{projects.as_uri()}{existing_label}\n"
    bookmarks.write_text(original)
    bookmarks.chmod(0o640)

    initial = run_setup(bookmarks_setup, projects)

    assert initial.returncode == 0, initial.stdout + initial.stderr
    expected = original if existing_label is not None else original + f"{projects.as_uri()}\n"
    assert bookmarks.read_text() == expected
    assert bookmarks.stat().st_uid == os.getuid()
    assert bookmarks.stat().st_mode & 0o777 == 0o640
    assert bookmarks.parent.stat().st_mode & 0o777 == 0o750
    assert (root / "home/.config").stat().st_mode & 0o777 == 0o700
    assert not (root / "ide-config").exists()
    repeated = run_setup(bookmarks_setup, projects)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout
    assert bookmarks.read_text() == expected


@pytest.mark.parametrize("existing_file", [False, True])
def test_check_mode_preserves_bookmarks_and_normal_setup_creates_them(bookmarks_setup, existing_file: bool) -> None:
    """A fresh or existing home supports a preview without any bookmark writes."""
    root, _ = bookmarks_setup
    projects = root / "home/Documents/dev-projects"
    projects.mkdir(parents=True)
    bookmarks = root / "home/.config/gtk-3.0/bookmarks"
    original = "file:///tmp/Documents Documents\n"
    if existing_file:
        bookmarks.parent.mkdir()
        bookmarks.write_text(original)

    preview = run_setup(bookmarks_setup, projects, check=True)

    assert preview.returncode == 0, preview.stdout + preview.stderr
    if existing_file:
        assert bookmarks.read_text() == original
    else:
        assert not bookmarks.parent.exists()
    applied = run_setup(bookmarks_setup, projects)
    assert applied.returncode == 0, applied.stdout + applied.stderr
    expected = (original if existing_file else "") + f"{projects.as_uri()}\n"
    assert bookmarks.read_text() == expected
    if not existing_file:
        assert bookmarks.stat().st_mode & 0o777 == 0o600
        assert bookmarks.parent.stat().st_mode & 0o777 == 0o700
