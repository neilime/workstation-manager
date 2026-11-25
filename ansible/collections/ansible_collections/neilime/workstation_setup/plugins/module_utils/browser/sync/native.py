"""Use Brave's native WebUI to compare codes and observe fresh Sync completion."""

from __future__ import annotations

import json
import re
import time

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser.cdp import (
    BrowserContextLost,
    BrowserPipe,
    BrowserProtocolError,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser.profiles.preferences import (
    PROFILE_PREFERENCES_SCRIPT,
    native_profile_preferences,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser.sync.checkpoint import (
    DOWNLOAD_OBSERVER,
    READ_DOWNLOAD_EVENTS,
    DownloadCheckpoint,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser.sync.devices import (
    _REMOVAL_BINDING,
    _WATCH_REMOVAL,
    SyncDeviceList,
    disposable_device_names,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser.sync.installed_data import (
    BrowserInstalledData,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser.sync.selection import (
    NATIVE_SELECTED_TYPES,
)

# Protocol field numbers are stable type identities, not release pins. Unknown
# active models fail closed until their download/application contracts are known.
_DOWNLOAD_TYPES = {
    "Bookmarks": 32904,
    "Preferences": 37702,
    "Themes": 41210,
    "Encryption Keys": 47745,
    "Extensions": 48119,
    "Apps": 48364,
    "Search Engines": 88610,
    "Extension settings": 96159,
    "App settings": 103656,
    "History Delete Directives": 150251,
    "Device Info": 154522,
    "Priority Preferences": 163425,
    "Dictionary": 170540,
    "Web Apps": 673225,
    "History": 963985,
    "Send Tab To Self": 601980,
    "Account Setting": 1438954,
}

_COMMIT_ONLY_TYPES = ("User Events", "User Consents", "Security Events", "Sharing Message")

_REQUIRED_DATA_TYPES = (
    "Bookmarks",
    "Preferences",
    "Priority Preferences",
    "Search Engines",
    "Dictionary",
    "Themes",
    "Extensions",
    "Extension settings",
    "Web Apps",
    "History",
    "History Delete Directives",
    "Device Info",
)

_DIAGNOSTIC_CHECKS = (
    "Status Response",
    "Transport State",
    "User Actionable Error",
    "Sync Feature Enabled",
    "Setup In Progress",
    "Sync First-Time Setup Complete",
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

# Native type names are mapped to fixed labels before crossing the pipe. Unknown
# names remain unlabelled; arbitrary browser strings never enter task errors.
_DIAGNOSTIC_TYPES = (
    "Bookmarks",
    "Passwords",
    "Preferences",
    "Priority Preferences",
    "Extensions",
    "Extension settings",
    "Apps",
    "App settings",
    "Autofill",
    "Autofill Profiles",
    "Contact Info",
    "History",
    "Typed URLs",
    "History Delete Directives",
    "Sessions",
    "Device Info",
    "Encryption Keys",
    "Reading List",
    "Saved Tab Group",
    "Themes",
    "Search Engines",
    "Dictionary",
    "Web Apps",
    "User Events",
    "User Consents",
    "Send Tab To Self",
    "Security Events",
    "Sharing Message",
    "Account Setting",
)

_SETTINGS_URL = "chrome://settings/braveSync/setup"
_SETTINGS_CHECKS = (
    "Settings Page",
    "Document Loaded",
    "Response Callback",
    "Listener Callback",
    "Native Sender",
    "Callback Bridge",
)

# WebUI pages can bundle cr.js or reject its standalone module import. Reuse
# their existing native callbacks and forward traffic owned by the page.
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

# Only booleans and counts leave diagnostics. In particular getAllNodes contains
# browsing data: reduce it inside the browser, never return it over the pipe.
_START = r"""(async () => {
  if (!CALLBACK_BRIDGE) return false;
  const {addWebUiListener} = window.workstationSyncSettings;
  const state = window.workstationSync = {
    since: Date.now(), downloaded: false, downloadedTypes: [], downloadCoverage: [],
    commitErrors: [], entityCoverage: []
  };
  addWebUiListener('onProtocolEvent', event => {
    if (typeof event.time !== 'number' || event.time < state.since) return;
    const entries = event.proto?.commit?.entryresponse;
    if (event.type === 'Commit Response' && Array.isArray(entries)) {
      const known = ['CONFLICT', 'RETRY', 'INVALID_MESSAGE', 'OVER_QUOTA', 'TRANSIENT_ERROR'];
      state.commitErrors = [...new Set(entries.map(entry => entry.response_type).filter(type => known.includes(type)))];
    }
  });
  if (!DOWNLOAD_OBSERVER) return false;
  chrome.send('setIncludeSpecifics', [false]);
  chrome.send('requestDataAndRegisterForUpdates');
  chrome.send('triggerRefresh');
  return true;
})()""".replace("CALLBACK_BRIDGE", _SETTINGS_BRIDGE).replace("DOWNLOAD_OBSERVER", DOWNLOAD_OBSERVER)

_GET_NODES = r"""(async timeoutMs => {
  const {sendWithPromise} = window.workstationSyncSettings;
  let timer;
  try {
    return await Promise.race([
      sendWithPromise('getAllNodes'),
      new Promise(resolve => { timer = setTimeout(() => resolve(null), timeoutMs); })
    ]);
  } finally { clearTimeout(timer); }
})"""

_GET_ABOUT = r"""(async (timeoutMs, callbacks) => {
  const {addWebUiListener, removeWebUiListener} = callbacks;
  const listeners = [];
  let timer;
  try {
    return await new Promise(resolve => {
      let current;
      const counts = new Map();
      const complete = () => {
        if (!current) return;
        const rows = current.type_status || [];
        if (!rows.filter(row => row.state === 'Running').every(row => counts.has(row.name))) return;
        resolve({info: current, rows: rows.map(row => ({...row, ...counts.get(row.name)}))});
      };
      listeners.push(addWebUiListener('onAboutInfoUpdated', info => {
        current = info;
        counts.clear();
        complete();
      }));
      listeners.push(addWebUiListener('onEntityCountsUpdated', update => {
        const count = update?.entityCounts;
        if (!current || typeof count?.dataType !== 'string'
            || !Number.isInteger(count.entities) || !Number.isInteger(count.nonTombstoneEntities)) return;
        counts.set(count.dataType, {num_entries: count.entities, num_live: count.nonTombstoneEntities});
        complete();
      }));
      timer = setTimeout(() => resolve(null), timeoutMs);
      chrome.send('requestDataAndRegisterForUpdates');
    });
  } finally {
    clearTimeout(timer);
    listeners.forEach(removeWebUiListener);
  }
})"""

_SNAPSHOT = (
    r"""(async (timeoutMs) => {
  if (!window.workstationSync) await START_SYNC;
  const deadline = performance.now() + timeoutMs;
  const {addWebUiListener, removeWebUiListener} = window.workstationSyncSettings;
  let latest;
  const listener = addWebUiListener('onAboutInfoUpdated', info => { latest = info; });
  try {
    // Cycle-completion notifications can precede the native idle-state update.
    // Request current status and its asynchronous counts instead of trusting the
    // page's cached object, which is replaced on every status notification.
    const response = await BOUNDED_ABOUT(
      Math.max(1, deadline - performance.now()), {addWebUiListener, removeWebUiListener});
    const aboutInfo = response?.info;
    const stats = Object.fromEntries((aboutInfo?.details || []).flatMap(
      section => section.data.map(item => [item.stat_name, item.stat_value])));
    const rows = (response?.rows || []).filter(row => row.status !== 'header');
    const active = rows.filter(row => row.state === 'Running');
    const good = {
      'Transport State': 'Active', 'User Actionable Error': 'None',
      'Sync Feature Enabled': true, 'Setup In Progress': false,
      'Sync First-Time Setup Complete': true,
      'Throttled or Backoff': false, 'Cryptographer Ready To Encrypt': true,
      'Cryptographer Has Pending Keys': false, 'GetKey Step Failed': false,
      'Download Step Result': 'Success', 'Commit Step Result': 'Success'
    };
    const checks = Object.fromEntries(Object.entries(good).map(([key, value]) => [key, stats[key] === value]));
    checks['Status Response'] = aboutInfo !== undefined && aboutInfo === latest;
    checks['Server Connection'] = typeof stats['Server Connection'] === 'string'
      && stats['Server Connection'].startsWith('OK');
    checks['Auth Error'] = typeof stats['Auth Error'] === 'string' && stats['Auth Error'].startsWith('OK');
    checks['Actionable Error'] = aboutInfo?.actionable_error_detected === false;
    checks['Unrecoverable Error'] = aboutInfo?.unrecoverable_error_detected === false;
    const required = REQUIRED_DATA_TYPES;
    checks['Required Data Types'] = required.every(
      name => active.some(row => row.name === name));
    const downloads = active.filter(row => !COMMIT_ONLY_TYPES.includes(row.name));
    window.workstationSync.downloaded = downloads.length > 0 && downloads.every(
      row => window.workstationSync.downloadedTypes.includes(DOWNLOAD_TYPES[row.name]));
    window.workstationSync.downloadCoverage = downloads.filter(
      row => !window.workstationSync.downloadedTypes.includes(DOWNLOAD_TYPES[row.name]))
      .map(row => DIAGNOSTIC_TYPES.indexOf(row.name));
    checks['Data Type Status'] = rows.every(
      row => row.status === 'ok' || (row.status === 'severity_info' && row.state === 'Not Running'));
    let healthy = Object.values(checks).every(value => value);
    checks['Entity Response'] = false;
    checks['Entity Counts'] = false;
    checks['Entity Coverage'] = false;
    checks['Entity Metadata'] = false;
    let entityCoverage;
    let pendingChanges = false;
    let pending = true;
    if (healthy) {
      // Native node aggregation waits for every data type and may lose a callback
      // during reconfiguration. A missing reply is incomplete evidence, not a
      // failed DevTools connection. Bound this request so the next poll can retry.
      const groups = await BOUNDED_NODES(Math.max(1, deadline - performance.now()));
      checks['Entity Response'] = Array.isArray(groups);
      // Counts also cover tombstones omitted by getAllNodes. A deletion must have
      // been acknowledged and removed from the native tracker before we succeed.
      const countsReady = active.every(row => Number.isInteger(row.num_entries)
        && Number.isInteger(row.num_live) && row.num_live >= 0 && row.num_entries === row.num_live);
      if (Array.isArray(groups)) {
        entityCoverage = active.flatMap(row => {
          const matching = groups.filter(group => group.type === row.name && Array.isArray(group.nodes));
          const counts = matching.map(group => group.nodes.filter(node => node.metadata).length);
          const covered = counts.length === 1 && counts[0] === row.num_live;
          if (covered) return [];
          return [{type: DIAGNOSTIC_TYPES.indexOf(row.name), live: row.num_live,
            nodes: counts.length === 1 ? counts[0] : -1}];
        });
      }
      const coverageReady = entityCoverage !== undefined && entityCoverage.length === 0;
      const nodesReady = Array.isArray(groups) && groups.every(group =>
        Array.isArray(group.nodes) && group.nodes.every(node => {
          if (!node.metadata && node.PARENT_ID === 'r' && node.IS_DIR === true
              && group.type !== 'Encryption Keys') return true;
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
      pendingChanges = !countsReady || (checks['Entity Response'] && !nodesReady);
    }
    if (aboutInfo !== latest) {
      checks['Status Response'] = false;
      healthy = false;
      pending = true;
    }
    // Retain the last coherent counts for timeout reporting only. Busy cycles,
    // missing replies and replaced status cannot erase or certify this evidence.
    if (checks['Status Response'] && entityCoverage !== undefined) {
      window.workstationSync.entityCoverage = entityCoverage;
    }
    // Initialization can discard a refresh. An idle active engine also needs retries
    // after failed downloads or while uploads and deletions await acknowledgement.
    // A diagnostic coverage mismatch alone does not justify starting another cycle.
    const retryCycle = pendingChanges || !window.workstationSync.downloaded
      || !checks['Download Step Result'] || !checks['Commit Step Result'];
    if (checks['Status Response'] && stats['Transport State'] === 'Active' && stats['Sync Cycle Ongoing'] === false
        && retryCycle) chrome.send('triggerRefresh');
    checks['Fresh Download'] = window.workstationSync.downloaded === true;
    window.workstationSync.checks = checks;
    return {healthy, pending, fresh: window.workstationSync.downloaded === true};
  } finally { removeWebUiListener(listener); }
})""".replace("BOUNDED_NODES", _GET_NODES)
    .replace("BOUNDED_ABOUT", _GET_ABOUT)
    .replace("START_SYNC", _START)
    .replace("DIAGNOSTIC_TYPES", json.dumps(_DIAGNOSTIC_TYPES))
    .replace("DOWNLOAD_TYPES", json.dumps(_DOWNLOAD_TYPES))
    .replace("COMMIT_ONLY_TYPES", json.dumps(_COMMIT_ONLY_TYPES))
    .replace("REQUIRED_DATA_TYPES", json.dumps(_REQUIRED_DATA_TYPES))
)


def _entity_coverage_summary(coverage: object) -> str:
    """Report only allowlisted type labels and validated numeric mismatch counts."""

    if not isinstance(coverage, list):
        raise BrowserProtocolError("Brave returned unsupported entity coverage diagnostics")
    details = []
    for row in coverage:
        if (
            not isinstance(row, dict)
            or set(row) != {"type", "live", "nodes"}
            or any(not isinstance(value, int) or isinstance(value, bool) for value in row.values())
        ):
            raise BrowserProtocolError("Brave returned unsupported entity coverage diagnostics")
        if not -1 <= row["type"] < len(_DIAGNOSTIC_TYPES) or row["live"] < 0 or row["nodes"] < -1:
            raise BrowserProtocolError("Brave returned unsupported entity coverage diagnostics")
        label = _DIAGNOSTIC_TYPES[row["type"]] if row["type"] >= 0 else "Other data type"
        observed = str(row["nodes"]) if row["nodes"] >= 0 else "unavailable"
        details.append(f"{label}: live={row['live']}, nodes={observed}")
    return "; ".join(details)


_CONFIGURE_SELECTION = r"""(async restore => {
  const {addWebUiListener, removeWebUiListener, sendWithPromise} = window.workstationSyncSettings;
  const enabled = SELECTED_TYPES;
  return await new Promise((resolve, reject) => {
    let changing = false;
    const listener = addWebUiListener('sync-prefs-changed', prefs => {
      const keys = Object.keys(prefs).filter(key => key.endsWith('Synced'));
      const available = enabled.every(name => typeof prefs[name + 'Synced'] === 'boolean');
      const matches = available && prefs.syncAllDataTypes === false
        && keys.every(key => prefs[key] === enabled.includes(key.slice(0, -6)));
      if (matches || !available || !restore) {
        removeWebUiListener(listener);
        resolve(matches);
      } else if (!changing) {
        changing = true;
        const selection = Object.fromEntries(keys.map(key => [key, enabled.includes(key.slice(0, -6))]));
        sendWithPromise('SyncSetupSetDatatypes', JSON.stringify({...prefs, ...selection, syncAllDataTypes: false}))
          .then(() => chrome.send('SyncPrefsDispatch')).catch(error => {
            removeWebUiListener(listener);
            reject(error);
          });
      }
    });
    chrome.send('SyncPrefsDispatch');
  });
})""".replace("SELECTED_TYPES", json.dumps(NATIVE_SELECTED_TYPES))


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
        raise ValueError(  # noqa: TRY004 - Schema validation reports ValueError.
            "The browser recovery note must contain exactly 24 recovery words"
        )

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
        self._diagnostics: str | None = None
        version = pipe.page("brave://version")
        matches = self._evaluate(
            version,
            "(async () => {"
            " const {sendWithPromise} = await import('chrome://resources/js/cr.js');"
            " const paths = await sendWithPromise('requestPathInfo');"
            f" return paths?.profilePath === {json.dumps(profile_path)};"
            " })()",
            "checking the selected profile",
        )
        if matches is not True:
            raise BrowserProtocolError("Brave opened a different profile; browser synchronization stopped")
        self.settings = pipe.page("brave://settings/braveSync/setup")
        if self._evaluate_settings("true", "initializing settings callbacks") is not True:
            raise BrowserProtocolError("Brave's native Sync callbacks are unavailable")
        self._wait_for_encryption()

    def _evaluate(self, session: str, expression: str, operation: str, timeout: float = 30) -> object:
        """Identify the failed operation without exposing scripts, responses, or recovery words."""

        try:
            return self.pipe.evaluate(session, expression, timeout=timeout)
        except BrowserProtocolError as error:
            raise type(error)(f"Brave Sync failed while {operation}: {error}") from error

    def _evaluate_settings(self, expression: str, operation: str, timeout: float = 30) -> object:
        """Wait for the owned settings page, then issue one native operation without replay."""

        script = (
            "(() => {"
            " const checks = {"
            f" 'Settings Page': location.href === {json.dumps(_SETTINGS_URL)},"
            " 'Document Loaded': document.readyState === 'complete',"
            " 'Response Callback': typeof window.cr?.webUIResponse === 'function',"
            " 'Listener Callback': typeof window.cr?.webUIListenerCallback === 'function',"
            " 'Native Sender': typeof window.chrome?.send === 'function'"
            " };"
            f" checks['Callback Bridge'] = Object.values(checks).every(Boolean) && {_SETTINGS_BRIDGE};"
            " if (!Object.values(checks).every(Boolean)) return {issued: false, checks};"
            # Checking this document and issuing the operation are synchronous.
            # An exception or lost reply after this point must never be retried.
            f" return Promise.resolve({expression}).then(value => ({{issued: true, value}}));"
            " })()"
        )
        deadline = None
        navigated = False
        checks = dict.fromkeys(_SETTINGS_CHECKS, False)
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                break
            response = self._evaluate(self.settings, script, operation, timeout=timeout)
            if isinstance(response, dict) and set(response) == {"issued", "value"} and response["issued"] is True:
                return response["value"]
            if (
                not isinstance(response, dict)
                or set(response) != {"issued", "checks"}
                or response["issued"] is not False
            ):
                raise BrowserProtocolError("Brave returned unsupported settings readiness diagnostics")
            checks = response["checks"]
            if (
                not isinstance(checks, dict)
                or set(checks) != set(_SETTINGS_CHECKS)
                or any(not isinstance(value, bool) for value in checks.values())
                or all(checks.values())
            ):
                raise BrowserProtocolError("Brave returned unsupported settings readiness diagnostics")
            if deadline is None:
                deadline = time.monotonic() + 30
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if not navigated and (not checks["Settings Page"] or checks["Document Loaded"]):
                # Only this adapter-created tab is recovered, before any request
                # was dispatched. Never navigate a failed in-flight operation.
                result = self.pipe.call(
                    "Page.navigate", {"url": _SETTINGS_URL}, self.settings, timeout=min(30, remaining)
                )
                if "errorText" in result or result.get("isDownload") is True:
                    raise BrowserProtocolError("Brave could not reopen its native Sync settings page")
                navigated = True
            time.sleep(min(0.1, remaining))
        missing = ", ".join(name for name in _SETTINGS_CHECKS if not checks[name])
        raise BrowserProtocolError(f"Brave Sync could not finish {operation}; unavailable: {missing}")

    def _wait_for_encryption(self, timeout: float = 30) -> None:
        """Wait for asynchronous OS encryption before reading or changing a recovery chain."""

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self._evaluate_settings(_ENCRYPTION_STATUS, "waiting for desktop encryption")
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
        return self._evaluate_settings(
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
        result = self._evaluate_settings(
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
        self.pipe.watch_acknowledgement(session, _REMOVAL_BINDING)
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
        if self.pipe.wait_for_acknowledgement(session, _REMOVAL_BINDING) is not True:
            raise BrowserProtocolError("The Sync server did not confirm device cleanup")
        self.pipe.call("Runtime.removeBinding", {"name": _REMOVAL_BINDING}, session)
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
        # Joining resets native type choices; always restore the managed scope.
        self.configure_selection(restore=True)

    def configure_selection(self, *, restore: bool) -> None:
        """Verify the native selection, changing it only during approved restoration."""

        if (
            self._evaluate_settings(
                f"{_CONFIGURE_SELECTION}({json.dumps(restore)})", "checking selected Sync categories"
            )
            is not True
        ):
            raise BrowserProtocolError("Brave did not retain the selected Sync categories; run setup")

    def wait(self, timeout: float = 120) -> bool:
        """Require a fresh successful download and two clean observations without pending changes."""

        self.pending_reason = "Sync verification did not complete"
        deadline = time.monotonic() + timeout
        try:
            return self._wait_until(deadline)
        except BrowserContextLost:
            if time.monotonic() >= deadline:
                raise
            # Restart only observation, once, within the original deadline.
            # A lost page never authorizes replaying enrollment or device removal.
            return self._wait_until(deadline)

    def _wait_until(self, deadline: float) -> bool:
        """Observe one owned diagnostics page without carrying evidence from another context."""

        session = self.pipe.page("brave://sync-internals")
        self._diagnostics = session
        if self._evaluate(session, _START, "starting Sync diagnostics") is not True:
            raise BrowserProtocolError("Brave could not request a fresh Sync cycle")
        checkpoint = DownloadCheckpoint(list(_DOWNLOAD_TYPES.values()))
        clean = 0
        while time.monotonic() < deadline:
            packet = self._evaluate(session, READ_DOWNLOAD_EVENTS, "reading download checkpoints")
            if (
                isinstance(packet, dict)
                and packet.get("available") is False
                and packet == {"available": False, "events": [], "generation": None}
            ):
                raise BrowserContextLost("Brave's download observer was lost")
            generation = checkpoint.generation
            try:
                checkpoint.consume(packet)
            except ValueError as error:
                raise BrowserProtocolError("Brave returned unsupported download evidence") from error
            if checkpoint.generation != generation:
                clean = 0
            self._evaluate(
                session,
                f"window.workstationSync.downloadedTypes = {json.dumps(sorted(checkpoint.completed))}; true",
                "updating download coverage",
            )
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
        self.pending_reason = self._incomplete_reason(session)
        return False

    def verify_installed_data(self, timeout: float = 120) -> None:
        """Wait for actual application installation after the verified Sync boundary."""

        if self._diagnostics is None:
            raise BrowserProtocolError("Brave application readback requires verified Sync")
        installed = BrowserInstalledData(self.pipe, _GET_NODES)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if installed.matches(self._diagnostics):
                return
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        raise BrowserProtocolError(
            f"Brave has not restored all required data; incomplete checks: {installed.pending_reason}"
        )

    def _incomplete_reason(self, session: str) -> str:
        """Distinguish current failures from retained diagnostic evidence without exposing browser data."""

        checks = self._evaluate(session, "window.workstationSync.checks", "reading incomplete Sync checks")
        if (
            not isinstance(checks, dict)
            or set(checks) != set(_DIAGNOSTIC_CHECKS)
            or any(not isinstance(value, bool) for value in checks.values())
        ):
            raise BrowserProtocolError("Brave returned unsupported Sync diagnostics")
        entity_checks = {name for name in _DIAGNOSTIC_CHECKS if name.startswith("Entity ")}
        prerequisites = set(_DIAGNOSTIC_CHECKS) - entity_checks - {"Fresh Download"}
        unavailable = entity_checks if any(not checks[name] for name in prerequisites) else set()
        incomplete = [name for name in _DIAGNOSTIC_CHECKS if not checks[name] and name not in unavailable]
        reason = ", ".join(incomplete) or "two consecutive clean observations"
        if not checks["Fresh Download"]:
            missing = self._evaluate(session, "window.workstationSync.downloadCoverage", "reading download coverage")
            if not isinstance(missing, list) or any(
                not isinstance(index, int) or isinstance(index, bool) or not -1 <= index < len(_DIAGNOSTIC_TYPES)
                for index in missing
            ):
                raise BrowserProtocolError("Brave returned unsupported download coverage diagnostics")
            if missing:
                reason += "; missing downloads: " + ", ".join(
                    _DIAGNOSTIC_TYPES[index] if index >= 0 else "Other data type" for index in missing
                )
        if not checks["Entity Coverage"]:
            coverage = self._evaluate(
                session, "window.workstationSync.entityCoverage", "reading entity coverage counts"
            )
            detail = _entity_coverage_summary(coverage)
            if detail:
                reason += "; last complete entity observation: " + detail
        errors = self._evaluate(session, "window.workstationSync.commitErrors", "reading commit result categories")
        known_errors = {"CONFLICT", "RETRY", "INVALID_MESSAGE", "OVER_QUOTA", "TRANSIENT_ERROR"}
        if isinstance(errors, list) and all(isinstance(error, str) and error in known_errors for error in errors):
            if errors:
                reason += "; commit responses: " + ", ".join(sorted(set(errors)))
        else:
            raise BrowserProtocolError("Brave returned unsupported commit diagnostics")
        codes = self.protocol_error_codes()
        if codes:
            reason += "; Sync protocol error codes: " + ", ".join(map(str, codes))
        return reason
