"""Recover the managed user's live desktop environment without exposing credentials."""

import json
import os
import pwd
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    desktop_session,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desktop_session import (
    DesktopSession,
)


@pytest.fixture(name="manager")
def session_manager(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Model an SSH session with a running user manager but no inherited display."""
    monkeypatch.setattr(
        os,
        "environ",
        {
            "BW_SESSION": "private-vault-session",
            "BWS_ACCESS_TOKEN": "private-vault-token",
            "DISPLAY": "",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/other/bus",
            "XDG_RUNTIME_DIR": "/run/user/other",
        },
    )
    bus = f"/run/user/{os.geteuid()}/bus"
    monkeypatch.setattr(Path, "is_socket", lambda path: str(path) == bus)
    command = Mock(return_value=subprocess.CompletedProcess([], 0, "{}", ""))
    monkeypatch.setattr(desktop_session.subprocess, "run", command)
    return command


def test_browser_recovers_live_wayland_session_from_ssh(manager: Mock) -> None:
    """GNOME publishes displays after starting; its initial process environment lacks them."""
    desktop = {
        "DISPLAY": ":7",
        "WAYLAND_DISPLAY": "wayland-fixture",
        "XAUTHORITY": "/run/user/fixture/auth with 'quotes' and $text",
        "XDG_RUNTIME_DIR": f"/run/user/{os.geteuid()}",
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{os.geteuid()}/bus",
    }
    manager.return_value.stdout = json.dumps({**desktop, "BW_SESSION": "private-session", "HOME": "/other-user"})

    environment = DesktopSession.environment()

    assert {key: environment[key] for key in desktop} == desktop
    assert environment["HOME"] == pwd.getpwuid(os.geteuid()).pw_dir
    assert "private-" not in json.dumps(environment)
    probe = manager.call_args
    assert probe.args[0] == [
        "/usr/bin/systemctl",
        "--user",
        "show-environment",
        "--output=json",
    ]
    assert probe.kwargs["env"]["DBUS_SESSION_BUS_ADDRESS"] == desktop["DBUS_SESSION_BUS_ADDRESS"]
    assert "private-" not in json.dumps(probe.kwargs["env"])
    assert 0 < probe.kwargs["timeout"] <= 5


def test_caller_display_remains_usable_without_a_user_manager(manager: Mock, monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicitly supplied desktop remains usable; profile-only work needs no display."""
    monkeypatch.setattr(Path, "is_socket", lambda _path: False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-explicit")
    environment = DesktopSession.environment()
    assert environment["WAYLAND_DISPLAY"] == "wayland-explicit"
    assert "DISPLAY" not in environment
    assert "BW_SESSION" not in environment
    manager.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    ["private-invalid-json", '["private-value"]', '{"DISPLAY": ["private-value"]}'],
)
def test_invalid_session_environment_is_redacted(manager: Mock, payload: str) -> None:
    """Invalid manager output cannot be mistaken for a usable desktop or exposed in an error."""
    manager.return_value.stdout = payload
    with pytest.raises(ValueError, match="desktop session environment") as error:
        DesktopSession.environment()
    assert "private-" not in str(error.value)


@pytest.mark.parametrize("failure", ["unavailable", "timeout", "execution"])
def test_session_query_failures_are_bounded_and_redacted(manager: Mock, failure: str) -> None:
    """A broken live session produces an actionable error without command output."""
    if failure == "unavailable":
        manager.return_value = subprocess.CompletedProcess([], 1, "private-output", "private-error")
    elif failure == "timeout":
        manager.side_effect = subprocess.TimeoutExpired("systemctl", 5, output="private-output")
    else:
        manager.side_effect = OSError("private-error")
    with pytest.raises(ValueError, match="desktop session environment") as error:
        DesktopSession.environment()
    assert "private-" not in str(error.value)
