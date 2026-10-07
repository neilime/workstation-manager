"""Exercise browser associations without changing the host desktop."""

from __future__ import annotations

import configparser
import pathlib

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible_test_helpers import (
    ansible_environment,
    managed_user,
    run_playbook,
    write_local_playbook,
)

pytestmark = pytest.mark.integration

TASK_FILE = (
    pathlib.Path(__file__).parents[2]
    / "ansible/collections/ansible_collections/neilime/workstation_setup"
    / "roles/browser_brave/tasks/default_browser.yml"
)


MIME_ASSOCIATIONS = "[Default Applications]\napplication/pdf=fixture.desktop\ntext/html=old.desktop\n"


@pytest.mark.parametrize("existing_mode,check", [(None, False), (None, True), (0o750, False), (0o700, True)])
def test_browser_setup_preserves_config_permissions_and_other_associations(tmp_path, existing_mode, check) -> None:
    """Development and browser setup preserve Chezmoi permissions and MIME choices."""
    home = tmp_path / "home"
    home.mkdir()
    directory = home / ".config"
    if existing_mode is not None:
        directory.mkdir(mode=existing_mode)
        (directory / "mimeapps.list").write_text(MIME_ASSOCIATIONS)
    playbook = tmp_path / "playbook.json"
    tasks = [
        task
        for task in DataLoader().load_from_file(str(TASK_FILE.parents[2] / "development_tooling/tasks/main.yml"))
        if task["name"] in ("Inspect development config directory permissions", "Ensure mise user directories exist")
    ]
    assert len(tasks) == 2
    tasks.append({"ansible.builtin.import_tasks": str(TASK_FILE)})
    write_local_playbook(
        playbook,
        tasks,
        {
            "workstation_manager_use_become": False,
            "workstation_manager_resolved": {
                "user": managed_user(home, state_dir=str(home / ".local/state/workstation-manager"))
            },
            "workstation_manager_browser_desktop_file": "brave-browser.desktop",
        },
    )
    environment = ansible_environment(tmp_path, HOME=str(home))
    command = ["ansible-playbook", "-i", "localhost,", str(playbook)]
    if check:
        command.append("--check")
    result = run_playbook(command, environment)
    assert result.returncode == 0, result.stdout + result.stderr
    if check:
        if existing_mode is None:
            assert not directory.exists()
        else:
            assert directory.stat().st_mode & 0o777 == existing_mode
            assert (directory / "mimeapps.list").read_text() == MIME_ASSOCIATIONS
        return

    assert directory.stat().st_mode & 0o777 == (existing_mode or 0o700)
    for name in ("mimeapps.list", "ubuntu-mimeapps.list", "gnome-mimeapps.list"):
        settings = configparser.ConfigParser()
        settings.read(directory / name)
        for mime in ("x-scheme-handler/http", "x-scheme-handler/https", "text/html"):
            assert settings["Default Applications"][mime] == "brave-browser.desktop"
        if name == "mimeapps.list" and existing_mode is not None:
            assert settings["Default Applications"]["application/pdf"] == "fixture.desktop"
    repeated = run_playbook(command, environment)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout
