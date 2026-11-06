"""Persist drift reports and expose clickable actions through GNOME notifications.

The proposed actions remain usable after the scheduled sender exits: GNOME
re-launches this helper as a D-Bus service when a notification button is pressed,
so each button carries the command to run in the managed user's terminal.
"""

# This helper is installed standalone per role and deliberately mirrors the
# git_project_report notification structure, so cross-file similarity is expected.
# pylint: disable=duplicate-code

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

APPLICATION_ID = "io.github.neilime.WorkstationConfigDrift"


class ConfigDriftNotifications:
    """Keep the report available and run proposed actions after the sender exits."""

    def __init__(self, state_home: Path) -> None:
        self.path = state_home / "workstation-manager/config-drift/latest.txt"
        # PyGObject modules and the application are bound at runtime inside run(),
        # so callbacks reuse them without re-importing or reconstructing state.
        self._gio: Any = None
        self._glib: Any = None
        self._application: Any = None
        self._failure = 0

    def save(self, report: str) -> None:
        """Replace the report atomically in a private application directory."""
        if self.path.parent.is_symlink():
            raise ValueError("The config drift report directory must not be a symlink")
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.path.parent.chmod(0o700)
        descriptor, temporary = tempfile.mkstemp(prefix=".report-", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(report)
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def _fail(self, title: str, error: object) -> None:
        """Surface a handler failure to the user and the scheduled command."""
        self._failure = 1
        notification = self._gio.Notification.new(title)
        notification.set_body(str(error))
        self._application.send_notification("config-drift", notification)
        print(f"{title}: {error}", file=sys.stderr)

    def _open_report(self, *_arguments) -> None:
        """Open the saved report, reporting any failure to the user."""
        try:
            if not self.path.is_file():
                raise ValueError("No saved configuration drift report. Run the drift check first.")
            self._gio.AppInfo.launch_default_for_uri(self.path.as_uri(), None)
        except (self._glib.Error, OSError, ValueError) as error:
            self._fail("Configuration drift report could not be opened", error)

    def _run_action(self, _action, parameter) -> None:
        """Launch a proposed action in the managed user's terminal."""
        try:
            launcher = self._gio.AppInfo.create_from_commandline(
                parameter.get_string(),
                None,
                self._gio.AppInfoCreateFlags.NEEDS_TERMINAL,
            )
            launcher.launch(None, None)
        except (self._glib.Error, OSError, ValueError) as error:
            self._fail("Configuration drift action could not start", error)

    def _publish(self, _action, parameter) -> None:
        """Send the notification with the default action and proposed buttons."""
        title, body, actions = parameter.unpack()
        notification = self._gio.Notification.new(title)
        notification.set_body(body)
        notification.set_default_action("app.open-report")
        notification.add_button("Open report", "app.open-report")
        for label, command in actions:
            target = self._glib.Variant("s", command)
            notification.add_button_with_target_value(label, "app.run-action", target)
        self._application.send_notification("config-drift", notification)

    def _build_application(self) -> Any:
        """Create the application and register its notification actions."""
        application = self._gio.Application(application_id=APPLICATION_ID)
        self._application = application
        for name, signature, handler in (
            ("open-report", None, self._open_report),
            ("run-action", "s", self._run_action),
            ("notify", "(ssa(ss))", self._publish),
        ):
            variant_type = self._glib.VariantType.new(signature) if signature else None
            action = self._gio.SimpleAction.new(name, variant_type)
            action.connect("activate", handler)
            application.add_action(action)
        application.connect("activate", self._open_report)
        return application

    def run(
        self,
        payload: tuple[str, str, list[tuple[str, str]]] | None = None,
        *,
        service: bool = False,
    ) -> int:
        """Send a notification with proposed actions or handle a desktop activation."""
        # Distro PyGObject is required only by this desktop helper, not by the scanner.
        # pylint: disable-next=import-outside-toplevel,import-error
        from gi.repository import Gio, GLib

        self._gio, self._glib = Gio, GLib
        application = self._build_application()
        try:
            if payload is not None:
                application.register(None)
                connection = application.get_dbus_connection()
                if connection is None:
                    raise ValueError("A desktop session bus is required for configuration drift notifications")
                application.activate_action("notify", GLib.Variant("(ssa(ss))", payload))
                connection.flush_sync(None)
                return 0
            arguments = ["workstation-manager-config-drift"]
            if service:
                arguments.append("--gapplication-service")
            return application.run(arguments) or self._failure
        except (GLib.Error, OSError, ValueError) as error:
            print(f"Configuration drift notification failed: {error}", file=sys.stderr)
            return 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notify", nargs=2, metavar=("TITLE", "BODY"))
    parser.add_argument(
        "--action",
        action="append",
        nargs=2,
        default=[],
        metavar=("LABEL", "COMMAND"),
    )
    parser.add_argument("--gapplication-service", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Use the managed user's state directory and native desktop session."""
    arguments = parse_args(argv)
    state_home = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    if not state_home.is_absolute():
        print("XDG_STATE_HOME must be an absolute path", file=sys.stderr)
        return 1
    notifications = ConfigDriftNotifications(state_home)
    try:
        payload: tuple[str, str, list[tuple[str, str]]] | None = None
        if arguments.notify is not None:
            notifications.save(sys.stdin.read())
            title, body = arguments.notify
            payload = (title, body, [tuple(action) for action in arguments.action])
        return notifications.run(payload, service=arguments.gapplication_service)
    except (ImportError, OSError, ValueError) as error:
        print(f"Configuration drift notification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
