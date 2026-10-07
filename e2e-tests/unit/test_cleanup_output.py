"""Exercise terminal drift summaries without writing files or changing user data."""

from __future__ import annotations

import json

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
if operation == "command":
    argv = args["argv"]
    outputs = {
        ("apt-mark", "showmanual"): "baseline-apt\nextra-apt",
        ("flatpak", "list", "--system", "--app", "--columns=application"): "baseline.App\nextra.App",
        ("apt-get", "--simulate", "dist-upgrade"): "Inst pending-update (1 fixture)",
        ("journalctl", "--vacuum-time=14days", "--vacuum-size=1024M"): "",
    }
    if argv == ["sh", "-lc", "command -v docker"]:
        result.update(rc=1, stdout="", stdout_lines=[], stderr="")
    elif tuple(argv) in outputs:
        output = outputs[tuple(argv)]
        result.update(rc=0, stdout=output, stdout_lines=output.splitlines(), stderr="")
    else:
        module.fail_json(msg="Unexpected cleanup command")
elif operation == "apt":
    if args != {"autoclean": True}:
        module.fail_json(msg="Unexpected package operation")
"""


def cleanup_tasks(state_file):
    """Run real filesystem inspection and reporting with isolated OS maintenance boundaries."""
    directory = SETUP_ROLES.parents[1] / "workstation_cleanup/roles/cleanup/tasks"
    loader = DataLoader()
    tasks = []
    for task in loader.load_from_file(str(directory / "main.yml")):
        if "ansible.builtin.import_tasks" in task:
            tasks.extend(loader.load_from_file(str(directory / task["ansible.builtin.import_tasks"])))
        else:
            tasks.append(task)
    for task in tasks:
        for operation in ("command", "apt"):
            if "ansible.builtin." + operation in task:
                task["fixture_cleanup"] = {
                    "operation": operation,
                    "arguments": task.pop("ansible.builtin." + operation),
                    "state_file": str(state_file),
                }
    return tasks


def cleanup_context(tmp_path):
    """Keep all state and browser profiles inside the temporary managed home."""
    home = tmp_path / "home"
    home.mkdir()
    variables = desktop_variables(home, system={"state_dir": str(tmp_path / "system")}, desktop={"browser": "brave"})
    variables["workstation_manager_resolved"]["user"]["state_dir"] = str(home / ".local/state/workstation-manager-v1")
    variables["workstation_manager_browser_profiles"] = []
    state_file = tmp_path / "fixture.json"
    state_file.write_text("{}")
    library = tmp_path / "library"
    library.mkdir()
    write_stateful_module(library / "fixture_cleanup.py", OPERATIONS)
    playbook = write_local_playbook(tmp_path / "playbook.json", cleanup_tasks(state_file), variables)
    return (
        ["ansible-playbook", "-i", "localhost,", str(playbook)],
        ansible_environment(tmp_path, ANSIBLE_LIBRARY=str(library)),
    )


def seed_baseline_and_drift(home, system):
    """Provide both a managed baseline and unrelated data in every inspected location."""
    user_state = home / ".local/state/workstation-manager-v1"
    config = home / ".config/workstation-manager"
    browser = home / ".config/BraveSoftware/Brave-Browser"
    files = {
        system / "system.json": json.dumps(
            {"baseline": {"manual_apt_packages": ["baseline-apt"], "flatpak_packages": ["baseline.App"]}}
        ),
        system / "personal-system-note": "keep system data",
        user_state / "state.json": "{}",
        user_state / "personal-user-note": "keep user data",
        config / "mise.sh": "# managed runtime",
        config / "personal-config": "keep config data",
        browser / "Profile 9999/Preferences": "{}",
        browser / "component-cache/personal-data": "keep browser cache",
    }
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return [
        "extra-apt",
        "extra.App",
        str(system / "personal-system-note"),
        str(user_state / "personal-user-note"),
        str(config / "personal-config"),
        str(browser / "Profile 9999"),
    ]


def snapshot_files(*roots):
    """Compare the entire managed fixture to catch new reports and unintended writes."""
    return {str(path): path.read_bytes() for root in roots for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("with_baseline", [False, True])
def test_cleanup_prints_results_without_writing_files(tmp_path, with_baseline):
    """Apply and preview display drift while preserving data and absent state directories."""
    command, environment = cleanup_context(tmp_path)
    home, system = tmp_path / "home", tmp_path / "system"
    expected = seed_baseline_and_drift(home, system) if with_baseline else ["Cleanup baseline is unavailable"]
    original = snapshot_files(home, system)
    for arguments in (["--check"], []):
        result = run_playbook([*command, *arguments], environment)
        assert result.returncode == 0, result.stdout + result.stderr
        for value in [*expected, "Inst pending-update", "Reboot required:"]:
            assert value in result.stdout
        assert "component-cache" not in result.stdout
        assert snapshot_files(home, system) == original
        assert (home / ".local/state/workstation-manager-v1").exists() == with_baseline
