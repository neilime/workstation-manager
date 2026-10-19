"""Exercise managed GNOME extension setup without touching a real desktop."""

from __future__ import annotations

import hashlib
import json
import zipfile

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible_test_helpers import (
    SETUP_ROLES,
    ansible_environment,
    desktop_variables,
    run_playbook,
    write_local_playbook,
    write_stateful_module,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.parametrize(
        "extension",
        [
            pytest.param(
                {
                    "task": "clipboard",
                    "configuration": "clipboard_indicator",
                    "uuid": "clipboard-indicator@tudmotu.com",
                    "profile": ("clipboard-indicator", "clipboard"),
                    "preferences": {"history-size": "17", "paste-on-select": "true"},
                },
                id="clipboard",
            ),
            pytest.param(
                {
                    "task": "system_monitor",
                    "configuration": "system_monitor",
                    "uuid": "Vitals@CoreCoding.com",
                    "profile": ("vitals", "vitals"),
                    "preferences": {"position-in-panel": "2", "show-memory": "true"},
                },
                id="system-monitor",
            ),
        ],
    ),
]

OPERATIONS = r"""
if operation == "apt":
    state["packages"] = sorted(set(state["packages"]) | {args["name"]})
elif operation == "get_url":
    source = Path(state["archive"])
    target = Path(args["dest"])
    if not module.check_mode:
        target.write_bytes(source.read_bytes())
elif operation == "unarchive":
    import zipfile
    if not module.check_mode:
        with zipfile.ZipFile(args["src"]) as archive:
            archive.extractall(args["dest"])
elif operation == "command":
    if args["argv"] != ["gnome-shell", "--version"]:
        module.fail_json(msg="Unexpected GNOME extension command")
    result.update(rc=0, stdout="GNOME Shell 999.1")
elif operation == "dconf":
    if args.get("state") == "read":
        result["value"] = state["dconf"].get(args["key"])
    else:
        state["dconf"][args["key"]] = args["value"]
"""


def extension_tasks(state_file, task_name):
    """Replace desktop integrations while retaining the role's orchestration and file tasks."""
    tasks = DataLoader().load_from_file(str(SETUP_ROLES / f"gnome_preferences/tasks/{task_name}.yml"))
    adapters = {
        **{"ansible.builtin." + name: name for name in ("apt", "get_url", "unarchive", "command")},
        "community.general.dconf": "dconf",
    }
    for task in tasks:
        for module, operation in adapters.items():
            if module in task:
                task["fixture_extension"] = {
                    "operation": operation,
                    "arguments": task.pop(module),
                    "state_file": str(state_file),
                }
    return tasks


def extension_fixture(tmp_path, extension, *, corrupt=False):
    """Use real file tasks and archive validation, isolating external command boundaries."""
    source = tmp_path / "source.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "metadata.json",
            json.dumps(
                {
                    "uuid": extension["uuid"],
                    "version": 123,
                    "shell-version": ["999"],
                }
            ),
        )
        archive.writestr("extension.js", "// synthetic extension")
    digest = "0" * 64 if corrupt else hashlib.sha256(source.read_bytes()).hexdigest()
    home = tmp_path / "home"
    preferences = home / ".config" / extension["profile"][0] / "settings.ini"
    preferences.parent.mkdir(parents=True)
    preferences.write_text(
        f"[{extension['profile'][1]}]\n"
        + "".join(f"{key}={value}\n" for key, value in extension["preferences"].items())
    )
    preserved = home / ".local/share/personal-app/data.bin"
    preserved.parent.mkdir(parents=True)
    preserved.write_bytes(b"synthetic personal data")
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "archive": str(source),
                "packages": [],
                "dconf": {
                    "/org/gnome/shell/enabled-extensions": "['other@example.test']",
                    "/org/gnome/shell/disabled-extensions": repr([extension["uuid"]]),
                },
            }
        )
    )
    library = tmp_path / "library"
    library.mkdir()
    write_stateful_module(library / "fixture_extension.py", OPERATIONS)
    variables = desktop_variables(home, desktop={extension["configuration"]: {"version": "123", "sha256": digest}})
    directory = home / ".local/share/workstation-manager" / extension["configuration"].replace("_", "-") / digest
    variables[f"workstation_manager_{extension['task']}_directory"] = str(directory)
    playbook = write_local_playbook(
        tmp_path / "playbook.json", extension_tasks(state_file, extension["task"]), variables
    )
    return (
        ["ansible-playbook", "-i", "localhost,", str(playbook)],
        ansible_environment(tmp_path, ANSIBLE_LIBRARY=str(library)),
        state_file,
        preserved,
        directory,
    )


def test_extension_setup_applies_preferences_and_preserves_user_data(tmp_path, extension):
    """Setup previews safely, enables the selected extension, preserves data, and converges."""
    command, environment, state_file, preserved, directory = extension_fixture(tmp_path, extension)
    original = state_file.read_bytes()
    preview = run_playbook([*command, "--check"], environment)
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert state_file.read_bytes() == original
    assert not directory.exists()
    result = run_playbook(command, environment)
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads(state_file.read_text())
    assert "other@example.test" in state["dconf"]["/org/gnome/shell/enabled-extensions"]
    assert extension["uuid"] in state["dconf"]["/org/gnome/shell/enabled-extensions"]
    assert state["dconf"]["/org/gnome/shell/disabled-extensions"] == "@as []"
    for key, value in extension["preferences"].items():
        assert state["dconf"][f"/org/gnome/shell/extensions/{extension['profile'][0]}/{key}"] == value
    assert preserved.read_bytes() == b"synthetic personal data"
    repeated = run_playbook(command, environment)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout


def test_extension_failure_stops_activation_and_preserves_user_data(tmp_path, extension):
    """Invalid artifacts prevent activation without discarding data."""
    command, environment, state_file, preserved, _directory = extension_fixture(tmp_path, extension, corrupt=True)
    result = run_playbook(command, environment)
    assert result.returncode != 0
    assert "checksum" in result.stdout
    state = json.loads(state_file.read_text())
    assert state["dconf"]["/org/gnome/shell/enabled-extensions"] == "['other@example.test']"
    assert preserved.read_bytes() == b"synthetic personal data"
