"""Track only browser device identities created in a fresh E2E fixture."""

from __future__ import annotations

import argparse
import json
import platform
import time
from collections.abc import Callable
from pathlib import Path

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_cdp import (
    BrowserPipe,
    BrowserProtocolError,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_lifecycle import (
    automation_arguments,
    browser_processes,
    closed_browser,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_native_sync import (
    _GET_ABOUT,
    _SETTINGS_BRIDGE,
    NativeSync,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_sync_devices import (
    _REMOVAL_BINDING,
    _REMOVAL_CHECKS,
    _WATCH_REMOVAL,
)
from browser_sync_network_gate import SyncNetworkGate
from browser_sync_teardown_state import teardown_profile, write_private_json

_COMMIT_BINDING = "workstationDeviceRemovedCommit"

_TEARDOWN_CHECKS = (
    "Diagnostic Page",
    "Native Callbacks",
    "Readiness Observer",
    "Status Response",
    "Transport State",
    "Fresh Download",
    "Sync Cycle Ongoing",
    "Throttled or Backoff",
    "Download Step Result",
    "Commit Step Result",
    "Server Connection",
    "Auth Error",
    "Device Info State",
    "Device Info Status",
    "Device Info Counts",
)

# Use the page's native callbacks without loading diagnostic modules. Native
# WebUI events remain usable when the page's module loader rejects an import.
_START_TEARDOWN = r"""(() => {
  if (location.href !== 'chrome://sync-internals/' || document.readyState !== 'complete') return false;
  if (!SETTINGS_BRIDGE) return false;
  const {addWebUiListener} = window.workstationSyncSettings;
  const state = window.workstationSync = {since: Date.now(), downloaded: false, about: {}};
  addWebUiListener('onProtocolEvent', event => {
    if (typeof event.time !== 'number' || event.time < state.since) return;
    if (event.type === 'GetUpdates Response') {
      state.downloaded = /^Received \d+ update\(s\)\.$/.test(event.details);
    }
  });
  addWebUiListener('onAboutInfoUpdated', about => { state.about = about; });
  chrome.send('setIncludeSpecifics', [false]);
  chrome.send('requestDataAndRegisterForUpdates');
  chrome.send('triggerRefresh');
  return true;
})()""".replace("SETTINGS_BRIDGE", _SETTINGS_BRIDGE)

_TEARDOWN_STATE = (
    r"""(async (identity, timeoutMs) => {
  const checks = Object.fromEntries(CHECK_NAMES.map(name => [name, false]));
  const expectedPage = location.href === 'chrome://sync-internals/';
  const loaded = document.readyState === 'complete';
  checks['Diagnostic Page'] = expectedPage && loaded;
  checks['Native Callbacks'] = typeof window.cr?.webUIResponse === 'function'
    && typeof window.cr?.webUIListenerCallback === 'function' && typeof window.chrome?.send === 'function';
  if (checks['Diagnostic Page'] && checks['Native Callbacks']) {
    checks['Readiness Observer'] = !!window.workstationSync?.about || START_TEARDOWN;
  }
  if (!checks['Readiness Observer']) {
    return {active: false, stopped: false, ready: false, matches: false,
      needsNavigation: !expectedPage || loaded, checks};
  }
  const response = await BOUNDED_ABOUT(timeoutMs, window.workstationSyncSettings);
  const about = response?.info || {};
  const {downloaded} = window.workstationSync;
  const stats = Object.fromEntries((about.details || []).flatMap(
    section => section.data.map(item => [item.stat_name, item.stat_value])));
  const device = (response?.rows || []).find(row => row.name === 'Device Info');
  const active = stats['Transport State'] === 'Active';
  Object.assign(checks, {
    'Status Response': response !== null && about === window.workstationSync.about,
    'Transport State': active,
    'Fresh Download': downloaded === true,
    'Sync Cycle Ongoing': stats['Sync Cycle Ongoing'] === false,
    'Throttled or Backoff': stats['Throttled or Backoff'] === false,
    'Download Step Result': stats['Download Step Result'] === 'Success',
    'Commit Step Result': stats['Commit Step Result'] === 'Success',
    'Server Connection': typeof stats['Server Connection'] === 'string'
      && stats['Server Connection'].startsWith('OK'),
    'Auth Error': typeof stats['Auth Error'] === 'string' && stats['Auth Error'].startsWith('OK'),
    'Device Info State': device?.state === 'Running',
    'Device Info Status': device?.status === 'ok',
    'Device Info Counts': Number.isInteger(device?.num_entries) && device.num_entries === device.num_live
  });
  const ready = Object.entries(checks).every(([name, passed]) => name === 'Transport State' || passed);
  if (checks['Status Response'] && active && stats['Sync Cycle Ongoing'] === false && !ready)
    chrome.send('triggerRefresh');
  return {active, stopped: stats['Transport State'] === 'Disabled', ready,
    matches: stats['Sync Client ID'] === identity, needsNavigation: false, checks};
})""".replace("START_TEARDOWN", _START_TEARDOWN)
    .replace("BOUNDED_ABOUT", _GET_ABOUT)
    .replace("CHECK_NAMES", json.dumps(_TEARDOWN_CHECKS))
)

# Native leave has a short upload deadline. Observe the commit without starting
# competing downloads; the fixture enables Chromium's immediate Sync scheduling.
_WATCH_TEARDOWN_REMOVAL = r"""(async (identities, readBack = true, binding) => {
  const observed = await WATCH_REMOVAL(identities, readBack, binding);
  if (observed) clearInterval(window.workstationDeviceRemoval.timer);
  return observed;
})""".replace("WATCH_REMOVAL", _WATCH_REMOVAL)

_LEAVE_DEVICE = r"""(async identity => {
  const {sendWithPromise} = window.workstationSyncSettings;
  const devices = await sendWithPromise('SyncGetDeviceList');
  const current = Array.isArray(devices) ? devices.filter(device => device?.isCurrentDevice === true) : [];
  if (current.length !== 1 || current[0].guid !== identity) return null;
  return await sendWithPromise('SyncSetupReset');
})"""


class UnconfirmedDeviceRemoval(ValueError):
    """Native leave completed without proof that the server committed the deletion."""


def reset_device(pipe: BrowserPipe, settings: str, identity: str) -> bool:
    """Require the captured identity in the settings target before invoking native leave."""

    removed = pipe.evaluate(settings, f"{_LEAVE_DEVICE}({json.dumps(identity)})", timeout=120)
    if removed is None:
        raise ValueError("The settings page no longer matches the captured test identity")
    if not isinstance(removed, bool):
        raise ValueError(  # noqa: TRY004 - Schema validation reports ValueError.
            "Brave returned unsupported native leave diagnostics"
        )
    return removed


def device_identity(profile: Path, *, require_initialized: bool = False) -> str | None:
    """Read initialized device identity metadata without returning recovery words."""

    preferences_path = profile / "Preferences"
    if profile.is_symlink() or preferences_path.is_symlink():
        raise ValueError("Refusing linked browser fixture data")
    preferences = json.loads(preferences_path.read_text())
    if not preferences.get("brave_sync_v2", {}).get("seed"):
        return None
    accounts = preferences.get("sync", {}).get("transport_data_per_account", {})
    initialized = [
        account.get("sync.cache_guid")
        for account in accounts.values()
        if account.get("sync.birthday") and account.get("sync.cache_guid")
    ]
    if not initialized:
        if require_initialized:
            raise ValueError("A successfully recovered test profile has no initialized device identity")
        return None
    if len(initialized) != 1 or not isinstance(initialized[0], str):
        raise ValueError("Unexpected browser fixture device identity")
    return initialized[0]


def incomplete_removal_checks(pipe: BrowserPipe, session: str) -> str:
    """Report fixed observation stages without exposing device IDs or protocol payloads."""

    try:
        checks = pipe.evaluate(session, "window.workstationDeviceRemoval?.checks", timeout=5)
    except BrowserProtocolError:
        return "removal observer unavailable"
    if (
        not isinstance(checks, dict)
        or set(checks) != set(_REMOVAL_CHECKS)
        or any(not isinstance(value, bool) for value in checks.values())
    ):
        return "removal observer unavailable"
    return ", ".join(name for name in _REMOVAL_CHECKS if not checks[name]) or "binding delivery"


def wait_for_removal_readiness(
    pipe: BrowserPipe, session: str, identity: str, acknowledged: Callable[[], bool], timeout: float
) -> bool:
    """Return server proof, or wait until the captured tracker can safely request deletion."""

    # Leaving changes Device Info, so verify its tracker and fresh server contact.
    # Browser-data recovery has already been tested by setup; aggregating every
    # data model here adds unrelated asynchronous callbacks to device teardown.
    deadline = time.monotonic() + timeout
    checks = dict.fromkeys(_TEARDOWN_CHECKS, False)
    while time.monotonic() < deadline:
        snapshot_timeout = min(30, max(0.001, deadline - time.monotonic()))
        state = pipe.evaluate(
            session,
            f"{_TEARDOWN_STATE}({json.dumps(identity)}, {int(snapshot_timeout * 1000)})",
            timeout=snapshot_timeout + 5,
        )
        if not isinstance(state, dict) or set(state) != {
            "active",
            "stopped",
            "ready",
            "matches",
            "needsNavigation",
            "checks",
        }:
            raise ValueError("Brave returned unsupported teardown diagnostics; the test device identity was retained")
        checks = state["checks"]
        if (
            any(
                not isinstance(state[name], bool)
                for name in ("active", "stopped", "ready", "matches", "needsNavigation")
            )
            or not isinstance(checks, dict)
            or set(checks) != set(_TEARDOWN_CHECKS)
            or any(not isinstance(value, bool) for value in checks.values())
        ):
            raise ValueError("Brave returned unsupported teardown diagnostics; the test device identity was retained")
        if acknowledged() and state["stopped"] and checks["Status Response"]:
            return True
        if state["needsNavigation"]:
            # Reopening this page after allowing downloads could miss the very
            # tombstone we need. Retry with a new gated copy instead.
            raise BrowserProtocolError("Brave lost its teardown observer; the test identity was retained")
        if state["active"]:
            if not state["matches"]:
                raise ValueError("The live browser device no longer matches the captured test identity")
            if state["ready"]:
                return False
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    detail = ", ".join(name for name in _TEARDOWN_CHECKS if not checks[name]) or "removal observer"
    raise ValueError(
        "The test device could not verify Sync readiness for teardown; "
        f"its identity was retained; incomplete checks: {detail}"
    )


def leave_device(
    pipe: BrowserPipe, profile: Path, identity: str, timeout: float = 120, *, network: SyncNetworkGate
) -> None:
    """Leave only a captured test device after checking its live identity and tracker."""

    native = NativeSync(pipe, str(profile))
    session = pipe.page("brave://sync-internals")
    acknowledged = pipe.watch_acknowledgement(session, _REMOVAL_BINDING)
    if (
        pipe.evaluate(session, _START_TEARDOWN) is not True
        or pipe.evaluate(session, f"{_WATCH_TEARDOWN_REMOVAL}({json.dumps([identity])})", timeout=15) is not True
    ):
        raise BrowserProtocolError("Brave could not observe device removal; the test identity was retained")
    # A retry can receive its own server tombstone and immediately stop Sync.
    # Install the observer before allowing any server contact, so that deletion
    # is proved even when no active tracker remains to satisfy readiness.
    network.release()
    if wait_for_removal_readiness(pipe, session, identity, acknowledged, timeout):
        return
    # A pending local Device Info update can win a conflict with a downloaded
    # tombstone. An active client therefore needs a new deletion and new proof;
    # an earlier readback must never satisfy this reset's acknowledgement.
    committed = pipe.watch_acknowledgement(session, _COMMIT_BINDING)
    if (
        pipe.evaluate(
            session,
            f"{_WATCH_TEARDOWN_REMOVAL}({json.dumps([identity])}, false, {json.dumps(_COMMIT_BINDING)})",
            timeout=15,
        )
        is not True
    ):
        raise BrowserProtocolError("Brave could not observe the new device deletion; the test identity was retained")
    # This native operation takes no device ID: it leaves only the selected
    # profile's current device, whose freshly-created identity was checked above.
    try:
        removed = reset_device(pipe, native.settings, identity)
    except BrowserProtocolError:
        if committed():
            return
        raise
    if removed is not True:
        raise ValueError("Brave did not confirm leaving the captured test device")
    # The settings callback and diagnostic event arrive from separate targets.
    # Keep the binding installed until its event arrives; confirmation must not
    # depend on page globals that leave may discard. The pipe closes every target.
    if pipe.wait_for_acknowledgement(session, _COMMIT_BINDING) is not True:
        raise UnconfirmedDeviceRemoval(
            "The Sync server did not confirm removal of the captured test device; "
            f"incomplete checks: {incomplete_removal_checks(pipe, session)}"
        )


class BrowserSyncFixture:
    """Record ownership before setup and capture the exact new device identities."""

    def __init__(self, root: Path, manifest: Path) -> None:
        self.root = root
        self.manifest = manifest

    def prepare(self) -> None:
        """Require an absent browser tree so existing profiles cannot become fixtures."""

        if self.root.exists() or self.root.is_symlink():
            raise ValueError("Browser E2E setup requires a fresh VM without existing Brave profiles")
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        with self.manifest.open("x", encoding="utf-8") as handle:
            self.manifest.chmod(0o600)
            json.dump({"root": str(self.root), "host": platform.node(), "phase": "prepared", "devices": {}}, handle)

    def load(self) -> dict:
        """Reject ownership records from another fixture or browser tree."""

        if self.manifest.is_symlink() or self.root.is_symlink():
            raise ValueError("Refusing linked browser fixture data")
        record = json.loads(self.manifest.read_text())
        if record.get("root") != str(self.root) or record.get("host") != platform.node():
            raise ValueError("Browser fixture ownership does not match this VM")
        return record

    def capture(self, *, require_initialized: bool = False) -> None:
        """Capture initialized identities created by setup in the previously absent tree."""

        record = self.load()
        if record.get("phase") != "prepared":
            raise ValueError("Browser fixture identities were already captured")
        for preferences in sorted(self.root.glob("*/Preferences")):
            identity = device_identity(preferences.parent, require_initialized=require_initialized)
            if identity:
                record["devices"][preferences.parent.name] = identity
        record["phase"] = "captured"
        write_private_json(self.manifest, record)

    def leave_captured_device(
        self, profile: Path, identity: str, executable: str, environment: dict[str, str], confirmed: Callable[[], None]
    ) -> None:
        """Leave through isolated copies; keep the original identity available after every failure."""

        for attempt in range(3):
            confirmed_removal = False
            try:
                with (
                    teardown_profile(self.root, profile, self.manifest.parent) as copied,
                    SyncNetworkGate() as network,
                ):
                    arguments = [
                        argument
                        for argument in automation_arguments(executable, str(copied.parent), copied.name)
                        if argument != "--restore-last-session"
                    ]
                    with BrowserPipe(
                        [
                            *arguments,
                            "--sync-short-nudge-delay-for-test",
                            f"--proxy-server={network.proxy_url}",
                            "--disable-quic",
                            "--disable-extensions",
                            "about:blank",
                        ],
                        environment,
                    ) as pipe:
                        leave_device(pipe, copied, identity, network=network)
                        # Persist proof before closing targets: a failed browser
                        # shutdown must not make the next invocation reset again.
                        confirmed()
                        confirmed_removal = True
                return
            except (UnconfirmedDeviceRemoval, BrowserProtocolError) as error:
                self.check_stopped_copies()
                if confirmed_removal or attempt == 2:
                    raise
                print(f"Retrying E2E device removal ({attempt + 1}/3): {error}", flush=True)
                time.sleep(2**attempt)

    def check_stopped_copies(self) -> None:
        """Prevent overlapping same-identity writers after an interrupted attempt."""

        for copied_root in self.manifest.parent.glob("browser-teardown-*"):
            if copied_root.is_symlink() or browser_processes(copied_root):
                raise ValueError("A previous teardown browser is still running; its private copy and VM were retained")

    def leave(self) -> None:
        """Leave only captured devices; never enumerate other profiles for mutation."""

        if not self.manifest.exists():
            return
        record = self.load()
        if record.get("phase") != "captured":
            raise ValueError("Browser fixture identities were not captured; the VM must be retained")
        self.check_stopped_copies()
        if not record["devices"]:
            return
        with closed_browser(str(self.root), reopen=False) as (executable, environment):
            for directory, identity in list(record["devices"].items()):
                if Path(directory).name != directory or directory in {".", ".."}:
                    raise ValueError("Invalid captured browser fixture directory")
                profile = self.root / directory
                if device_identity(profile) != identity:
                    raise ValueError("The browser profile no longer matches the captured test identity")

                def confirmed(selected: str = directory) -> None:
                    del record["devices"][selected]
                    write_private_json(self.manifest, record)

                self.leave_captured_device(profile, identity, executable, environment, confirmed)
                print("The Sync server confirmed removal of a captured E2E browser device.", flush=True)


def main() -> None:
    """Operate only inside the disposable Lima guest."""

    if not platform.node().startswith("lima-"):
        raise SystemExit("Run browser fixture management inside the Lima VM.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "capture", "leave"))
    parser.add_argument("--require-initialized", action="store_true")
    arguments = parser.parse_args()
    fixture = BrowserSyncFixture(
        Path.home() / ".config/BraveSoftware/Brave-Browser",
        Path.home() / ".local/state/workstation-manager/e2e/browser-devices.json",
    )
    if arguments.action == "capture":
        fixture.capture(require_initialized=arguments.require_initialized)
    elif arguments.require_initialized:
        parser.error("--require-initialized applies only to capture")
    else:
        getattr(fixture, arguments.action)()


if __name__ == "__main__":
    main()
