"""Exercise the VM teardown lifecycle without a real VM or remote browser devices."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

E2E_PATH = Path(__file__).parents[2] / "e2e-tests"


@pytest.mark.parametrize("cleanup_status,repeat_pending", [(0, False), (17, False), (0, True)])
def test_e2e_teardown_waits_for_guest_completion_before_vm_deletion(
    tmp_path: Path, cleanup_status: int, repeat_pending: bool
) -> None:
    """Unverified repeat identities or failed device teardown must retain the VM for diagnosis."""

    commands = tmp_path / "bin"
    commands.mkdir()
    log = tmp_path / "commands"
    limactl = commands / "limactl"
    limactl.write_text(
        "#!/bin/bash\n"
        'printf "%s\\n" "$1" >>"$TEST_COMMAND_LOG"\n'
        'case "$1" in\n'
        '  list) if [[ "$2" == --format ]]; then echo fixture; else echo Running; fi ;;\n'
        "  shell)\n"
        "    for device in 1 2 3 4; do\n"
        "      sleep 0.15\n"
        '      printf "device-complete\\n" >>"$TEST_COMMAND_LOG"\n'
        "    done\n"
        '    exit "$TEST_CLEANUP_STATUS" ;;\n'
        "esac\n"
    )
    limactl.chmod(0o700)
    # Accelerate any aggregate host deadline while each simulated device remains
    # faster than that deadline. Native per-device limits belong to the guest.
    timeout_command = commands / "timeout"
    timeout_command.write_text(
        '#!/bin/bash\nwhile [[ "$1" == -* ]]; do shift; done\nshift\nexec /usr/bin/timeout --kill-after=1s 0.2s "$@"\n'
    )
    timeout_command.chmod(0o700)
    repeat_marker = tmp_path / ".lima/fixture/setup-repeat.pending"
    if repeat_pending:
        repeat_marker.parent.mkdir(parents=True)
        repeat_marker.touch()

    result = subprocess.run(
        ["bash", str(E2E_PATH / "e2e-down.sh"), "fixture"],
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "PATH": f"{commands}:/usr/bin:/bin",
            "TEST_COMMAND_LOG": str(log),
            "TEST_CLEANUP_STATUS": str(cleanup_status),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == (1 if cleanup_status or repeat_pending else 0), result.stderr
    if repeat_pending:
        assert log.read_text().splitlines() == ["list"]
        assert "VM was retained for diagnosis" in result.stderr
        assert repeat_marker.exists()
        return
    assert log.read_text().splitlines() == ["list", "list", "shell", *(["device-complete"] * 4)] + (
        [] if cleanup_status else ["stop", "delete"]
    )
    assert ("VM and recorded device identities were retained" in result.stderr) == bool(cleanup_status)
