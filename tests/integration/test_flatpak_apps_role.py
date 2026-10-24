"""Exercise Flatpak updates, retries, and setup concurrency through isolated Ansible roles."""

from __future__ import annotations

import json
from pathlib import Path

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

FIXTURE_OPERATIONS = r"""
import time

if operation == "flatpak" and args["state"] == "absent":
    with path.with_suffix(".removals").open("a") as removals:
        removals.write(args["name"] + "\n")
    state["applications"].pop(args["name"], None)
elif operation in ("flatpak_remote", "flatpak"):
    if args["method"] != "system":
        module.fail_json(msg="Expected system-wide installation")
    if operation == "flatpak" and args["remote"] not in state["remotes"]:
        module.fail_json(msg="Remote must exist before installing applications")
    if operation == "flatpak" and not module.check_mode:
        with path.with_suffix(".attempts").open("a") as attempts:
            attempts.write("install\n")
        path.with_suffix(".started").touch()
        if state.get("await_release"):
            deadline = time.monotonic() + 5
            while not path.with_suffix(".release").exists():
                if time.monotonic() > deadline:
                    module.fail_json(msg="Development did not run while Flatpak was pending")
                time.sleep(0.05)
            time.sleep(0.3)
    if not module.check_mode and state["failures"][operation] > 0:
        state["failures"][operation] -= 1
        if operation == "flatpak":
            # A failed transaction can leave some applications installed.
            state["applications"].setdefault(args["name"][0], "current")
        path.write_text(json.dumps(state))
        module.fail_json(msg="Synthetic download failure: SSL connect error")
    if operation == "flatpak_remote":
        state["remotes"] = sorted(set(state["remotes"]) | {args["name"]})
    else:
        for name in args["name"]:
            if name not in state["applications"] or args["state"] == "latest":
                state["applications"][name] = "current"
        if not module.check_mode:
            path.with_suffix(".finished").touch()
elif operation == "development":
    if not module.check_mode and state.get("await_release"):
        deadline = time.monotonic() + 5
        while not path.with_suffix(".started").exists():
            if time.monotonic() > deadline:
                module.fail_json(msg="Flatpak was not started before development")
            time.sleep(0.05)
        if path.with_suffix(".finished").exists():
            module.fail_json(msg="Flatpak completed before development could overlap")
        path.with_suffix(".release").touch()
    if state.get("development_fails"):
        module.fail_json(msg="Synthetic development failure")
    module.exit_json(changed=False)
elif operation == "consumer":
    if not module.check_mode and not path.with_suffix(".finished").exists():
        module.fail_json(msg="Setup continued before Flatpak completed")
    if not module.check_mode:
        path.with_suffix(".consumed").touch()
    module.exit_json(changed=False)
"""


def isolated_role_tasks(directory: Path, state_file: Path) -> None:
    """Keep real role control flow and async modules, replacing only external operations."""

    def shorten_waits(task):
        if "delay" in task:
            task["delay"] = 0
        if "ansible.builtin.pause" in task:
            task["ansible.builtin.pause"]["seconds"] = 0
        if "async" in task:
            task["async"] = 15
        for section in ("block", "rescue", "always"):
            for nested in task.get(section, []):
                shorten_waits(nested)

    source = SETUP_ROLES / "flatpak_apps/tasks"
    for path in source.rglob("*.yml"):
        tasks = []
        for task in DataLoader().load_from_file(str(path)):
            if any(
                module in task for module in ("ansible.builtin.apt", "ansible.builtin.stat", "community.general.dconf")
            ):
                continue
            for operation in ("flatpak_remote", "flatpak"):
                module = "community.general." + operation
                if module in task:
                    arguments = task.pop(module)
                    task["ansible.legacy.fixture_flatpak"] = {
                        "operation": operation,
                        "arguments": arguments,
                        "state_file": str(state_file),
                    }
            shorten_waits(task)
            tasks.append(task)
        target = directory / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(tasks))


@pytest.fixture(name="flatpak_playbook")
def flatpak_playbook_fixture(tmp_path):
    """Keep collection role loading, retries, and conditions while isolating external downloads."""
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "failures": {"flatpak_remote": 0, "flatpak": 0},
                "remotes": [],
                "applications": {"org.example.Personal": "older", "org.example.First": "older"},
            }
        )
    )
    library = tmp_path / "library"
    library.mkdir()
    write_stateful_module(library / "fixture_flatpak.py", FIXTURE_OPERATIONS)
    collections = tmp_path / "collections"
    isolated_role_tasks(
        collections / "ansible_collections/neilime/workstation_setup/roles/flatpak_apps/tasks", state_file
    )
    playbook = write_local_playbook(
        tmp_path / "playbook.json",
        [{"ansible.builtin.import_role": {"name": "neilime.workstation_setup.flatpak_apps"}}],
        desktop_variables(
            tmp_path / "home",
            desktop={"flatpak": {"remote": "fixture", "packages": ["org.example.First", "org.example.Second"]}},
        ),
    )
    data = json.loads(playbook.read_text())
    data[0]["vars"]["ansible_async_dir"] = str(tmp_path / "async")
    playbook.write_text(json.dumps(data))
    environment = ansible_environment(tmp_path, ANSIBLE_LIBRARY=str(library))
    environment["ANSIBLE_COLLECTIONS_PATH"] = f"{collections}:{environment['ANSIBLE_COLLECTIONS_PATH']}"
    return (
        ["ansible-playbook", "-i", "localhost,", str(playbook)],
        environment,
        state_file,
    )


@pytest.fixture(name="setup_playbook")
def setup_playbook_fixture(flatpak_playbook):
    """Run the production role entrypoints and setup block with only external work isolated."""
    command, _environment, state_file = flatpak_playbook
    playbook = Path(command[-1])
    data = json.loads(playbook.read_text(encoding="utf-8"))
    setup = SETUP_ROLES.parents[4] / "tasks/setup_action.yml"
    block = next(task for task in DataLoader().load_from_file(str(setup)) if "always" in task)
    for task in block["block"]:
        if task["ansible.builtin.import_role"]["name"].endswith(".development_tooling"):
            del task["ansible.builtin.import_role"]
            task["ansible.legacy.fixture_flatpak"] = {
                "operation": "development",
                "arguments": {},
                "state_file": str(state_file),
            }
    data[0]["tasks"] = [
        block,
        {
            "ansible.legacy.fixture_flatpak": {"operation": "consumer", "arguments": {}, "state_file": str(state_file)},
            "when": "workstation_manager_resolved.desktop.flatpak.packages | length > 0",
        },
    ]
    playbook.write_text(json.dumps(data), encoding="utf-8")
    return flatpak_playbook


def test_flatpak_downloads_recover_and_converge(flatpak_playbook) -> None:
    """Install and update declared apps after partial failures, preserving unmanaged apps."""
    command, environment, state_file = flatpak_playbook
    original = json.loads(state_file.read_text())
    original["failures"] = {"flatpak_remote": 1, "flatpak": 2}
    state_file.write_text(json.dumps(original))

    result = run_playbook(command, environment)
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads(state_file.read_text())
    assert state == {
        "failures": {"flatpak_remote": 0, "flatpak": 0},
        "remotes": ["fixture"],
        "applications": {
            "org.example.First": "current",
            "org.example.Personal": "older",
            "org.example.Second": "current",
        },
    }
    repeated = run_playbook(command, environment)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout
    assert json.loads(state_file.read_text()) == state


@pytest.mark.parametrize("operation", ["flatpak_remote", "flatpak"])
def test_flatpak_persistent_download_failure_stops_setup(flatpak_playbook, operation) -> None:
    """Exhausted download retries still fail instead of reporting incomplete setup as successful."""
    command, environment, state_file = flatpak_playbook
    state = json.loads(state_file.read_text())
    state["failures"][operation] = 100
    state_file.write_text(json.dumps(state))

    result = run_playbook(command, environment)
    assert result.returncode != 0
    assert "Synthetic download failure: SSL connect error" in result.stdout + result.stderr
    remaining = json.loads(state_file.read_text())
    assert 1 < 100 - remaining["failures"][operation] <= 5
    assert "org.example.Second" not in remaining["applications"]


def test_flatpak_preview_preserves_installed_state(flatpak_playbook) -> None:
    """Check mode previews applications without writing state or consuming download attempts."""
    command, environment, state_file = flatpak_playbook
    state = json.loads(state_file.read_text())
    state["remotes"] = ["fixture"]
    state["failures"]["flatpak"] = 2
    state_file.write_text(json.dumps(state))

    result = run_playbook([*command, "--check"], environment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(state_file.read_text()) == state


@pytest.mark.parametrize("failures", [0, 2, 100])
def test_setup_joins_flatpak_and_preserves_retry_budget(setup_playbook, failures) -> None:
    """Overlap independent work, retry failed downloads, and stop consumers on exhausted retries."""
    command, environment, state_file = setup_playbook
    state = json.loads(state_file.read_text())
    state.update(await_release=True)
    state["failures"]["flatpak"] = failures
    state_file.write_text(json.dumps(state))

    result = run_playbook(command, environment)
    assert (result.returncode == 0) == (failures < 4), result.stdout + result.stderr
    attempts = state_file.with_suffix(".attempts").read_text().splitlines()
    assert len(attempts) == min(failures + 1, 4)
    assert state_file.with_suffix(".consumed").exists() == (failures < 4)
    assert state_file.with_suffix(".removals").exists() == (failures < 4)
    assert not list((state_file.parent / "async").glob("*"))
    if failures < 4:
        assert json.loads(state_file.read_text())["applications"] == {
            "org.example.First": "current",
            "org.example.Personal": "older",
            "org.example.Second": "current",
        }
    if failures == 0:
        state = json.loads(state_file.read_text())
        state["await_release"] = False
        state_file.write_text(json.dumps(state))
        repeated = run_playbook(command, environment)
        assert repeated.returncode == 0, repeated.stdout + repeated.stderr
        assert "changed=0" in repeated.stdout


def test_setup_waits_for_pending_flatpak_after_development_failure(setup_playbook) -> None:
    """A development failure still completes and cleans the running Flatpak job before returning failure."""
    command, environment, state_file = setup_playbook
    state = json.loads(state_file.read_text())
    state.update(await_release=True, development_fails=True)
    state_file.write_text(json.dumps(state))

    result = run_playbook(command, environment)
    assert result.returncode != 0
    assert "Synthetic development failure" in result.stdout + result.stderr
    assert state_file.with_suffix(".finished").exists()
    assert not state_file.with_suffix(".consumed").exists()
    assert not list((state_file.parent / "async").glob("*"))


def test_setup_preview_runs_synchronously_without_a_background_job(setup_playbook) -> None:
    """Setup check mode retains the synchronous Flatpak preview and starts no worker."""
    command, environment, state_file = setup_playbook
    state = json.loads(state_file.read_text())
    state["remotes"] = ["fixture"]
    state_file.write_text(json.dumps(state))

    result = run_playbook([*command, "--check"], environment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(state_file.read_text()) == state
    assert not state_file.with_suffix(".started").exists()
    assert not list((state_file.parent / "async").glob("*"))
    assert len(state_file.with_suffix(".removals").read_text().splitlines()) == 2


def test_setup_with_no_flatpak_applications_starts_no_worker(setup_playbook) -> None:
    """An empty application list requires no asynchronous job or completion result."""
    command, environment, state_file = setup_playbook
    playbook = Path(command[-1])
    data = json.loads(playbook.read_text(encoding="utf-8"))
    data[0]["vars"]["workstation_manager_resolved"]["desktop"]["flatpak"]["packages"] = []
    playbook.write_text(json.dumps(data), encoding="utf-8")

    result = run_playbook(command, environment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(state_file.read_text())["applications"] == {
        "org.example.Personal": "older",
        "org.example.First": "older",
    }
    assert not state_file.with_suffix(".started").exists()
    assert len(state_file.with_suffix(".removals").read_text().splitlines()) == 2


@pytest.mark.parametrize("fixture_name", ["flatpak_playbook", "setup_playbook"])
def test_native_scanner_removes_a_configured_flatpak_duplicate(request, fixture_name) -> None:
    """Both direct and overlapped installation retain the native scanner as the sole managed copy."""
    command, environment, state_file = request.getfixturevalue(fixture_name)
    playbook = Path(command[-1])
    data = json.loads(playbook.read_text(encoding="utf-8"))
    data[0]["vars"]["workstation_manager_resolved"]["desktop"]["flatpak"]["packages"].append("org.gnome.SimpleScan")
    playbook.write_text(json.dumps(data), encoding="utf-8")

    result = run_playbook(command, environment)
    assert result.returncode == 0, result.stdout + result.stderr
    applications = json.loads(state_file.read_text())["applications"]
    assert "org.gnome.SimpleScan" not in applications
    assert "org.example.Personal" in applications
