"""Persist Git reports and reopen them through GNOME notification activation."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

APPLICATION_ID = "io.github.neilime.WorkstationGitReport"


class GitReportNotifications:
    """Keep the report available after the scheduled sender has exited."""

    def __init__(self, state_home: Path) -> None:
        self.path = state_home / "workstation-manager/git-project-report/latest.txt"

    def save(self, report: str) -> None:
        """Replace the report atomically in a private application directory."""
        if self.path.parent.is_symlink():
            raise ValueError("The Git report directory must not be a symlink")
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.path.parent.chmod(0o700)
        descriptor, temporary = tempfile.mkstemp(prefix=".report-", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(report)
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def run(self, summary: list[str] | None = None, *, service: bool = False) -> int:
        """Send a persistent notification or handle a desktop activation."""
        # Distro PyGObject is required only by this desktop helper, not by the scanner.
        # pylint: disable-next=import-outside-toplevel,import-error
        from gi.repository import Gio, GLib

        application = Gio.Application(application_id=APPLICATION_ID)
        failure = 0

        def open_report(*_arguments) -> None:
            nonlocal failure
            try:
                if not self.path.is_file():
                    raise ValueError("No saved Git report. Run workstation-manager-git-project-report --notify first.")
                Gio.AppInfo.launch_default_for_uri(self.path.as_uri(), None)
            except (GLib.Error, OSError, ValueError) as error:
                failure = 1
                notification = Gio.Notification.new("Git project report could not be opened")
                notification.set_body(str(error))
                application.send_notification("daily-report", notification)
                print(f"Cannot open Git project report: {error}", file=sys.stderr)

        def publish(_action, parameter) -> None:
            title, body = parameter.unpack()
            notification = Gio.Notification.new(title)
            notification.set_body(body)
            notification.set_default_action("app.open-report")
            notification.add_button("Open report", "app.open-report")
            application.send_notification("daily-report", notification)

        open_action = Gio.SimpleAction.new("open-report", None)
        open_action.connect("activate", open_report)
        application.add_action(open_action)
        application.connect("activate", open_report)
        notify_action = Gio.SimpleAction.new("notify", GLib.VariantType.new("(ss)"))
        notify_action.connect("activate", publish)
        application.add_action(notify_action)
        try:
            if summary is not None:
                application.register(None)
                connection = application.get_dbus_connection()
                if connection is None:
                    raise ValueError("A desktop session bus is required for Git report notifications")
                application.activate_action("notify", GLib.Variant("(ss)", tuple(summary)))
                connection.flush_sync(None)
                return 0
            arguments = ["workstation-manager-git-project-report"]
            if service:
                arguments.append("--gapplication-service")
            return application.run(arguments) or failure
        except (GLib.Error, OSError, ValueError) as error:
            print(f"Git report notification failed: {error}", file=sys.stderr)
            return 1


def main(argv: list[str]) -> int:
    """Use the managed user's state directory and native desktop session."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notify", nargs=2, metavar=("TITLE", "BODY"))
    parser.add_argument("--gapplication-service", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    state_home = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    if not state_home.is_absolute():
        print("XDG_STATE_HOME must be an absolute path", file=sys.stderr)
        return 1
    notifications = GitReportNotifications(state_home)
    try:
        if arguments.notify is not None:
            notifications.save(sys.stdin.read())
        return notifications.run(arguments.notify, service=arguments.gapplication_service)
    except (ImportError, OSError, ValueError) as error:
        print(f"Git report notification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
