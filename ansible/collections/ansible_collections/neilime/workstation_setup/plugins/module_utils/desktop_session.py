"""Discover the managed user's desktop and connect native commands to their terminal."""

from __future__ import annotations

import json
import os
import pwd
import subprocess
from pathlib import Path

_DESKTOP_VARIABLES = frozenset(
    (
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "XAUTHORITY",
        "DBUS_SESSION_BUS_ADDRESS",
        "XDG_RUNTIME_DIR",
        "XDG_CURRENT_DESKTOP",
        "XDG_SESSION_TYPE",
    )
)


class DesktopSession:
    """Use the effective user's live desktop and terminal without capturing sign-in codes."""

    @staticmethod
    def environment() -> dict[str, str]:
        """Use the managed user's session and keyring, without passing vault credentials."""

        account = pwd.getpwuid(os.geteuid())
        environment = {
            "HOME": account.pw_dir,
            "USER": account.pw_name,
            "LOGNAME": account.pw_name,
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "LANG": "C.UTF-8",
        }
        environment.update({key: value for key, value in os.environ.items() if key in _DESKTOP_VARIABLES and value})
        runtime = Path(f"/run/user/{os.geteuid()}")
        if not (runtime / "bus").is_socket():
            return environment

        # Wayland displays are published after gnome-shell starts, so /proc's
        # initial environment cannot supply them. Query the managed user's live bus.
        environment.update(
            XDG_RUNTIME_DIR=str(runtime),
            DBUS_SESSION_BUS_ADDRESS=f"unix:path={runtime}/bus",
        )
        message = "Cannot read the managed user's desktop session environment; log in to GNOME and retry"
        try:
            # run_command would merge vault credentials into this sanitized environment.
            # The Ansible-only checker is absent from standalone Pylint.
            # pylint: disable-next=unknown-option-value
            # pylint: disable-next=ansible-bad-function
            result = subprocess.run(
                ["/usr/bin/systemctl", "--user", "show-environment", "--output=json"],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError(message) from error
        if result.returncode:
            raise ValueError(message)
        try:
            session = json.loads(result.stdout)
        except ValueError as error:
            raise ValueError(message) from error
        if not isinstance(session, dict) or any(
            not isinstance(session[key], str) for key in session.keys() & _DESKTOP_VARIABLES
        ):
            raise ValueError(message)
        environment.update({key: value for key, value in session.items() if key in _DESKTOP_VARIABLES and value})
        return environment

    @staticmethod
    def run_in_terminal(
        command: list[str], *, terminal: str, home: Path, environment: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        """Run native sign-in with a live display when available and output confined to a real terminal."""
        environment = dict(environment)
        try:
            session = DesktopSession.environment()
        except (OSError, ValueError):
            # Native clients can still display a URL for manual opening without a live desktop.
            session = {}
        for name in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE"):
            if session.get(name):
                environment[name] = session[name]
        with open(terminal, "r+b", buffering=0) as tty:
            if not tty.isatty():
                raise ValueError("Sign-in requires an interactive terminal")
            # Device codes belong to the user's terminal, outside Ansible's captured output.
            # pylint: disable-next=unknown-option-value
            # pylint: disable-next=ansible-bad-function
            return subprocess.run(
                command,
                stdin=tty,
                stdout=tty,
                stderr=tty,
                env=environment,
                cwd=home,
                text=True,
                check=False,
                timeout=300,
            )
