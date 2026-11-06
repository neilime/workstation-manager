"""Persist drift reports and expose clickable actions through GNOME notifications.

The proposed actions remain usable after the scheduled sender exits: GNOME
re-launches this helper as a D-Bus service when a notification button is pressed,
so each button carries the command to run in the managed user's terminal.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

APPLICATION_ID = "io.github.neilime.WorkstationConfigDrift"


class ConfigDriftNotifications:
    """Keep the report available and run proposed actions after the sender exits."""

    def __init__(self, state_home: Path) -> None:
        self.path = state_home / "workstation-manager/config-drift/latest.txt"

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

        application = Gio.Application(application_id=APPLICATION_ID)
        failure = 0

        def open_report(*_arguments) -> None:
            nonlocal failure
            try:
                if not self.path.is_file():
                    raise ValueError("No saved configuration drift report. Run the drift check first.")
                Gio.AppInfo.launch_default_for_uri(self.path.as_uri(), None)
            except (GLib.Error, OSError, ValueError) as error:
                failure = 1
                notification = Gio.Notification.new("Configuration drift report could not be opened")
                notification.set_body(str(error))
                application.send_notification("config-drift", notification)
                print(f"Cannot open configuration drift report: {error}", file=sys.stderr)

        def run_action(_action, parameter) -> None:
            nonlocal failure
            command = parameter.get_string()
            try:
                launcher = Gio.AppInfo.create_from_commandline(
                    command,
                    None,
                    Gio.AppInfoCreateFlags.NEEDS_TERMINAL,
                )
                launcher.launch(None, None)
            except (GLib.Error, OSError, ValueError) as error:
                failure = 1
                notification = Gio.Notification.new("Configuration drift action could not start")
                notification.set_body(str(error))
                application.send_notification("config-drift", notification)
                print(f"Cannot start configuration drift action: {error}", file=sys.stderr)

        def publish(_action, parameter) -> None:
            title, body, actions = parameter.unpack()
            notification = Gio.Notification.new(title)
            notification.set_body(body)
            notification.set_default_action("app.open-report")
            notification.add_button("Open report", "app.open-report")
            for label, command in actions:
                notification.add_button_with_target_value(
                    label,
                    "app.run-action",
                    GLib.Variant("s", command),
                )
            application.send_notification("config-drift", notification)

        open_action = Gio.SimpleAction.new("open-report", None)
        open_action.connect("activate", open_report)
        application.add_action(open_action)
        application.connect("activate", open_report)
        run_action_handler = Gio.SimpleAction.new("run-action", GLib.VariantType.new("s"))
        run_action_handler.connect("activate", run_action)
        application.add_action(run_action_handler)
        notify_action = Gio.SimpleAction.new("notify", GLib.VariantType.new("(ssa(ss))"))
        notify_action.connect("activate", publish)
        application.add_action(notify_action)
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
            return application.run(arguments) or failure
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
            payload = (title, body, [(label, command) for label, command in arguments.action])
        return notifications.run(payload, service=arguments.gapplication_service)
    except (ImportError, OSError, ValueError) as error:
        print(f"Configuration drift notification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
