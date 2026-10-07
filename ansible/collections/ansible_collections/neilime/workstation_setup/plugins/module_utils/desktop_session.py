"""Read the managed user's live graphical session without forwarding credentials."""

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
    )
)


# One query returns the complete allowlisted environment.
# pylint: disable=too-few-public-methods
class DesktopSession:
    """Discover desktop access through the effective user's systemd manager."""

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
