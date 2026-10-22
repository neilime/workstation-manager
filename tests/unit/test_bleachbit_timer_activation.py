"""Verify login activation starts the timer and surfaces systemd failures."""

import os
import subprocess

import pytest
from ansible_test_helpers import SETUP_ROLES


@pytest.mark.parametrize("failed_step", ["", "daemon-reload", "start"])
def test_login_activation_reports_systemd_failures(tmp_path, failed_step):
    """A failed reload prevents startup and either systemd failure reaches the caller."""
    systemctl = tmp_path / "systemctl"
    systemctl.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$TIMER_TEST_LOG"\nif [ "$2" = "$TIMER_FAIL_STEP" ]; then exit 42; fi\n'
    )
    systemctl.chmod(0o755)
    log = tmp_path / "calls.log"
    result = subprocess.run(
        ["sh", str(SETUP_ROLES / "bleachbit/files/schedule/bleachbit-clean-activate-timer.sh")],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "TIMER_TEST_LOG": str(log),
            "TIMER_FAIL_STEP": failed_step,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == (42 if failed_step else 0), result.stderr
    commands = log.read_text().splitlines()
    assert commands[0] == "--user daemon-reload"
    if failed_step == "daemon-reload":
        assert len(commands) == 1
    else:
        assert commands[1:] == ["--user start workstation-manager-bleachbit-clean.timer"]
