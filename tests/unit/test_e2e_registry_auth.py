"""Keep the CI job's package credential separate through the VM setup boundary."""

import os
import shlex
import subprocess
from pathlib import Path

from ansible.parsing.dataloader import DataLoader

ROOT = Path(__file__).parents[2]


def test_ci_stages_limit_credentials_to_actions_that_need_external_authentication():
    """Assertions and local fixture work must not inherit action credentials from the job."""
    workflow = DataLoader().load_from_file(str(ROOT / ".github/workflows/__shared-ci.yml"))
    job = workflow["jobs"]["e2e"]
    assert not any(marker in str(value) for value in job["env"].values() for marker in ("secrets.", "github.token"))
    assert job["env"]["E2E_REPOSITORY_URL"]
    assert job["env"]["REPORTS_DIR"] == ".reports"
    assert str(job["env"]["E2E_PROFILE_TASKS"]) == "1"
    authenticated = {"backup-arrange", "backup-act", "setup-act", "cleanup-act"}
    vault_credentials = {
        "BITWARDEN_CLIENT_ID": "${{ secrets.BITWARDEN_CLIENT_ID }}",
        "BITWARDEN_CLIENT_SECRET": "${{ secrets.BITWARDEN_CLIENT_SECRET }}",
        "BITWARDEN_PASSWORD": "${{ secrets.BITWARDEN_PASSWORD }}",
        "WORKSTATION_MANAGER_GITHUB_TOKEN": "${{ secrets.WORKSTATION_MANAGER_GITHUB_TOKEN }}",
    }
    observed = set()
    for step in job["steps"]:
        arguments = shlex.split(step.get("run", ""))
        if arguments[:2] != ["make", "e2e-stage"]:
            continue
        stage = next(argument.removeprefix("STAGE=") for argument in arguments if argument.startswith("STAGE="))
        expected = vault_credentials if stage in authenticated else {}
        if stage == "setup-act":
            expected = {**expected, "WORKSTATION_MANAGER_GHCR_TOKEN": "${{ secrets.GITHUB_TOKEN }}"}
        environment = {**job["env"], **step.get("env", {})}
        credentials = {
            key: value
            for key, value in environment.items()
            if key in {*vault_credentials, "WORKSTATION_MANAGER_GHCR_TOKEN"}
            or any(marker in str(value) for marker in ("secrets.", "github.token"))
        }
        assert credentials == expected, stage
        observed.add(stage)
    assert authenticated.issubset(observed)
    assert {"backup-assert", "setup-assert", "cleanup-assert", "finish"}.issubset(observed)


def test_ci_finishes_fixtures_before_reports_and_always_stops_the_vm():
    """Stage failures still finish backup fixtures before report collection and VM teardown."""
    workflow = DataLoader().load_from_file(str(ROOT / ".github/workflows/__shared-ci.yml"))
    steps = workflow["jobs"]["e2e"]["steps"]
    finish = next(step for step in steps if shlex.split(step.get("run", "")) == ["make", "e2e-stage", "STAGE=finish"])
    teardown = next(step for step in steps if shlex.split(step.get("run", "")) == ["make", "e2e-down"])
    reports = next(step for step in steps if "e2e-*.junit.xml" in step.get("with", {}).get("report-paths", ""))
    assert steps.index(finish) < steps.index(reports) < steps.index(teardown)
    for step in (finish, reports, teardown):
        assert step["if"] in ("always()", "${{ always() }}")
        assert not step.get("continue-on-error", False)


def test_ci_registry_token_has_write_access_and_reaches_vm_setup_privately(tmp_path):
    """The job supplies its package-write token to setup without changing the GitHub user token."""
    workflow = DataLoader().load_from_file(str(ROOT / ".github/workflows/__shared-ci.yml"))
    job = workflow["jobs"]["e2e"]
    step = next(step for step in job["steps"] if "WORKSTATION_MANAGER_GHCR_TOKEN" in step.get("env", {}))
    assert shlex.split(step["run"]) == ["make", "e2e-stage", "STAGE=setup-act"]
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
        check=True,
        timeout=10,
    )
    invocation = arguments.read_text().split("\0")[:-1]
    assert invocation[0] == "setup"
    assert f"WORKSTATION_MANAGER_GHCR_TOKEN={token}" in invocation
    assert token not in result.stdout + result.stderr
