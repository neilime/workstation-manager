"""Build local role-test playbooks without repeating the Ansible connection schema."""

from __future__ import annotations

import json
import os
import pwd
import subprocess
import sys
from pathlib import Path
from typing import Any

SETUP_ROLES = Path(__file__).parents[2] / "ansible/collections/ansible_collections/neilime/workstation_setup/roles"


def managed_user(home: Path, **fields: str) -> dict[str, str]:
    """Resolve the fixture's unprivileged account without assuming its username."""
    return {"name": pwd.getpwuid(os.getuid()).pw_name, "home": str(home), **fields}


def run_playbook(
    command: list[str], environment: dict[str, str], *, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Capture a bounded Ansible run, leaving expected failure assertions to callers."""
    return subprocess.run(command, env=environment, cwd=cwd, capture_output=True, text=True, check=False, timeout=60)


def write_local_playbook(
    path: Path, tasks: list[dict[str, Any]], variables: dict[str, Any], **play_options: Any
) -> Path:
    """Write a local playbook using the interpreter that runs the test suite."""
    play = {
        "hosts": "localhost",
        "connection": "local",
        "gather_facts": False,
        "vars": {"ansible_python_interpreter": sys.executable, **variables},
        "tasks": tasks,
        **play_options,
    }
    path.write_text(json.dumps([play]))
    return path


def ansible_environment(root: Path, **overrides: str) -> dict[str, str]:
    """Isolate controller state while retaining installed collection dependencies."""
    configuration = root / "ansible.cfg"
    if not configuration.exists():
        configuration.write_text("[defaults]\n")
    collections = Path(__file__).parents[2] / "ansible/collections"
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(root),
        "LC_ALL": "C.UTF-8",
        "ANSIBLE_CONFIG": str(configuration),
        "ANSIBLE_HOME": str(root / ".ansible"),
        "ANSIBLE_COLLECTIONS_PATH": f"{collections}:"
        + os.environ.get("ANSIBLE_COLLECTIONS_PATH", "/opt/ansible/collections"),
        **overrides,
    }


def desktop_variables(home: Path, **settings: Any) -> dict[str, Any]:
    """Run desktop roles as the fixture user without privilege escalation."""
    return {
        "workstation_manager_use_become": False,
        "workstation_manager_gnome_use_become_user": False,
        "workstation_manager_resolved": {"user": managed_user(home), **settings},
    }


def write_stateful_module(path: Path, operations: str) -> None:
    """Wrap simulated operations with shared JSON state and check-mode handling."""
    path.write_text(
        r"""
import json
from pathlib import Path
from ansible.module_utils.basic import AnsibleModule

module = AnsibleModule(argument_spec={
    "operation": {"type": "str", "required": True},
    "arguments": {"type": "dict", "required": True},
    "state_file": {"type": "path", "required": True},
}, supports_check_mode=True)
path = Path(module.params["state_file"])
state = json.loads(path.read_text())
before = json.dumps(state, sort_keys=True)
operation, args = module.params["operation"], module.params["arguments"]
result = {}
"""
        + operations.strip()
        + r"""
else:
    module.fail_json(msg="Unexpected operation: " + operation)
changed = before != json.dumps(state, sort_keys=True)
if not module.check_mode:
    path.write_text(json.dumps(state))
module.exit_json(changed=changed, **result)
"""
    )
