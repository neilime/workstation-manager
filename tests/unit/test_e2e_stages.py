"""Keep separately invoked AAA stages equivalent to the complete local E2E flow."""

from __future__ import annotations

import json
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
prepare_e2e_task_profiling() { printf 'prepare:%s\n' "$stage" >>"$TEST_TRACE"; }
restore_e2e_task_profiling() {
    printf 'restore:%s\n' "$stage" >>"$TEST_TRACE"
    [[ "$stage" != "$TEST_RESTORE_FAILURE" ]] || return 42
}
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
        --junitxml=*/e2e-setup-repeat.junit.xml) phase=setup-repeat-assert ;;
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
        "TEST_RESTORE_FAILURE": "",
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
    """CI and local execution use identical ordering, fixtures, profiling, and test selection."""
    run, fixture, trace = suite
    result = run()
    assert result.returncode == 0, result.stderr
    complete_trace = trace.read_text().splitlines()
    assert [event for event in complete_trace if event in STAGES] == STAGES
    assert not any("setup-repeat" in event for event in complete_trace)
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
    records = [json.loads(line) for line in (fixture / "reports/e2e/phase-timings.jsonl").read_text().splitlines()]
    assert [record["phase"] for record in records if record["phase"] in STAGES] == STAGES * 2
    assert all(record["exit_status"] == 0 for record in records)


def test_setup_repeat_runs_all_setup_assertions_with_separate_reports(suite):
    """Optional repeat stages preserve setup coverage and keep fresh-run reports available."""
    run, fixture, trace = suite
    assert run("setup-assert").returncode == 0
    original_arguments = (fixture / "arguments/setup-assert").read_text().splitlines()
    trace.write_text("")

    for stage in ("setup-repeat-act", "setup-repeat-assert"):
        result = run(stage)
        assert result.returncode == 0, result.stderr

    assert trace.read_text().splitlines() == [
        "prepare:setup-repeat-act",
        "setup-repeat",
        "screenshot",
        "restore:setup-repeat-act",
        "setup-repeat-assert",
    ]
    repeated_arguments = (fixture / "arguments/setup-repeat-assert").read_text().splitlines()
    assert [argument for argument in repeated_arguments if argument.startswith("e2e-tests/test_")] == [
        argument for argument in original_arguments if argument.startswith("e2e-tests/test_")
    ]
    assert "--junitxml=/workspace/reports/tests/e2e-setup-repeat.junit.xml" in repeated_arguments
    assert (fixture / "arguments/setup-assert").read_text().splitlines() == original_arguments
    assert (fixture / "reports/screenshots/e2e-setup-repeat-desktop.png").read_text() == "image"
    records = [json.loads(line) for line in (fixture / "reports/e2e/phase-timings.jsonl").read_text().splitlines()]
    assert [record["phase"] for record in records if record["phase"].startswith("setup-repeat")] == [
        "setup-repeat-act",
        "setup-repeat-assert",
    ]


def test_setup_repeat_screenshot_failure_does_not_skip_assertions(suite):
    """An unavailable repeat screenshot fails fixture finishing after installed behavior is checked."""
    run, _, trace = suite
    assert run("setup-repeat-act", TEST_SCREENSHOT_STATUS="1").returncode == 0
    assert run("setup-repeat-assert").returncode == 0
    result = run("finish")
    assert result.returncode == 1
    assert "screenshot failed" in result.stderr
    assert "setup-repeat-assert" in trace.read_text().splitlines()


@pytest.mark.parametrize("failed_stage", ["backup-arrange", "setup-act", "setup-assert", "cleanup-act"])
def test_stage_failure_stops_later_work_and_preserves_original_error(suite, failed_stage):
    """Failed arrangements, actions, and assertions stop dependents but still finish fixtures."""
    run, _, trace = suite
    result = run(TEST_FAILURE=failed_stage, TEST_RESTORE_FAILURE=failed_stage)
    assert result.returncode == 31, result.stderr
    events = trace.read_text().splitlines()
    assert [event for event in events if event in STAGES] == STAGES[: STAGES.index(failed_stage) + 1]
    assert events[-1] == "backup-finish"
    if failed_stage == "setup-act":
        assert events.index("screenshot") < events.index("desktop-diagnostics") < events.index("browser-diagnostics")
        assert "restore:setup-act" in events


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


def test_restore_failure_fails_a_successful_stage(suite):
    """Profiling restoration must fail the stage when its action otherwise succeeded."""
    run, _, trace = suite
    result = run(TEST_RESTORE_FAILURE="setup-act")
    assert result.returncode == 42, result.stderr
    assert "cleanup-act" not in trace.read_text().splitlines()


def test_screenshot_write_failure_cannot_mask_setup_failure(suite):
    """Broken report storage still permits diagnostics and retains the failed workstation action."""
    run, fixture, trace = suite
    blocked = fixture / "blocked"
    blocked.touch()
    result = run("setup-act", TEST_FAILURE="setup-act", SCREENSHOTS_DIR=str(blocked))
    assert result.returncode == 31, result.stderr
    events = trace.read_text().splitlines()
    assert events.index("desktop-diagnostics") < events.index("browser-diagnostics")
    assert events[-1] == "restore:setup-act"


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


def test_shared_deadline_interrupts_action_and_restores_profiling(suite):
    """An in-flight action is bounded, and signal handling still restores its temporary profiling."""
    run, _, trace = suite
    result = run(
        "backup-act",
        E2E_SUITE_DEADLINE=str(int(time.time()) + 2),
        TEST_SLOW_STAGE="backup-act",
    )
    assert result.returncode == 124, result.stderr
    assert trace.read_text().splitlines() == ["prepare:backup-act", "backup-act", "restore:backup-act"]
