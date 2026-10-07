"""Exercise Clipboard Indicator setup without touching a real desktop or Flatpak installation."""

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

pytestmark = pytest.mark.integration

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
    argv = args["argv"]
    result.update(rc=0, stdout="")
    if argv == ["gnome-shell", "--version"]:
        result["stdout"] = "GNOME Shell 999.1"
    elif argv[0] == "pgrep":
        result["rc"] = 0 if state["copyq_running"] else 1
    elif argv == ["flatpak", "run", "com.github.hluk.copyq", "exit"]:
        if state.get("fail_close"):
            module.fail_json(msg="synthetic CopyQ close failure")
        state["copyq_running"] = False
    else:
        module.fail_json(msg="Unexpected clipboard command")
elif operation == "session":
    result.update(available=True, environment={})
elif operation == "flatpak":
    if args["state"] != "absent" or args.get("delete_data"):
        module.fail_json(msg="Only application removal with preserved data is authorized")
    state["flatpaks"][args["method"]] = [app for app in state["flatpaks"][args["method"]] if app != args["name"]]
elif operation == "dconf":
    if args.get("state") == "read":
        result["value"] = state["dconf"].get(args["key"])
    else:
        state["dconf"][args["key"]] = args["value"]
"""


def clipboard_tasks(state_file):
    """Replace desktop integrations while retaining the role's orchestration and file tasks."""
    tasks = DataLoader().load_from_file(str(SETUP_ROLES / "gnome_preferences/tasks/clipboard.yml"))
    adapters = {
        **{"ansible.builtin." + name: name for name in ("apt", "get_url", "unarchive", "command")},
        "community.general.flatpak": "flatpak",
        "community.general.dconf": "dconf",
        "neilime.workstation_setup.desktop_session_info": "session",
    }
    for task in tasks:
        for module, operation in adapters.items():
            if module in task:
                task["fixture_clipboard"] = {
                    "operation": operation,
                    "arguments": task.pop(module) or {},
                    "state_file": str(state_file),
                }
    return tasks


def seed_personal_data(home, conflicting_app):
    """Seed unmanaged data, including the running application's data when present."""
    preserved_files = {home / ".local/share/personal-app/data.bin": b"synthetic personal data"}
    if conflicting_app:
        preserved_files[home / ".var/app/com.github.hluk.copyq/data/history.dat"] = b"synthetic clipboard data"
    for path, content in preserved_files.items():
        path.parent.mkdir(parents=True)
        path.write_bytes(content)
    return preserved_files


def clipboard_fixture(tmp_path, *, conflicting_app=False, corrupt=False, fail_close=False):
    """Use real file tasks and archive validation, isolating external command boundaries."""
    source = tmp_path / "source.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "metadata.json",
            json.dumps(
                {
                    "uuid": "clipboard-indicator@tudmotu.com",
                    "version": 123,
                    "shell-version": ["999"],
                }
            ),
        )
        archive.writestr("extension.js", "// synthetic extension")
    digest = "0" * 64 if corrupt else hashlib.sha256(source.read_bytes()).hexdigest()
    home = tmp_path / "home"
    preferences = home / ".config/clipboard-indicator/settings.ini"
    preferences.parent.mkdir(parents=True)
    preferences.write_text("[clipboard]\nhistory-size=17\npaste-on-select=true\n")
    preserved_files = seed_personal_data(home, conflicting_app)
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "archive": str(source),
                "packages": [],
                "copyq_running": conflicting_app,
                "fail_close": fail_close,
                "flatpaks": {
                    "system": ["example.Other", *(["com.github.hluk.copyq"] if conflicting_app else [])],
                    "user": ["com.github.hluk.copyq"] if conflicting_app else [],
                },
                "dconf": {
                    "/org/gnome/shell/enabled-extensions": "['other@example.test']",
                    "/org/gnome/shell/disabled-extensions": "['clipboard-indicator@tudmotu.com']",
                },
            }
        )
    )
    library = tmp_path / "library"
    library.mkdir()
    write_stateful_module(library / "fixture_clipboard.py", OPERATIONS)
    variables = desktop_variables(home, desktop={"clipboard_indicator": {"version": "123", "sha256": digest}})
    directory = home / ".local/share/workstation-manager/clipboard-indicator" / digest
    variables["workstation_manager_clipboard_directory"] = str(directory)
    playbook = write_local_playbook(tmp_path / "playbook.json", clipboard_tasks(state_file), variables)
    return (
        ["ansible-playbook", "-i", "localhost,", str(playbook)],
        ansible_environment(tmp_path, ANSIBLE_LIBRARY=str(library)),
        state_file,
        preserved_files,
        directory,
    )


@pytest.mark.parametrize("conflicting_app", [False, True])
def test_clipboard_setup_applies_preferences_and_preserves_user_data(tmp_path, conflicting_app):
    """Setup enables one clipboard manager, preserves personal data, and converges."""
    command, environment, state_file, preserved_files, directory = clipboard_fixture(
        tmp_path, conflicting_app=conflicting_app
    )
    original = state_file.read_bytes()
    preview = run_playbook([*command, "--check"], environment)
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert state_file.read_bytes() == original
    assert not directory.exists()
    result = run_playbook(command, environment)
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads(state_file.read_text())
    assert not state["copyq_running"]
    assert state["flatpaks"] == {"system": ["example.Other"], "user": []}
    assert "other@example.test" in state["dconf"]["/org/gnome/shell/enabled-extensions"]
    assert "clipboard-indicator@tudmotu.com" in state["dconf"]["/org/gnome/shell/enabled-extensions"]
    assert state["dconf"]["/org/gnome/shell/disabled-extensions"] == "@as []"
    assert state["dconf"]["/org/gnome/shell/extensions/clipboard-indicator/history-size"] == "17"
    assert state["dconf"]["/org/gnome/shell/extensions/clipboard-indicator/paste-on-select"] == "true"
    for path, content in preserved_files.items():
        assert path.read_bytes() == content
    repeated = run_playbook(command, environment)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout


@pytest.mark.parametrize(("failure", "conflicting_app"), [("corrupt", False), ("fail_close", True)])
def test_clipboard_failure_stops_activation_and_preserves_user_data(tmp_path, failure, conflicting_app):
    """Invalid artifacts and failed shutdown prevent activation without discarding data."""
    command, environment, state_file, preserved_files, _directory = clipboard_fixture(
        tmp_path, conflicting_app=conflicting_app, **{failure: True}
    )
    original = json.loads(state_file.read_text())
    result = run_playbook(command, environment)
    assert result.returncode != 0
    assert ("checksum" if failure == "corrupt" else "synthetic CopyQ close failure") in result.stdout
    state = json.loads(state_file.read_text())
    assert state["copyq_running"] == original["copyq_running"]
    assert state["flatpaks"] == original["flatpaks"]
    assert state["dconf"]["/org/gnome/shell/enabled-extensions"] == "['other@example.test']"
    for path, content in preserved_files.items():
        assert path.read_bytes() == content
