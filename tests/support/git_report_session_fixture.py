"""Exercise notification actions on a private bus with a synthetic text viewer."""

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# This fixture runs under distro Python with the GIO packages from the tooling image.
# pylint: disable-next=import-error,no-name-in-module
from gi.repository import Gio, GLib

APPLICATION_ID = "io.github.neilime.WorkstationGitReport"
INTERFACE = """<node><interface name="org.gtk.Notifications">
<method name="AddNotification"><arg type="s" direction="in"/><arg type="s" direction="in"/>
<arg type="a{sv}" direction="in"/></method>
<method name="RemoveNotification"><arg type="s" direction="in"/><arg type="s" direction="in"/></method>
</interface></node>"""


# The fixture owns one complete desktop interaction scenario.
# pylint: disable=too-few-public-methods
class NotificationSession:
    """Stand in for GNOME's notification server while retaining real GIO activation."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self.notifications: list[tuple[str, str, dict[str, Any]]] = []
        self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.connection.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "RequestName",
            GLib.Variant("(su)", ("org.gtk.Notifications", 4)),
            None,
            Gio.DBusCallFlags.NONE,
            5000,
            None,
        )
        self.connection.register_object(
            "/org/gtk/Notifications", Gio.DBusNodeInfo.new_for_xml(INTERFACE).interfaces[0], self._receive, None, None
        )

    def _receive(self, _connection, _sender, _path, _interface, method, parameters, invocation):
        if method == "AddNotification":
            self.notifications.append(parameters.unpack())
        invocation.return_value(None)

    @staticmethod
    def _wait(predicate) -> None:
        deadline = time.monotonic() + 15
        context = GLib.MainContext.default()
        while time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError("Desktop notification interaction timed out")

    def _invoke(self, detailed_action: str) -> None:
        assert detailed_action.startswith("app.")
        self.connection.call_sync(
            APPLICATION_ID,
            "/" + APPLICATION_ID.replace(".", "/"),
            "org.gtk.Actions",
            "Activate",
            GLib.Variant("(sava{sv})", (detailed_action.removeprefix("app."), [], {})),
            None,
            Gio.DBusCallFlags.NONE,
            10000,
            None,
        )

    def _publish(self) -> str:
        count = len(self.notifications)
        command = self.home / ".local/bin/workstation-manager-git-project-report"
        with subprocess.Popen(
            [str(command), "--notify"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        ) as sender:
            self._wait(lambda: sender.poll() is not None and len(self.notifications) > count)
            output, error = sender.communicate(timeout=5)
            assert sender.returncode == 0, error
        return output

    def run(self) -> None:
        """Publish, exit, reactivate from a click, refresh, and surface missing-report failures."""
        opened = self.home / "opened.jsonl"
        output = self._publish()
        assert not opened.exists(), "Sending a notification must not open a viewer"
        owner = self.connection.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
            GLib.Variant("(s)", (APPLICATION_ID,)),
            None,
            Gio.DBusCallFlags.NONE,
            5000,
            None,
        )
        assert not owner.unpack()[0], "The scheduled sender must exit before the click"
        application_id, notification_id, payload = self.notifications[0]
        assert application_id == APPLICATION_ID and notification_id == "daily-report"
        assert "+1 more repositories" in payload["body"]
        assert payload["default-action"] == "app.open-report"
        assert payload["buttons"] == [{"label": "Open full report", "action": "app.open-report"}]
        self._invoke(payload["default-action"])
        self._wait(opened.exists)
        viewed = json.loads(opened.read_text().splitlines()[0])
        assert viewed["report"] == output, "The click must open the full saved report"
        assert "project-5 [main]" in viewed["report"] and "uncommitted.txt" in viewed["report"]
        self._invoke(payload["buttons"][0]["action"])
        self._wait(lambda: len(opened.read_text().splitlines()) == 2)
        (self.home / "projects/project-5/another-note.txt").write_text("More local work\n")
        updated = self._publish()
        assert "another-note.txt" in updated
        self._invoke(self.notifications[-1][2]["default-action"])
        self._wait(lambda: len(opened.read_text().splitlines()) == 3)
        assert json.loads(opened.read_text().splitlines()[-1])["report"] == updated
        Path(viewed["path"]).unlink()
        self._invoke(payload["default-action"])
        self._wait(lambda: len(self.notifications) == 3)
        assert self.notifications[-1][2]["title"] == "Git project report could not be opened"
        assert "No saved Git report" in self.notifications[-1][2]["body"]
        assert len(opened.read_text().splitlines()) == 3


if __name__ == "__main__":
    NotificationSession(Path(sys.argv[1])).run()
