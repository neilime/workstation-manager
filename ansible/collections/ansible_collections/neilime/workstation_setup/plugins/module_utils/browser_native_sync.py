"""Use Brave's native WebUI to compare codes and observe fresh Sync completion."""

from __future__ import annotations

import json
import re
import time

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_cdp import (
    BrowserPipe,
    BrowserProtocolError,
)

# Only booleans and counts leave diagnostics. In particular getAllNodes contains
# browsing data: reduce it inside the browser, never return it over the pipe.
_START = r"""(async () => {
  const {addWebUiListener} = await import('chrome://resources/js/cr.js');
  window.workstationSync = {since: Date.now(), downloaded: false};
  addWebUiListener('onProtocolEvent', event => {
    const state = window.workstationSync;
    if (typeof event.time !== 'number' || event.time < state.since) return;
    if (event.type === 'GetUpdates Response') {
      state.downloaded = /^Received \d+ update\(s\)\.$/.test(event.details);
    }
  });
  chrome.send('setIncludeSpecifics', [false]);
  chrome.send('requestDataAndRegisterForUpdates');
  chrome.send('triggerRefresh');
  return true;
})()"""

_SNAPSHOT = r"""(async () => {
  const {aboutInfo} = await import('./about.js');
  const {sendWithPromise} = await import('chrome://resources/js/cr.js');
  const stats = Object.fromEntries((aboutInfo.details || []).flatMap(
    section => section.data.map(item => [item.stat_name, item.stat_value])));
  const rows = (aboutInfo.type_status || []).filter(row => row.status !== 'header');
  const active = rows.filter(row => row.state === 'Running');
  const good = {
    'Transport State': 'Active', 'User Actionable Error': 'None',
    'Sync Feature Enabled': true, 'Setup In Progress': false,
    'Sync First-Time Setup Complete': true, 'Sync Cycle Ongoing': false,
    'Throttled or Backoff': false, 'Cryptographer Ready To Encrypt': true,
    'Cryptographer Has Pending Keys': false, 'GetKey Step Failed': false,
    'Download Step Result': 'Success', 'Commit Step Result': 'Success'
  };
  const healthy = Object.entries(good).every(([key, value]) => stats[key] === value)
    && typeof stats['Server Connection'] === 'string' && stats['Server Connection'].startsWith('OK')
    && typeof stats['Auth Error'] === 'string' && stats['Auth Error'].startsWith('OK')
    && aboutInfo.actionable_error_detected === false
    && aboutInfo.unrecoverable_error_detected === false
    && ['Bookmarks', 'Passwords', 'Preferences', 'Extensions', 'Sessions'].every(
      name => active.some(row => row.name === name))
    && rows.every(row => row.status === 'ok' || (row.status === 'severity_info' && row.state === 'Not Running'));
  let pending = true;
  if (healthy) {
    const groups = await sendWithPromise('getAllNodes');
    // Counts also cover tombstones omitted by getAllNodes. A deletion must have
    // been acknowledged and removed from the native tracker before we succeed.
    const countsReady = active.every(row => Number.isInteger(row.num_entries)
      && Number.isInteger(row.num_live) && row.num_entries === row.num_live);
    const nodesReady = Array.isArray(groups) && active.every(row => groups.some(group =>
      group.type === row.name && Array.isArray(group.nodes)
        && group.nodes.filter(node => node.metadata).length === row.num_live))
      && groups.every(group =>
      Array.isArray(group.nodes) && group.nodes.every(node => {
        if (!node.metadata && node.PARENT_ID === 'r' && node.IS_DIR === true && group.type !== 'Nigori') return true;
        const metadata = node.metadata;
        if (!metadata) return false;
        const sequence = metadata.sequence_number;
        const acknowledged = metadata.acked_sequence_number;
        return /^\d+$/.test(String(sequence)) && /^\d+$/.test(String(acknowledged))
          && BigInt(sequence) === BigInt(acknowledged);
      }));
    pending = !countsReady || !nodesReady;
  }
  // A refresh requested before the engine initialized may have been ignored.
  // Retry once it becomes healthy, without accepting the previous session's status.
  if (healthy && !window.workstationSync.downloaded) chrome.send('triggerRefresh');
  chrome.send('requestDataAndRegisterForUpdates');
  return {healthy, pending, fresh: window.workstationSync.downloaded === true};
})()"""


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

    def __init__(self, pipe: BrowserPipe, profile_path: str) -> None:
        self.pipe = pipe
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

    def _evaluate(self, session: str, expression: str, operation: str, timeout: float = 30) -> object:
        """Identify the failed operation without exposing scripts, responses, or recovery words."""

        try:
            return self.pipe.evaluate(session, expression, timeout=timeout)
        except BrowserProtocolError as error:
            raise BrowserProtocolError(f"Brave Sync failed while {operation}: {error}") from error

    def _request(self, method: str, *arguments: object) -> object:
        encoded = ", ".join(json.dumps(value) for value in (method, *arguments))
        return self._evaluate(
            self.settings,
            f"window.workstationSyncSettings.sendWithPromise({encoded})",
            f"calling {method}",
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

    def restore(self, code: str, *, reset: bool = False) -> None:
        """Join an approved chain with Brave's current pairing suffix and verify it."""

        code = recovery_words(code)
        if reset and self._request("SyncSetupReset") is not True:
            raise BrowserProtocolError("Brave could not leave its previous Sync chain")
        pairing = self._request("SyncSetupGetSyncCode")
        if not isinstance(pairing, str) or len(pairing.split()) != 25:
            raise BrowserProtocolError("Brave could not generate the current pairing word")
        accepted = self._request("SyncSetupSetSyncCode", code + " " + pairing.split()[-1])
        if accepted is not True or self.code() != code:
            raise BrowserProtocolError("Brave did not join the selected recovery chain")
        # Joining resets Brave's selected types to its defaults. Restore explicitly
        # re-enables the full selection required by backup, through the native API.
        if self._evaluate(self.settings, _ENABLE_EVERYTHING, "enabling Sync everything") is not True:
            raise BrowserProtocolError("Brave did not enable Sync everything after joining the recovery chain")

    def wait(self, timeout: float = 120) -> bool:
        """Require a fresh successful download and two clean observations without pending changes."""

        session = self.pipe.page("brave://sync-internals")
        if self._evaluate(session, _START, "starting Sync diagnostics") is not True:
            raise BrowserProtocolError("Brave could not request a fresh Sync cycle")
        deadline = time.monotonic() + timeout
        clean = 0
        while time.monotonic() < deadline:
            snapshot = self._evaluate(
                session,
                _SNAPSHOT,
                "reading Sync diagnostics",
                timeout=min(30, max(1, deadline - time.monotonic())),
            )
            if not isinstance(snapshot, dict) or any(
                not isinstance(snapshot.get(key), bool) for key in ("healthy", "pending", "fresh")
            ):
                raise BrowserProtocolError("Brave returned unsupported Sync diagnostics")
            clean = clean + 1 if snapshot == {"healthy": True, "pending": False, "fresh": True} else 0
            if clean >= 2:
                return True
            time.sleep(min(2, max(0, deadline - time.monotonic())))
        return False
