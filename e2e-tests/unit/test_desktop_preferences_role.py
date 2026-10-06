"""Check that unset personal preferences leave the desktop untouched."""

from __future__ import annotations

import json
import os
import pathlib
import pwd
import subprocess
import sys

from ansible.parsing.dataloader import DataLoader


def test_unset_desktop_preferences_do_not_access_dconf(tmp_path) -> None:
    """A setup without overrides or wallpaper must work without a desktop bus."""
    # Role fixtures repeat the Ansible play and isolated environment contract.
    # pylint: disable=duplicate-code
    task_file = (
        pathlib.Path(__file__).parents[2]
        / "ansible/collections/ansible_collections/neilime/workstation_setup"
        / "roles/gnome_preferences/tasks/main.yml"
    )
    tasks = [
        task
        for task in DataLoader().load_from_file(str(task_file))
        if "community.general.dconf" in task or task.get("register") == "workstation_manager_gnome_wallpaper"
    ]
    home = tmp_path / "home"
    database = home / ".config/dconf/user"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"existing desktop state")
    config = tmp_path / "ansible.cfg"
    config.write_text("[defaults]\n")
    playbook = tmp_path / "playbook.json"
    playbook.write_text(
        json.dumps(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "vars": {
                        "ansible_python_interpreter": sys.executable,
                        "workstation_manager_gnome_use_become_user": False,
                        "workstation_manager_resolved": {
                            "user": {"name": pwd.getpwuid(os.getuid()).pw_name, "home": str(home)},
                            "desktop": {"gnome": {"dark_mode": None, "show_trash": None, "favorites": None}},
                        },
                    },
                    "tasks": tasks,
                }
            ]
        )
    )
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={tmp_path}/missing-bus",
        "ANSIBLE_CONFIG": str(config),
        "ANSIBLE_HOME": str(tmp_path / ".ansible"),
        "ANSIBLE_COLLECTIONS_PATH": os.environ.get("ANSIBLE_COLLECTIONS_PATH", ""),
    }
    result = subprocess.run(
        ["ansible-playbook", "-i", "localhost,", str(playbook)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "changed=0" in result.stdout
    assert database.read_bytes() == b"existing desktop state"
    assert not (home / ".local/share/backgrounds/wallpaper.jpg").exists()
    # pylint: enable=duplicate-code
