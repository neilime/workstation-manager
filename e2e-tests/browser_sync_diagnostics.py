"""Inspect incomplete recovery only in the disposable Lima desktop."""

from __future__ import annotations

import json
import platform
from pathlib import Path

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_cdp import (
    BrowserPipe,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_lifecycle import (
    closed_browser,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_native_sync import (
    NativeSync,
)

_STATES = (
    "Disabled",
    "Paused",
    "Start deferred",
    "Initializing",
    "Pending desired configuration",
    "Configuring data types",
    "Active",
)


def main() -> None:
    """Reopen seeded fixture profiles and report only fixed states and verified checks."""

    if not platform.node().startswith("lima-"):
        raise SystemExit("Run browser diagnostics inside the Lima VM.")
    root = Path.home() / ".config/BraveSoftware/Brave-Browser"
    if not root.is_dir():
        return
    with closed_browser(str(root)) as (executable, environment):
        for index, preferences_path in enumerate(sorted(root.glob("*/Preferences"))):
            preferences = json.loads(preferences_path.read_text())
            if not preferences.get("brave_sync_v2", {}).get("seed"):
                continue
            profile = preferences_path.parent
            with BrowserPipe(
                [
                    executable,
                    "--remote-debugging-pipe",
                    "--no-first-run",
                    "--no-default-browser-check",
                    f"--user-data-dir={root}",
                    f"--profile-directory={profile.name}",
                    "--restore-last-session",
                ],
                environment,
            ) as pipe:
                native = NativeSync(pipe, str(profile))
                page = pipe.page("brave://sync-internals")
                pipe.evaluate(page, "chrome.send('requestDataAndRegisterForUpdates'); true")
                verified = native.wait(timeout=120)
                state = pipe.evaluate(
                    page,
                    "(async () => {const {aboutInfo} = await import('./about.js'); "
                    "const stats = (aboutInfo.details || []).flatMap(section => section.data); "
                    f"return {json.dumps(_STATES)}.indexOf(stats.find(item => "
                    "item.stat_name === 'Transport State')?.stat_value);})()",
                )
                label = (
                    _STATES[state]
                    if isinstance(state, int) and not isinstance(state, bool) and 0 <= state < len(_STATES)
                    else "Unknown"
                )
                print(
                    f"Profile {index}: reopened transport={label}; verified={verified}",
                    flush=True,
                )
                if not verified:
                    print(f"Incomplete checks: {native.pending_reason}", flush=True)


if __name__ == "__main__":
    main()
