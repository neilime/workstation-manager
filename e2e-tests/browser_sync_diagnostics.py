"""Inspect incomplete recovery only in the disposable Lima desktop."""

from __future__ import annotations

import json
import platform
import tempfile
from pathlib import Path

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_cdp import (
    BrowserPipe,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_lifecycle import (
    automation_arguments,
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


def network_metrics(pipe: BrowserPipe) -> None:
    """Print only fixed Sync metric names and numeric response-code buckets."""

    for name in (
        "Sync.URLFetchResponse",
        "Sync.URLFetchTimedOut",
        "Sync.PostedClientToServerMessage",
        "Sync.PostedClientToServerMessageError2",
    ):
        result = pipe.call("Browser.getHistograms", {"query": name})
        for histogram in result.get("histograms", []):
            if histogram.get("name") != name:
                continue
            buckets = histogram.get("buckets", [])
            if not isinstance(buckets, list) or any(
                not isinstance(bucket, dict)
                or set(bucket) != {"low", "high", "count"}
                or any(not isinstance(value, int) or isinstance(value, bool) for value in bucket.values())
                for bucket in buckets
            ):
                raise ValueError("Unexpected numeric Sync metrics")
            print(f"{name}: {json.dumps(buckets)}", flush=True)


def control_chain(executable: str, environment: dict[str, str]) -> None:
    """Verify an independent empty chain without changing any saved recovery chain."""

    with tempfile.TemporaryDirectory(prefix="workstation-sync-control-") as root:
        with BrowserPipe(
            automation_arguments(executable, root, "Default"),
            environment,
        ) as pipe:
            native = NativeSync(pipe, str(Path(root) / "Default"))
            try:
                native.restore(native.code())
                verified = native.wait()
                print(f"Disposable control chain verified={verified}", flush=True)
                if not verified:
                    print(f"Incomplete checks: {native.pending_reason}", flush=True)
            finally:
                try:
                    network_metrics(pipe)
                finally:
                    # Only this newly created control profile leaves its own chain.
                    removed = pipe.evaluate(
                        native.settings, "window.workstationSyncSettings.sendWithPromise('SyncSetupReset')"
                    )
                    if removed is not True:
                        raise ValueError("Could not remove the disposable control device")


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
                automation_arguments(executable, str(root), profile.name),
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
                network_metrics(pipe)
        control_chain(executable, environment)


if __name__ == "__main__":
    main()
