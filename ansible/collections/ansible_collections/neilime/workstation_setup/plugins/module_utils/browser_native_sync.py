"""Use Brave's native WebUI to compare codes and observe fresh Sync completion."""

from __future__ import annotations

import json
import re
import time

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_cdp import (
    BrowserPipe,
    BrowserProtocolError,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_preferences import (
    PROFILE_PREFERENCES_SCRIPT,
    native_profile_preferences,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_sync_devices import (
    _REMOVAL_BINDING,
    _WATCH_REMOVAL,
    SyncDeviceList,
    disposable_device_names,
)

_DIAGNOSTIC_CHECKS = (
    "Transport State",
    "User Actionable Error",
    "Sync Feature Enabled",
    "Setup In Progress",
    "Sync First-Time Setup Complete",
    "Sync Cycle Ongoing",
    "Throttled or Backoff",
    "Cryptographer Ready To Encrypt",
    "Cryptographer Has Pending Keys",
    "GetKey Step Failed",
    "Download Step Result",
    "Commit Step Result",
    "Server Connection",
    "Auth Error",
    "Actionable Error",
    "Unrecoverable Error",
    "Required Data Types",
    "Data Type Status",
    "Entity Response",
    "Entity Counts",
    "Entity Coverage",
    "Entity Metadata",
    "Fresh Download",
)

# Only booleans and counts leave diagnostics. In particular getAllNodes contains
# browsing data: reduce it inside the browser, never return it over the pipe.
_START = r"""(async () => {
  const {addWebUiListener} = await import('chrome://resources/js/cr.js');
  const state = window.workstationSync = {since: Date.now(), downloaded: false, commitErrors: []};
  addWebUiListener('onProtocolEvent', event => {
    if (typeof event.time !== 'number' || event.time < state.since) return;
    if (event.type === 'GetUpdates Response') {
      state.downloaded = /^Received \d+ update\(s\)\.$/.test(event.details);
    }
    const entries = event.proto?.commit?.entryresponse;
    if (event.type === 'Commit Response' && Array.isArray(entries)) {
      const known = ['CONFLICT', 'RETRY', 'INVALID_MESSAGE', 'OVER_QUOTA', 'TRANSIENT_ERROR'];
      state.commitErrors = [...new Set(entries.map(entry => entry.response_type).filter(type => known.includes(type)))];
    }
  });
  chrome.send('setIncludeSpecifics', [false]);
  chrome.send('requestDataAndRegisterForUpdates');
  chrome.send('triggerRefresh');
  return true;
})()"""

_GET_NODES = r"""(async timeoutMs => {
  const {sendWithPromise} = await import('chrome://resources/js/cr.js');
  let timer;
  try {
    return await Promise.race([
      sendWithPromise('getAllNodes'),
      new Promise(resolve => { timer = setTimeout(() => resolve(null), timeoutMs); })
    ]);
  } finally { clearTimeout(timer); }
})"""

_SNAPSHOT = r"""(async (timeoutMs) => {
  if (!window.workstationSync) await START_SYNC;
  const {aboutInfo} = await import('chrome://sync-internals/about.js');
  const stats = Object.fromEntries((aboutInfo?.details || []).flatMap(
    section => section.data.map(item => [item.stat_name, item.stat_value])));
  const rows = (aboutInfo?.type_status || []).filter(row => row.status !== 'header');
  const active = rows.filter(row => row.state === 'Running');
  const good = {
    'Transport State': 'Active', 'User Actionable Error': 'None',
    'Sync Feature Enabled': true, 'Setup In Progress': false,
    'Sync First-Time Setup Complete': true, 'Sync Cycle Ongoing': false,
    'Throttled or Backoff': false, 'Cryptographer Ready To Encrypt': true,
    'Cryptographer Has Pending Keys': false, 'GetKey Step Failed': false,
    'Download Step Result': 'Success', 'Commit Step Result': 'Success'
  };
  const checks = Object.fromEntries(Object.entries(good).map(([key, value]) => [key, stats[key] === value]));
  checks['Server Connection'] = typeof stats['Server Connection'] === 'string'
    && stats['Server Connection'].startsWith('OK');
  checks['Auth Error'] = typeof stats['Auth Error'] === 'string' && stats['Auth Error'].startsWith('OK');
  checks['Actionable Error'] = aboutInfo?.actionable_error_detected === false;
  checks['Unrecoverable Error'] = aboutInfo?.unrecoverable_error_detected === false;
  const required = ['Bookmarks', 'Passwords', 'Preferences', 'Extensions', 'Sessions', 'Device Info'];
  checks['Required Data Types'] = required.every(
    name => active.some(row => row.name === name));
  checks['Data Type Status'] = rows.every(
    row => row.status === 'ok' || (row.status === 'severity_info' && row.state === 'Not Running'));
  const healthy = Object.values(checks).every(value => value);
  checks['Entity Response'] = false;
  checks['Entity Counts'] = false;
  checks['Entity Coverage'] = false;
  checks['Entity Metadata'] = false;
  let pending = true;
  if (healthy) {
    // Native node aggregation waits for every data type and may lose a callback
    // during reconfiguration. A missing reply is incomplete evidence, not a
    // failed DevTools connection. Bound this request so the next poll can retry.
    const groups = await BOUNDED_NODES(timeoutMs);
    checks['Entity Response'] = Array.isArray(groups);
    // Counts also cover tombstones omitted by getAllNodes. A deletion must have
    // been acknowledged and removed from the native tracker before we succeed.
    const countsReady = active.every(row => Number.isInteger(row.num_entries)
      && Number.isInteger(row.num_live) && row.num_entries === row.num_live);
    const coverageReady = Array.isArray(groups) && active.every(row => groups.some(group =>
      group.type === row.name && Array.isArray(group.nodes)
        && group.nodes.filter(node => node.metadata).length === row.num_live));
    const nodesReady = Array.isArray(groups) && groups.every(group =>
      Array.isArray(group.nodes) && group.nodes.every(node => {
        if (!node.metadata && node.PARENT_ID === 'r' && node.IS_DIR === true && group.type !== 'Nigori') return true;
        const metadata = node.metadata;
        if (!metadata) return false;
        const sequence = metadata.sequence_number;
        const acknowledged = metadata.acked_sequence_number;
        return /^\d+$/.test(String(sequence)) && /^\d+$/.test(String(acknowledged))
          && BigInt(sequence) === BigInt(acknowledged);
      }));
    checks['Entity Counts'] = countsReady;
    checks['Entity Coverage'] = coverageReady;
    checks['Entity Metadata'] = nodesReady;
    pending = !countsReady || !coverageReady || !nodesReady;
  }
  // Initialization can discard a refresh. An idle active engine also needs retries
  // after failed downloads or while uploads and deletions await acknowledgement.
  // Native refresh schedules both download and commit work; verification stays strict.
  if (stats['Transport State'] === 'Active' && stats['Sync Cycle Ongoing'] === false
      && (pending || !window.workstationSync.downloaded)) chrome.send('triggerRefresh');
  chrome.send('requestDataAndRegisterForUpdates');
  checks['Fresh Download'] = window.workstationSync.downloaded === true;
  window.workstationSync.checks = checks;
  return {healthy, pending, fresh: window.workstationSync.downloaded === true};
})""".replace("BOUNDED_NODES", _GET_NODES).replace("START_SYNC", _START)


# Settings bundles cr.js, whose standalone module rejects a second initialization.
# Use the page's existing native callbacks and forward traffic owned by its UI.
_SETTINGS_BRIDGE = r"""(() => {
  if (window.workstationSyncSettings) return true;
  const callbacks = window.cr;
  if (typeof callbacks?.webUIResponse !== 'function'
      || typeof callbacks?.webUIListenerCallback !== 'function'
      || typeof window.chrome?.send !== 'function') return false;
  const pending = new Map();
  const listeners = new Set();
  let sequence = 0;
  const respond = callbacks.webUIResponse;
  const notify = callbacks.webUIListenerCallback;
  callbacks.webUIResponse = (id, success, value) => {
    const request = pending.get(id);
    if (!request) return respond(id, success, value);
    pending.delete(id);
    if (success) request.resolve(value);
    else request.reject(new Error('Native Sync request rejected'));
  };
  callbacks.webUIListenerCallback = (event, ...args) => {
    notify(event, ...args);
    for (const listener of listeners) {
      if (listener.event === event) listener.callback(...args);
    }
  };
  window.workstationSyncSettings = {
    sendWithPromise: (method, ...args) => new Promise((resolve, reject) => {
      const id = 'workstation-manager-sync-' + ++sequence;
      pending.set(id, {resolve, reject});
      try { chrome.send(method, [id, ...args]); }
      catch {
        pending.delete(id);
        reject(new Error('Native Sync request failed'));
      }
    }),
    addWebUiListener: (event, callback) => {
      const listener = {event, callback};
      listeners.add(listener);
      return listener;
    },
    removeWebUiListener: listener => listeners.delete(listener)
  };
  return true;
})()"""

_ENABLE_EVERYTHING = r"""(async () => {
  const {addWebUiListener, removeWebUiListener, sendWithPromise} = window.workstationSyncSettings;
  return await new Promise((resolve, reject) => {
    let changing = false;
    const listener = addWebUiListener('sync-prefs-changed', prefs => {
      if (prefs.syncAllDataTypes === true) {
        removeWebUiListener(listener);
        resolve(true);
      } else if (!changing && prefs.syncAllDataTypes === false) {
        changing = true;
        sendWithPromise('SyncSetupSetDatatypes', JSON.stringify({...prefs, syncAllDataTypes: true}))
          .then(() => chrome.send('SyncPrefsDispatch')).catch(reject);
      }
    });
    chrome.send('SyncPrefsDispatch');
  });
})()"""


_ENCRYPTION_STATUS = r"""(async () => {
  const status = await window.workstationSyncSettings.sendWithPromise('SyncSetupGetSyncStatus');
  return {
    available: status.isOsEncryptionAvailable === true,
    decryptionFailed: status.hasSyncWordsDecryptionError !== false
  };
})()"""


def recovery_words(value: object) -> str:
    """Accept the stable code, tolerating copied case and surrounding note text."""

    if not isinstance(value, str):
        raise ValueError("The browser recovery note must contain exactly 24 recovery words")

    lines = [[word.lower() for word in re.findall(r"[A-Za-z]+", line)] for line in value.splitlines()]
    candidates: list[list[str]] = []

    candidates.extend(words for words in lines if len(words) in {24, 25})

    note_words = [word.lower() for word in re.findall(r"[A-Za-z]+", value)]
    if len(note_words) in {24, 25}:
        candidates.append(note_words)

    single_word_lines = [words[0] for words in lines if len(words) == 1]
    if len(single_word_lines) in {24, 25}:
        candidates.append(single_word_lines)

    current_block: list[str] = []
    for words in lines:
        if len(words) == 1:
            current_block.append(words[0])
            continue
        if len(current_block) in {24, 25}:
            candidates.append(current_block)
        current_block = []
    if len(current_block) in {24, 25}:
        candidates.append(current_block)

    for words in candidates:
        normalized = words[:24] if len(words) == 25 else words
        if len(normalized) == 24 and all(re.fullmatch(r"[a-z]+", word) for word in normalized):
            return " ".join(normalized)

    raise ValueError("The browser recovery note must contain exactly 24 recovery words")


class NativeSync:
    """Operate only on the selected profile through its own native Sync handlers."""

    def __init__(self, pipe: BrowserPipe, profile_path: str, *, disposable_names: list[str] | None = None) -> None:
        self.pipe = pipe
        self.disposable_names = disposable_device_names([] if disposable_names is None else disposable_names)
        self.pending_reason = "Sync verification did not complete"
        version = pipe.page("brave://version")
        matches = self._evaluate(
            version,
            f"document.querySelector('#profile_path')?.textContent === {json.dumps(profile_path)}",
            "checking the selected profile",
        )
        if matches is not True:
            raise BrowserProtocolError("Brave opened a different profile; browser synchronization stopped")
        self.settings = pipe.page("brave://settings/braveSync/setup")
        if self._evaluate(self.settings, _SETTINGS_BRIDGE, "initializing settings callbacks") is not True:
            raise BrowserProtocolError("Brave's native Sync callbacks are unavailable")
        self._wait_for_encryption()

    def _evaluate(self, session: str, expression: str, operation: str, timeout: float = 30) -> object:
        """Identify the failed operation without exposing scripts, responses, or recovery words."""

        try:
            return self.pipe.evaluate(session, expression, timeout=timeout)
        except BrowserProtocolError as error:
            raise BrowserProtocolError(f"Brave Sync failed while {operation}: {error}") from error

    def _wait_for_encryption(self, timeout: float = 30) -> None:
        """Wait for asynchronous OS encryption before reading or changing a recovery chain."""

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self._evaluate(self.settings, _ENCRYPTION_STATUS, "waiting for desktop encryption")
            if isinstance(status, dict) and status.get("available") is True:
                if status.get("decryptionFailed") is not False:
                    raise BrowserProtocolError(
                        "Brave could not decrypt its saved recovery code; check desktop keyring access"
                    )
                return
            time.sleep(0.2)
        raise BrowserProtocolError("Brave desktop encryption is unavailable; unlock the desktop keyring and retry")

    def _request(self, method: str, *arguments: object, timeout: float = 30) -> object:
        encoded = ", ".join(json.dumps(value) for value in (method, *arguments))
        return self._evaluate(
            self.settings,
            f"window.workstationSyncSettings.sendWithPromise({encoded})",
            f"calling {method}",
            timeout=timeout,
        )

    def code(self) -> str:
        """Decrypt the existing code using Brave's normal desktop keyring integration."""

        value = self._request("SyncSetupGetPureSyncCode")
        try:
            return recovery_words(value)
        except ValueError as error:
            raise BrowserProtocolError(
                "Brave could not read its recovery code; check desktop keyring access"
            ) from error

    def profile_preferences(self, choices: dict, *, restore: bool) -> None:
        """Verify saved per-profile choices, restoring them through native settings only during setup."""

        expected = json.dumps(native_profile_preferences(choices))
        result = self._evaluate(
            self.settings,
            f"{PROFILE_PREFERENCES_SCRIPT}({expected}, {json.dumps(restore)})",
            "checking profile preferences",
        )
        if not isinstance(result, dict) or result.get("supported") is not True:
            raise BrowserProtocolError("Brave's profile preferences interface is unavailable")
        if result.get("matches") is not True:
            raise BrowserProtocolError("Brave's profile preferences differ from Bitwarden; check policy or run setup")
        if not isinstance(result.get("changed"), bool) or (not restore and result["changed"]):
            raise BrowserProtocolError("Brave returned unsupported profile preferences diagnostics")
        if result.get("changed") is True:
            if not self.wait():
                raise BrowserProtocolError(f"Brave did not synchronize profile preferences; {self.pending_reason}")
            self.profile_preferences(choices, restore=False)

    def protocol_error_codes(self) -> list[int]:
        """Read only numeric Sync error codes, never the server's response payload."""

        name = "Sync.PostedClientToServerMessageError2"
        histograms = self.pipe.call("Browser.getHistograms", {"query": name}).get("histograms", [])
        if not isinstance(histograms, list):
            return []
        codes: set[int] = set()
        for histogram in histograms:
            if not isinstance(histogram, dict) or histogram.get("name") != name:
                continue
            buckets = histogram.get("buckets", [])
            if not isinstance(buckets, list):
                continue
            for bucket in buckets:
                if not isinstance(bucket, dict):
                    continue
                count = bucket.get("count")
                code = bucket.get("low")
                if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
                    continue
                if isinstance(code, int) and not isinstance(code, bool) and 0 <= code <= 255:
                    codes.add(code)
        return sorted(codes)

    def prune_devices(self) -> int:
        """Remove selected remote registrations only with server acknowledgement and a verified readback."""

        before = SyncDeviceList(self._request("SyncGetDeviceList"))
        identities = before.removal_ids(self.disposable_names)
        if not identities:
            return 0
        session = self.pipe.page("brave://sync-internals")
        if self._evaluate(session, _SETTINGS_BRIDGE, "initializing device removal callbacks") is not True:
            raise BrowserProtocolError("Brave's device removal callbacks are unavailable")
        acknowledged = self.pipe.watch_acknowledgement(session, _REMOVAL_BINDING)
        if (
            self._evaluate(session, f"{_WATCH_REMOVAL}({json.dumps(identities)})", "observing device removal")
            is not True
        ):
            raise BrowserProtocolError("Brave could not observe Sync device removal")
        # Revalidate after observer installation, before issuing any deletion.
        current = SyncDeviceList(self._request("SyncGetDeviceList"))
        if current.current != before.current or any(
            current.devices.get(identity) != before.devices[identity] for identity in identities
        ):
            raise BrowserProtocolError("Brave's Sync device list changed before cleanup; retry")
        for identity in identities:
            if self._request("SyncDeleteDevice", identity) is not True:
                raise BrowserProtocolError("Brave rejected Sync device removal")
        if not self.wait():
            raise BrowserProtocolError(
                f"Brave did not finish Sync device cleanup; incomplete checks: {self.pending_reason}"
            )
        self.pipe.call("Runtime.removeBinding", {"name": _REMOVAL_BINDING}, session)
        if not acknowledged():
            raise BrowserProtocolError("The Sync server did not confirm device cleanup")
        after = SyncDeviceList(self._request("SyncGetDeviceList"))
        after.verify_cleanup(before, self.disposable_names)
        return len(identities)

    def restore(self, code: str, *, reset: bool = False) -> None:
        """Join an approved chain with Brave's current pairing suffix and verify it."""

        code = recovery_words(code)
        # Leave/join callbacks can wait for initial Sync work, beyond the local
        # seed write. Give those operations the same budget as Sync
        # verification while retaining short deadlines for local code reads.
        if reset and self._request("SyncSetupReset", timeout=120) is not True:
            raise BrowserProtocolError("Brave could not leave its previous Sync chain")
        pairing = self._request("SyncSetupGetSyncCode")
        if not isinstance(pairing, str) or len(pairing.split()) != 25:
            raise BrowserProtocolError("Brave could not generate the current pairing word")
        try:
            accepted = self._request("SyncSetupSetSyncCode", code + " " + pairing.split()[-1], timeout=120)
        except BrowserProtocolError as error:
            # A missing enrollment callback does not explain whether the engine
            # reached its server. Report only the existing fixed, boolean checks;
            # even a healthy engine cannot replace the failed acknowledgement.
            try:
                completed = self.wait(timeout=5)
                # SyncEnums.THROTTLED is 3, including device-limit rejection.
                throttled = 3 in self.protocol_error_codes()
            except BrowserProtocolError:
                raise error from None
            detail = "enrollment acknowledgement" if completed else self.pending_reason
            if throttled:
                detail += (
                    "; the Sync server throttled enrollment. Check the chain's device limit "
                    "and remove obsolete devices from an already-connected Brave profile before retrying"
                )
            raise BrowserProtocolError(f"{error}; incomplete checks: {detail}") from error
        if accepted is not True or self.code() != code:
            raise BrowserProtocolError("Brave did not join the selected recovery chain")
        # Joining resets Brave's selected types to its defaults. Restore explicitly
        # re-enables the full selection required by backup, through the native API.
        if self._evaluate(self.settings, _ENABLE_EVERYTHING, "enabling Sync everything") is not True:
            raise BrowserProtocolError("Brave did not enable Sync everything after joining the recovery chain")

    def wait(self, timeout: float = 120) -> bool:
        """Require a fresh successful download and two clean observations without pending changes."""

        self.pending_reason = "Sync verification did not complete"
        session = self.pipe.page("brave://sync-internals")
        if self._evaluate(session, _START, "starting Sync diagnostics") is not True:
            raise BrowserProtocolError("Brave could not request a fresh Sync cycle")
        deadline = time.monotonic() + timeout
        clean = 0
        while time.monotonic() < deadline:
            snapshot_timeout = min(30, max(0.001, deadline - time.monotonic()))
            snapshot = self._evaluate(
                session,
                f"{_SNAPSHOT}({int(snapshot_timeout * 1000)})",
                "reading Sync diagnostics",
                # Let the page return incomplete evidence before the transport
                # deadline, including a final query near the Sync deadline.
                timeout=snapshot_timeout + 5,
            )
            if not isinstance(snapshot, dict) or any(
                not isinstance(snapshot.get(key), bool) for key in ("healthy", "pending", "fresh")
            ):
                raise BrowserProtocolError("Brave returned unsupported Sync diagnostics")
            clean = clean + 1 if snapshot == {"healthy": True, "pending": False, "fresh": True} else 0
            if clean >= 2:
                return True
            time.sleep(min(2, max(0, deadline - time.monotonic())))
        checks = self._evaluate(session, "window.workstationSync.checks", "reading incomplete Sync checks")
        if (
            not isinstance(checks, dict)
            or set(checks) != set(_DIAGNOSTIC_CHECKS)
            or any(not isinstance(value, bool) for value in checks.values())
        ):
            raise BrowserProtocolError("Brave returned unsupported Sync diagnostics")
        self.pending_reason = ", ".join(name for name in _DIAGNOSTIC_CHECKS if not checks[name]) or (
            "two consecutive clean observations"
        )
        errors = self._evaluate(session, "window.workstationSync.commitErrors", "reading commit result categories")
        known_errors = {"CONFLICT", "RETRY", "INVALID_MESSAGE", "OVER_QUOTA", "TRANSIENT_ERROR"}
        if isinstance(errors, list) and all(isinstance(error, str) and error in known_errors for error in errors):
            if errors:
                self.pending_reason += "; commit responses: " + ", ".join(sorted(set(errors)))
        else:
            raise BrowserProtocolError("Brave returned unsupported commit diagnostics")
        codes = self.protocol_error_codes()
        if codes:
            self.pending_reason += "; Sync protocol error codes: " + ", ".join(map(str, codes))
        return False
