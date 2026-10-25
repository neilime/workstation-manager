"""Exercise independent E2E arrangement and action stages without touching a workstation."""

from __future__ import annotations

import os
import pathlib
import subprocess

import pytest

WORKSPACE = pathlib.Path(__file__).parents[2]


@pytest.fixture(name="stage_environment")
def stage_environment_fixture(tmp_path: pathlib.Path) -> dict[str, str]:
    """Run fixture filesystem operations locally, replacing only VM and action boundaries."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for phase in ("backup", "setup", "cleanup"):
        (scripts / f"e2e-{phase}.sh").write_bytes((WORKSPACE / f"e2e-tests/e2e-{phase}.sh").read_bytes())
    (scripts / "e2e-common.sh").write_text(
        (WORKSPACE / "e2e-tests/e2e-common.sh").read_text()
        + r"""
resolve_e2e_workstation_context() { touch "$TEST_FIXTURE/context"; }
resolve_e2e_target_user_home() { printf '%s\n' "$HOME"; }
run_e2e_vm_shell() {
    bash -c "${1//\/tmp\/workstation-manager-e2e-backup/$TEST_FIXTURE/backup}"
}
run_e2e_lima_shell() {
    case "${@: -1}" in
        prepare) printf 'prepare\n' >>"$TEST_FIXTURE/trace" ;;
        capture|--require-initialized)
            printf '%s\n' "${@: -1}" >>"$TEST_FIXTURE/trace"
            return "$TEST_CAPTURE_STATUS"
            ;;
        *) return 99 ;;
    esac
}
run_e2e_workstation_action() {
    printf '%s\n' "$1" >>"$TEST_FIXTURE/trace"
    if [[ -n "${TEST_ACTION_SIGNAL:-}" ]]; then kill -"$TEST_ACTION_SIGNAL" "$$"; fi
    return "$TEST_ACTION_STATUS"
}
run_e2e_detached_workstation_action() { run_e2e_workstation_action "$@"; }
"""
    )
    user_home = tmp_path / "home"
    user_home.mkdir()
    archives = tmp_path / "backup"
    archives.mkdir()
    (archives / "workstation-manager-backup-fixture.tar.gz").touch()
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(user_home),
        "TEST_FIXTURE": str(tmp_path),
        "TEST_ACTION_STATUS": "0",
        "TEST_CAPTURE_STATUS": "0",
    }


def run_stage(
    tmp_path: pathlib.Path, environment: dict[str, str], phase: str, stage: str
) -> subprocess.CompletedProcess[str]:
    """Run one production script, preserving its real stage parsing and exit traps."""
    return subprocess.run(
        ["bash", str(tmp_path / f"scripts/e2e-{phase}.sh"), "fixture-vm", stage],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def credentials(environment: dict[str, str]) -> dict[str, str]:
    """Supply synthetic credentials only for action stages."""
    return {
        **environment,
        "BITWARDEN_CLIENT_ID": "fixture-client",
        "BITWARDEN_CLIENT_SECRET": "fixture-secret",
        "BITWARDEN_PASSWORD": "fixture-password",
    }


@pytest.mark.parametrize("phase", ["backup", "setup", "cleanup"])
def test_invalid_stage_stops_before_context_or_guest_access(
    tmp_path: pathlib.Path, stage_environment: dict[str, str], phase: str
) -> None:
    """Unsupported stage names must fail before any fixture or workstation operation."""
    result = run_stage(tmp_path, stage_environment, phase, "unknown")
    assert result.returncode == 2
    assert not (tmp_path / "context").exists()


def test_setup_arranges_without_credentials_and_captures_only_during_act(
    tmp_path: pathlib.Path, stage_environment: dict[str, str]
) -> None:
    """Arrangement removes restore targets; browser identity ownership spans only the actual setup."""
    user_home = pathlib.Path(stage_environment["HOME"])
    targets = [user_home / "Documents/dev-projects", user_home / ".config/workstation-manager"]
    for target in targets:
        target.mkdir(parents=True)
    arranged = run_stage(tmp_path, stage_environment, "setup", "arrange")
    assert arranged.returncode == 0, arranged.stdout + arranged.stderr
    assert not any(target.exists() for target in targets)
    assert not (tmp_path / "trace").exists()
    acted = run_stage(tmp_path, credentials(stage_environment), "setup", "act")
    assert acted.returncode == 0, acted.stdout + acted.stderr
    assert (tmp_path / "trace").read_text().splitlines() == ["prepare", "setup", "--require-initialized"]


@pytest.mark.parametrize(
    "action_status,capture_status,signal,expected",
    [(37, 42, "", 37), (0, 42, "", 42), (0, 0, "TERM", 143)],
)
def test_setup_act_always_captures_devices_and_preserves_primary_failure(
    stage_environment: dict[str, str],
    action_status: int,
    capture_status: int,
    signal: str,
    expected: int,
) -> None:
    """Failed or interrupted setup captures partial identities, while successful setup requires initialization."""
    tmp_path = pathlib.Path(stage_environment["TEST_FIXTURE"])
    environment = {
        **credentials(stage_environment),
        "TEST_ACTION_STATUS": str(action_status),
        "TEST_CAPTURE_STATUS": str(capture_status),
        "TEST_ACTION_SIGNAL": signal,
    }
    result = run_stage(tmp_path, environment, "setup", "act")
    assert result.returncode == expected, result.stdout + result.stderr
    assert (tmp_path / "trace").read_text().splitlines() == [
        "prepare",
        "setup",
        "capture" if action_status or signal else "--require-initialized",
    ]


@pytest.mark.parametrize("invalid_state", ["multiple-archives", "existing-restore-target"])
def test_setup_act_revalidates_its_restore_preconditions(
    tmp_path: pathlib.Path, stage_environment: dict[str, str], invalid_state: str
) -> None:
    """A separate action cannot continue after archive selection or removed fixture paths change."""
    assert run_stage(tmp_path, stage_environment, "setup", "arrange").returncode == 0
    if invalid_state == "multiple-archives":
        (tmp_path / "backup/workstation-manager-backup-another.tar.gz").touch()
    else:
        (pathlib.Path(stage_environment["HOME"]) / "Documents/dev-projects").mkdir(parents=True)
    result = run_stage(tmp_path, credentials(stage_environment), "setup", "act")
    assert result.returncode != 0
    assert not (tmp_path / "trace").exists()


def test_cleanup_arranges_preservation_markers_without_credentials(
    tmp_path: pathlib.Path, stage_environment: dict[str, str]
) -> None:
    """Marker setup and destructive cleanup are separate stages with the same preservation fixture."""
    arranged = run_stage(tmp_path, stage_environment, "cleanup", "arrange")
    assert arranged.returncode == 0, arranged.stdout + arranged.stderr
    assert not (tmp_path / "trace").exists()
    browser = pathlib.Path(stage_environment["HOME"]) / ".config/BraveSoftware/Brave-Browser"
    for directory in ("managed-e2e-stale", "Profile 9999", "e2e-component-cache"):
        assert (browser / directory / "e2e-preserve-marker").read_text() == "preserve\n"
    acted = run_stage(tmp_path, credentials(stage_environment), "cleanup", "act")
    assert acted.returncode == 0, acted.stdout + acted.stderr
    assert (tmp_path / "trace").read_text().splitlines() == ["cleanup"]


def test_cleanup_act_requires_its_preservation_markers(
    tmp_path: pathlib.Path, stage_environment: dict[str, str]
) -> None:
    """A missing arrangement prevents running cleanup without preservation coverage."""
    result = run_stage(tmp_path, credentials(stage_environment), "cleanup", "act")
    assert result.returncode != 0
    assert not (tmp_path / "trace").exists()
