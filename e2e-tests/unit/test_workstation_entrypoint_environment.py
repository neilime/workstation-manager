"""Keep optional session variables valid across the bootstrap's sudo boundary."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest
from entrypoint_test_helpers import sudo_passthrough_script

ENTRYPOINT = pathlib.Path(__file__).parents[2] / "workstation.sh"
SESSION_VARIABLES = (
    "DBUS_SESSION_BUS_ADDRESS",
    "XDG_RUNTIME_DIR",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "GPG_TTY",
    "SSH_AUTH_SOCK",
)


@pytest.mark.parametrize(
    "session,skip_sudo,command_status",
    [
        pytest.param({}, False, 0, id="headless"),
        pytest.param(dict.fromkeys(SESSION_VARIABLES, ""), False, 0, id="empty"),
        pytest.param(
            {name: f"{name}=literal spaces ' $HOME $(false)" for name in SESSION_VARIABLES},
            False,
            23,
            id="desktop-and-failed-command",
        ),
        pytest.param({"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": "", "GPG_TTY": ""}, True, 0, id="wayland-direct"),
    ],
)
def test_session_environment_forwards_only_nonempty_values(tmp_path, session, skip_sudo, command_status) -> None:
    """Absent session endpoints stay absent; real values survive sudo without shell evaluation."""
    sudo = tmp_path / "sudo"
    sudo.write_text(
        sudo_passthrough_script(
            "unset " + " ".join(SESSION_VARIABLES) + "\nexport TEST_SUDO=1\n",
        )
    )
    sudo.chmod(0o700)
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import json, os, sys\n"
        f"session = {{name: os.environ[name] for name in {SESSION_VARIABLES!r} if name in os.environ}}\n"
        'print(json.dumps({"session": session, "sudo": os.environ.get("TEST_SUDO"), "args": sys.argv[1:]}))\n'
        'sys.exit(0 if sys.argv[1] == "caller" else int(os.environ["TEST_COMMAND_STATUS"]))\n'
    )
    result = subprocess.run(
        ["sh", "-s"],
        input=ENTRYPOINT.read_text().rsplit('main "$@"', 1)[0]
        + '\nstatus=0\nrun_with_session_environment "$TEST_PYTHON" "$TEST_PROBE" "argument with spaces" '
        + '|| status=$?\n"$TEST_PYTHON" "$TEST_PROBE" caller\nexit "$status"\n',
        env={
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(tmp_path),
            "WORKSTATION_MANAGER_SKIP_SUDO": "1" if skip_sudo else "0",
            "TEST_PYTHON": sys.executable,
            "TEST_PROBE": str(probe),
            "TEST_COMMAND_STATUS": str(command_status),
            **session,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == command_status, result.stdout + result.stderr
    command, caller = map(json.loads, result.stdout.splitlines())
    assert command == {
        "session": {name: value for name, value in session.items() if value},
        "sudo": None if skip_sudo else "1",
        "args": ["argument with spaces"],
    }
    assert caller == {"session": session, "sudo": None, "args": ["caller"]}
