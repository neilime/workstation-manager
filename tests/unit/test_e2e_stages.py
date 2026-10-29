"""Keep separately invoked AAA stages equivalent to the complete local E2E flow."""

from __future__ import annotations

import pathlib
import subprocess
import time

import pytest

E2E_PATH = pathlib.Path(__file__).parents[2] / "e2e-tests"
STAGES = [f"{phase}-{stage}" for phase in ("backup", "setup", "cleanup") for stage in ("arrange", "act", "assert")]


@pytest.fixture(name="suite")
def suite_fixture(tmp_path: pathlib.Path):
    """Replace VM and Docker boundaries while running the real stage orchestration."""
    scripts = tmp_path / "e2e-tests"
    scripts.mkdir()
    (scripts / "e2e-test.sh").write_bytes((E2E_PATH / "e2e-test.sh").read_bytes())
    for name in ("backup", "cleanup", "desktop", "new_feature"):
        (scripts / f"test_{name}.py").touch()
    (scripts / "e2e-common.sh").write_text(
        (E2E_PATH / "e2e-common.sh").read_text()
        + r"""
restart_e2e_desktop_session() { :; }
wait_for_e2e_clipboard_extension() { :; }
print_e2e_desktop_diagnostics() { printf 'desktop-diagnostics\n' >>"$TEST_TRACE"; return 43; }
run_e2e_lima_shell() { printf 'browser-diagnostics\n' >>"$TEST_TRACE"; return 44; }
capture_e2e_vm_desktop() {
    printf 'screenshot\n' >>"$TEST_TRACE"
    printf image >"$2/$1.png"
    return "$TEST_SCREENSHOT_STATUS"
}
"""
    )
    for phase in ("backup", "setup", "cleanup"):
        (scripts / f"e2e-{phase}.sh").write_text(
            f'phase="{phase}-$2"\n'
            + r"""
printf '%s\n' "$phase" >>"$TEST_TRACE"
[[ "$phase" != "$TEST_FAILURE" ]] || exit 31
if [[ "$phase" == "$TEST_SLOW_STAGE" ]]; then sleep 30; fi
"""
        )
    docker = tmp_path / "docker"
    docker.write_text(
        r"""#!/bin/bash
set -euo pipefail
phase=setup-assert
for argument in "$@"; do
    case "$argument" in
        e2e-tests/test_backup.py) phase=backup-assert ;;
        e2e-tests/test_cleanup.py) phase=cleanup-assert ;;
    esac
done
printf '%s\n' "$phase" >>"$TEST_TRACE"
printf '%s\n' "$@" >"$TEST_ARGUMENTS/$phase"
[[ "$phase" != "$TEST_FAILURE" ]] || exit 31
"""
    )
    docker.chmod(0o700)
    arguments = tmp_path / "arguments"
    arguments.mkdir()
    trace = tmp_path / "trace"
    trace.touch()
    environment = {
        "PATH": f"{tmp_path}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "REPORTS_DIR": "reports",
        "TEST_TRACE": str(trace),
        "TEST_ARGUMENTS": str(arguments),
        "TEST_FAILURE": "",
        "TEST_SLOW_STAGE": "",
        "TEST_SCREENSHOT_STATUS": "0",
    }

    def run(stage="all", **overrides):
        return subprocess.run(
            ["bash", str(scripts / "e2e-test.sh"), "fixture", stage],
            cwd=tmp_path,
            env={**environment, **overrides},
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    return run, tmp_path, trace


def test_separate_stages_match_full_flow_and_select_all_assertions(suite):
    """CI and local execution use identical ordering, fixtures, and test selection."""
    run, fixture, trace = suite
    result = run()
    assert result.returncode == 0, result.stderr
    complete_trace = trace.read_text().splitlines()
    assert [event for event in complete_trace if event in STAGES] == STAGES
    assert complete_trace[-1] == "backup-finish"
    trace.write_text("")
    for stage in [*STAGES, "finish"]:
        result = run(stage)
        assert result.returncode == 0, result.stderr
    assert trace.read_text().splitlines() == complete_trace
    for phase, expected in (
        ("backup", ["e2e-tests/test_backup.py"]),
        ("setup", ["e2e-tests/test_desktop.py", "e2e-tests/test_new_feature.py"]),
        ("cleanup", ["e2e-tests/test_cleanup.py"]),
    ):
        arguments = (fixture / "arguments" / f"{phase}-assert").read_text().splitlines()
        assert [argument for argument in arguments if argument.startswith("e2e-tests/test_")] == expected
        assert f"--junitxml=/workspace/reports/tests/e2e-{phase}.junit.xml" in arguments


def test_assertions_use_the_selected_vm_runtime_for_ssh(suite):
    """Host assertions can reach a VM created outside the default Lima home."""
    run, fixture, _ = suite
    runtime = str(fixture / "isolated runtime")
    result = run("backup-assert", LIMA_HOME=runtime)
    assert result.returncode == 0, result.stderr
    arguments = (fixture / "arguments/backup-assert").read_text().splitlines()
    assert f"{runtime}:{runtime}:ro" in arguments
    assert f"{runtime}/fixture/ssh.config" in arguments
    assert "--hosts=ssh://lima-fixture" in arguments


@pytest.mark.parametrize("failed_stage", ["backup-arrange", "setup-act", "setup-assert", "cleanup-act"])
def test_stage_failure_stops_later_work_and_preserves_original_error(suite, failed_stage):
    """Failed arrangements, actions, and assertions stop dependents but still finish fixtures."""
    run, _, trace = suite
    result = run(TEST_FAILURE=failed_stage)
    assert result.returncode == 31, result.stderr
    events = trace.read_text().splitlines()
    assert [event for event in events if event in STAGES] == STAGES[: STAGES.index(failed_stage) + 1]
    assert events[-1] == "backup-finish"
    if failed_stage == "setup-act":
        assert events.index("screenshot") < events.index("desktop-diagnostics") < events.index("browser-diagnostics")


def test_screenshot_failure_is_deferred_until_after_all_assertions(suite):
    """A missing screenshot fails finishing without skipping installed or preservation checks."""
    run, _, trace = suite
    for stage in STAGES:
        result = run(stage, TEST_SCREENSHOT_STATUS="1")
        assert result.returncode == 0, result.stderr
    result = run("finish")
    assert result.returncode == 1
    assert "screenshot failed" in result.stderr
    assert [event for event in trace.read_text().splitlines() if event in STAGES] == STAGES
    # A new run cannot inherit a prior screenshot failure.
    result = run()
    assert result.returncode == 0, result.stderr


def test_screenshot_write_failure_cannot_mask_setup_failure(suite):
    """Broken report storage still permits diagnostics and retains the failed workstation action."""
    run, fixture, trace = suite
    blocked = fixture / "blocked"
    blocked.touch()
    result = run("setup-act", TEST_FAILURE="setup-act", SCREENSHOTS_DIR=str(blocked))
    assert result.returncode == 31, result.stderr
    events = trace.read_text().splitlines()
    assert events.index("desktop-diagnostics") < events.index("browser-diagnostics")
    assert events[-1] == "browser-diagnostics"


@pytest.mark.parametrize("deadline,status", [("1", 124), ("not-an-epoch", 2)])
def test_deadline_prevents_work_but_does_not_block_finishing(suite, deadline, status):
    """Expired or invalid shared deadlines stop stage work while fixture finishing remains available."""
    run, _, trace = suite
    result = run("backup-arrange", E2E_SUITE_DEADLINE=deadline)
    assert result.returncode == status, result.stderr
    assert trace.read_text() == ""
    result = run("finish", E2E_SUITE_DEADLINE=deadline)
    assert result.returncode == 0, result.stderr
    assert trace.read_text().splitlines() == ["backup-finish"]
    trace.write_text("")
    result = run(E2E_SUITE_DEADLINE=deadline)
    assert result.returncode == status, result.stderr
    assert trace.read_text().splitlines() == ["backup-finish"]


def test_shared_deadline_interrupts_an_in_flight_action(suite):
    """The shared suite deadline bounds an in-flight action."""
    run, _, trace = suite
    result = run(
        "backup-act",
        E2E_SUITE_DEADLINE=str(int(time.time()) + 2),
        TEST_SLOW_STAGE="backup-act",
    )
    assert result.returncode == 124, result.stderr
    assert trace.read_text().splitlines() == ["backup-act"]
