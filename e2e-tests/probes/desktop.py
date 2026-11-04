#!/usr/bin/env python3
"""Check GNOME session relationships that require structured desktop state."""

from __future__ import annotations

import ast
import json
import os
import subprocess
from pathlib import Path


# A probe exposes one cohesive operation, rather than a general testing API.
# pylint: disable=too-few-public-methods
class DesktopProbe:
    """Validate session discovery, configured favorites, bookmarks and shortcuts."""

    def verify(self) -> None:
        """Read session state without exposing its environment or changing preferences."""
        home = Path.home()
        config = json.loads((home / ".local/state/workstation-manager/e2e/goss-vars.json").read_text(encoding="utf-8"))
        sessions = json.loads(subprocess.check_output(["loginctl", "list-sessions", "--json=short"], text=True))
        types = [
            subprocess.check_output(
                ["loginctl", "show-session", str(session["session"]), "-p", "Type", "--value"], text=True
            ).strip()
            for session in sessions
            if session["user"] == config["user"]["name"]
        ]
        assert "wayland" in types
        bookmarks = (home / ".config/gtk-3.0/bookmarks").read_text(encoding="utf-8").splitlines()
        assert [line.split(" ", 1)[0].rstrip("/") for line in bookmarks].count(
            (home / "Documents/dev-projects").as_uri()
        ) == 1
        favorites = ast.literal_eval(
            subprocess.check_output(
                ["dbus-run-session", "--", "gsettings", "get", "org.gnome.shell", "favorite-apps"], text=True
            )
        )
        assert isinstance(favorites, list) and all(isinstance(item, str) for item in favorites)
        selected = config["desktop"]["gnome"]["favorites"]
        if selected is not None:
            browser = subprocess.check_output(["xdg-mime", "query", "default", "text/html"], text=True).strip()
            assert browser
            assert favorites == [browser if item == "browser" else item for item in selected]
        pid = subprocess.check_output(
            ["pgrep", "--euid", str(os.getuid()), "--oldest", "--exact", "gnome-shell"], text=True
        ).strip()
        environment = dict(
            entry.split("=", 1)
            for entry in Path(f"/proc/{pid}/environ").read_text(encoding="utf-8").split("\0")
            if "=" in entry
        )
        directories = [
            Path(environment.get("XDG_DATA_HOME", environment["HOME"] + "/.local/share")),
            *[Path(value) for value in environment.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")],
        ]
        applications = [directory / "applications" for directory in directories]
        assert Path("/var/lib/flatpak/exports/share/applications") in applications
        assert all(any((directory / item).exists() for directory in applications) for item in favorites)
        session_environment = {
            **os.environ,
            "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}",
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{os.getuid()}/bus",
        }
        shortcuts = ast.literal_eval(
            subprocess.check_output(
                ["gsettings", "get", "org.gnome.Ptyxis.Shortcuts", "paste-clipboard"],
                text=True,
                env=session_environment,
            )
        )
        assert {"<Control>v", "<Control><Shift>v", "<Shift>Insert"}.issubset(shortcuts.split("|"))


if __name__ == "__main__":
    DesktopProbe().verify()
