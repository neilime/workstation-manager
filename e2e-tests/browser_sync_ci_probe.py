"""Verify test-device teardown with an independent peer in the disposable CI VM."""
import json
import platform
from pathlib import Path

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_cdp import BrowserPipe
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_native_sync import NativeSync
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desktop_session import DesktopSession
from browser_sync_fixture import BrowserSyncFixture

if not platform.node().startswith("lima-"):
    raise SystemExit("Run only in the disposable Lima VM.")
root = Path.home() / ".config/BraveSoftware/Brave-Browser"
fixture = BrowserSyncFixture(root, Path.home() / ".local/state/workstation-manager/e2e/browser-devices.json")
fixture.prepare()
environment = DesktopSession.environment()
def open_profile(profile):
    return BrowserPipe(["/usr/bin/brave-browser", "--remote-debugging-pipe", "--no-first-run",
                        "--no-default-browser-check", f"--user-data-dir={root}",
                        f"--profile-directory={profile}"], environment)
try:
    with open_profile("Default") as pipe:
        native = NativeSync(pipe, str(root / "Default"))
        code = native.code()
        native.restore(code)
        assert native.wait()
    fixture.capture()
    assert len(fixture.load()["devices"]) == 1
    print("Captured one newly-created fixture device", flush=True)
    with open_profile("Profile 2") as pipe:
        native = NativeSync(pipe, str(root / "Profile 2"))
        native.restore(code)
        assert native.wait()
    fixture.leave()
    with open_profile("Profile 2") as pipe:
        native = NativeSync(pipe, str(root / "Profile 2"))
        assert native.wait()
        assert native.code() == code
        count = pipe.evaluate(native.settings,
            "window.workstationSyncSettings.sendWithPromise('SyncGetDeviceList').then(devices => devices.length)")
        assert count == 1, count
        print("Recorded device removed; untracked peer remains connected and verified", flush=True)
finally:
    # Both profiles were explicitly created here in a previously absent fixture root.
    for profile in ("Default", "Profile 2"):
        preferences = root / profile / "Preferences"
        if not preferences.exists() or not json.loads(preferences.read_text()).get("brave_sync_v2", {}).get("seed"):
            continue
        with open_profile(profile) as pipe:
            native = NativeSync(pipe, str(root / profile))
            assert pipe.evaluate(native.settings,
                "window.workstationSyncSettings.sendWithPromise('SyncSetupReset')") is True
    print("All disposable control devices removed", flush=True)
