"""Keep the CI job's package credential separate through the VM setup boundary."""

import os
import subprocess
from pathlib import Path

from ansible.parsing.dataloader import DataLoader

ROOT = Path(__file__).parents[2]


def test_ci_registry_token_has_write_access_and_reaches_vm_setup_privately(tmp_path):
    """The job supplies its package-write token to setup without changing the GitHub user token."""
    workflow = DataLoader().load_from_file(str(ROOT / ".github/workflows/__shared-ci.yml"))
    job = workflow["jobs"]["e2e"]
    step = next(step for step in job["steps"] if "WORKSTATION_MANAGER_GHCR_TOKEN" in step.get("env", {}))
    assert job["permissions"]["packages"] == "write"
    assert step["env"]["WORKSTATION_MANAGER_GHCR_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"
    assert step["env"]["WORKSTATION_MANAGER_GITHUB_TOKEN"] == "${{ secrets.WORKSTATION_MANAGER_GITHUB_TOKEN }}"
    setup = tmp_path / "e2e-setup.sh"
    setup.write_bytes((ROOT / "e2e-tests/e2e-setup.sh").read_bytes())
    (tmp_path / "e2e-common.sh").write_text(
        "resolve_e2e_workstation_context() { :; }\n"
        "require_e2e_env_vars() { :; }\n"
        "resolve_e2e_target_user_home() { printf '/fixture/home'; }\n"
        "run_e2e_vm_shell() { case $1 in *archives=*) printf '/fixture/archive.tar.gz';; esac; }\n"
        "run_e2e_lima_shell() { :; }\n"
        'run_e2e_workstation_action() { printf \'%s\\0\' "$@" >"$TEST_ARGUMENTS"; }\n'
    )
    token = "synthetic-job-registry-token"
    arguments = tmp_path / "arguments"
    result = subprocess.run(
        ["bash", str(setup)],
        env={
            "PATH": os.environ["PATH"],
            "BITWARDEN_CLIENT_ID": "fixture",
            "BITWARDEN_CLIENT_SECRET": "fixture",
            "BITWARDEN_PASSWORD": "fixture",
            "WORKSTATION_MANAGER_GHCR_TOKEN": token,
            "TEST_ARGUMENTS": str(arguments),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    invocation = arguments.read_text().split("\0")[:-1]
    assert invocation[0] == "setup"
    assert f"WORKSTATION_MANAGER_GHCR_TOKEN={token}" in invocation
    assert token not in result.stdout + result.stderr
