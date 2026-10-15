"""Track only browser device identities created in a fresh E2E fixture."""

from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_cdp import (
    BrowserPipe,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_lifecycle import (
    automation_arguments,
    closed_browser,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_native_sync import (
    _SETTINGS_BRIDGE,
    NativeSync,
)

# Use the page's native callbacks without loading diagnostic modules. Native
# WebUI events remain usable when the page's module loader rejects an import.
_START_TEARDOWN = r"""(() => {
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
  addWebUiListener('onEntityCountsUpdated', ({entityCounts}) => {
    const row = (state.about.type_status || []).find(item => item.name === entityCounts.dataType);
    if (row) {
      row.num_entries = entityCounts.entities;
      row.num_live = entityCounts.nonTombstoneEntities;
    }
  });
  chrome.send('setIncludeSpecifics', [false]);
  chrome.send('requestDataAndRegisterForUpdates');
  chrome.send('triggerRefresh');
  return true;
})()""".replace("SETTINGS_BRIDGE", _SETTINGS_BRIDGE)

_TEARDOWN_STATE = r"""(identity => {
  if (!window.workstationSync?.about && !START_TEARDOWN) {
    return {active: false, ready: false, matches: false};
  }
  const {about, downloaded} = window.workstationSync;
  const stats = Object.fromEntries((about.details || []).flatMap(
    section => section.data.map(item => [item.stat_name, item.stat_value])));
  const device = (about.type_status || []).find(row => row.name === 'Device Info');
  const active = stats['Transport State'] === 'Active';
  const ready = downloaded === true && stats['Sync Cycle Ongoing'] === false
    && stats['Throttled or Backoff'] === false && stats['Download Step Result'] === 'Success'
    && stats['Commit Step Result'] === 'Success'
    && typeof stats['Server Connection'] === 'string' && stats['Server Connection'].startsWith('OK')
    && typeof stats['Auth Error'] === 'string' && stats['Auth Error'].startsWith('OK')
    && device?.state === 'Running' && device.status === 'ok'
    && Number.isInteger(device.num_entries) && device.num_entries === device.num_live;
  if (active && stats['Sync Cycle Ongoing'] === false && !ready) chrome.send('triggerRefresh');
  chrome.send('requestDataAndRegisterForUpdates');
  return {active, ready, matches: stats['Sync Client ID'] === identity};
})""".replace("START_TEARDOWN", _START_TEARDOWN)

# Device payloads and server IDs stay inside the diagnostic page. Only the
# acknowledgement boolean crosses the pipe. A native leave callback alone can
# succeed after its short upload deadline even when deletion was not committed.
_WATCH_REMOVAL = r"""(async identity => {
  const {addWebUiListener} = window.workstationSyncSettings;
  if (typeof identity !== 'string' || !identity) return false;
  // Chromium's ClientTagHash hashes the empty DeviceInfoSpecifics field
  // (EntitySpecifics field 154522, length-delimited) followed by DeviceInfo_<GUID>.
  // Tombstone commits retain this tag, so no all-data node query is needed.
  const input = new Uint8Array([
    0xd2, 0xb9, 0x4b, 0x00, ...new TextEncoder().encode('DeviceInfo_' + identity)
  ]);
  const digest = await crypto.subtle.digest('SHA-1', input);
  const tag = btoa(String.fromCharCode(...new Uint8Array(digest)));
  const state = window.workstationDeviceRemoval = {
    since: Date.now(), requested: null, acknowledged: false
  };
  addWebUiListener('onProtocolEvent', event => {
    if (typeof event.time !== 'number' || event.time < state.since) return;
    if (event.type === 'Commit Request') {
      const entries = event.proto?.commit?.entries;
      const own = Array.isArray(entries) ? entries.filter(
        entry => entry.client_tag_hash === tag && entry.deleted === true
          && typeof entry.id_string === 'string' && entry.id_string) : [];
      state.requested = own.length === 1 ? own[0].id_string : null;
    }
    if (event.type === 'Commit Response' && state.requested) {
      const entries = event.proto?.commit?.entryresponse;
      state.acknowledged ||= Array.isArray(entries) && entries.some(
        entry => entry.id_string === state.requested && entry.response_type === 'SUCCESS');
      state.requested = null;
    }
  });
  // Native refresh schedules commit work as well as downloads. Keep prompting
  // it while the leave handler waits, before that handler stops the Sync engine.
  state.timer = setInterval(() => chrome.send('triggerRefresh'), 100);
  return true;
})"""


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


def leave_device(pipe: BrowserPipe, profile: Path, identity: str, timeout: float = 120) -> None:
    """Leave only a captured test device after checking its live identity and tracker."""

    native = NativeSync(pipe, str(profile))
    session = pipe.page("brave://sync-internals")
    # Leaving changes Device Info, so verify its tracker and fresh server contact.
    # Browser-data recovery has already been tested by setup; aggregating every
    # data model here adds unrelated asynchronous callbacks to device teardown.
    if pipe.evaluate(session, _START_TEARDOWN) is not True:
        raise ValueError("The test device could not request fresh Sync for teardown")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = pipe.evaluate(
            session,
            f"{_TEARDOWN_STATE}({json.dumps(identity)})",
        )
        if isinstance(state, dict) and state.get("active") is True:
            if state.get("matches") is not True:
                raise ValueError("The live browser device no longer matches the captured test identity")
            if (
                state.get("ready") is True
                and pipe.evaluate(session, f"{_WATCH_REMOVAL}({json.dumps(identity)})", timeout=15) is True
            ):
                break
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    else:
        raise ValueError("The test device could not verify Sync readiness for teardown; its identity was retained")
    # This native operation takes no device ID: it leaves only the selected
    # profile's current device, whose freshly-created identity was checked above.
    try:
        removed = pipe.evaluate(
            native.settings,
            "window.workstationSyncSettings.sendWithPromise('SyncSetupReset')",
            timeout=120,
        )
    finally:
        acknowledged = pipe.evaluate(
            session,
            "clearInterval(window.workstationDeviceRemoval.timer); "
            "window.workstationDeviceRemoval.acknowledged === true",
        )
    if removed is not True or acknowledged is not True:
        raise ValueError("The Sync server did not confirm removal of the captured test device")


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
        self.manifest.write_text(json.dumps(record))

    def leave(self) -> None:
        """Leave only captured devices; never enumerate other profiles for mutation."""

        if not self.manifest.exists():
            return
        record = self.load()
        if record.get("phase") != "captured":
            raise ValueError("Browser fixture identities were not captured; the VM must be retained")
        if not record["devices"]:
            return
        with closed_browser(str(self.root)) as (executable, environment):
            for directory, identity in list(record["devices"].items()):
                if Path(directory).name != directory or directory in {".", ".."}:
                    raise ValueError("Invalid captured browser fixture directory")
                profile = self.root / directory
                if device_identity(profile) != identity:
                    raise ValueError("The browser profile no longer matches the captured test identity")
                with BrowserPipe(
                    automation_arguments(executable, str(self.root), directory),
                    environment,
                ) as pipe:
                    leave_device(pipe, profile, identity)
                del record["devices"][directory]
                self.manifest.write_text(json.dumps(record))
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
