"""Compare fresh and existing disposable Sync chains in the CI desktop."""

import platform
import tempfile
import time

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_cdp import BrowserPipe
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_native_sync import NativeSync
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desktop_session import DesktopSession

if not platform.node().startswith("lima-"):
    raise SystemExit("Run only in the disposable Lima VM.")

environment = DesktopSession.environment()
with tempfile.TemporaryDirectory(prefix="workstation-ci-chain-") as root:
    arguments = ["/usr/bin/brave-browser", "--remote-debugging-pipe", "--no-first-run",
                 "--no-default-browser-check", f"--user-data-dir={root}", "--restore-last-session"]
    enrolled = []
    try:
        code = None
        for profile in ("Default", "Profile 2"):
            with BrowserPipe([*arguments, f"--profile-directory={profile}"], environment) as pipe:
                native = NativeSync(pipe, root + "/" + profile)
                if code is None:
                    code = native.code()
                enrolled.append(profile)
                start = time.monotonic()
                native.restore(code)
                print(profile, "enrollment seconds:", round(time.monotonic() - start, 1), flush=True)
                verified = native.wait()
                print(profile, "verified:", verified, "total seconds:", round(time.monotonic() - start, 1), flush=True)
                if not verified:
                    raise RuntimeError("Incomplete checks: " + native.pending_reason)
    finally:
        for profile in enrolled:
            with BrowserPipe([*arguments, f"--profile-directory={profile}"], environment) as pipe:
                native = NativeSync(pipe, root + "/" + profile)
                print(profile, "removed test device:", native._request("SyncSetupReset", timeout=30), flush=True)
