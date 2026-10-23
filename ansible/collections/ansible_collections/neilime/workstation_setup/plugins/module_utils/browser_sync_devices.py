"""Plan exact-name device cleanup and observe native server deletion acknowledgements."""

from __future__ import annotations

import json

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_cdp import (
    BrowserProtocolError,
)


def disposable_device_names(value: object) -> list[str]:
    """Require explicit, nonempty exact names; never interpret patterns."""

    if not isinstance(value, list) or any(
        not isinstance(name, str) or not name.strip() or name != name.strip() or not name.isprintable()
        for name in value
    ):
        raise ValueError("Browser disposable device names must be a list of nonempty exact names")
    return list(dict.fromkeys(value))


class SyncDeviceList:
    """Validate a complete native list before identifying dispensable remote registrations."""

    def __init__(self, value: object) -> None:
        if not isinstance(value, list) or not value:
            raise BrowserProtocolError("Brave returned an unavailable Sync device list")
        self.devices: dict[str, dict] = {}
        for device in value:
            if not isinstance(device, dict):
                raise BrowserProtocolError("Brave returned an unsupported Sync device list")
            if (
                any(not isinstance(device.get(key), str) or not device[key].strip() for key in ("guid", "name"))
                or not isinstance(device.get("isCurrentDevice"), bool)
                or device["guid"] in self.devices
            ):
                raise BrowserProtocolError("Brave returned an unsupported Sync device list")
            self.devices[device["guid"]] = {key: device[key] for key in ("guid", "name", "isCurrentDevice")}
        current = [device for device in self.devices.values() if device["isCurrentDevice"]]
        if len(current) != 1:
            raise BrowserProtocolError("Brave could not identify exactly one current Sync device")
        self.current = current[0]

    def removal_ids(self, disposable_names: list[str]) -> list[str]:
        """Keep This Device, selecting only its exact-name duplicates and declared disposable names."""

        names = {self.current["name"], *disposable_device_names(disposable_names)}
        return [
            guid for guid, device in self.devices.items() if not device["isCurrentDevice"] and device["name"] in names
        ]

    def verify_cleanup(self, before: SyncDeviceList, disposable_names: list[str]) -> None:
        """Require the same active identity and absence of every selected remote registration."""

        if (
            self.current != before.current
            or any(identity in self.devices for identity in before.removal_ids(disposable_names))
            or self.removal_ids(disposable_names)
        ):
            raise BrowserProtocolError("Brave's Sync device cleanup verification failed")


_REMOVAL_BINDING = "workstationDeviceRemoved"
_REMOVAL_CHECKS = (
    "Commit Request",
    "Device Tombstone",
    "Commit Response",
    "Matching Response",
    "Server Acknowledgement",
)


# Device payloads and server IDs stay inside the diagnostic page. Only fixed
# boolean checks cross the pipe. A native leave callback alone can
# succeed after its short upload deadline even when deletion was not committed.
_WATCH_REMOVAL = r"""(async (identities, readBack = false, binding = REMOVAL_BINDING) => {
  const {addWebUiListener, removeWebUiListener} = window.workstationSyncSettings;
  if (!Array.isArray(identities) || !identities.length
    || identities.some(identity => typeof identity !== 'string' || !identity)
    || typeof binding !== 'string' || !binding || typeof window[binding] !== 'function') return false;
  const previous = window.workstationDeviceRemoval;
  if (previous) {
    clearInterval(previous.timer);
    if (previous.listener !== undefined) removeWebUiListener(previous.listener);
  }
  // Chromium's ClientTagHash hashes the empty DeviceInfoSpecifics field
  // (EntitySpecifics field 154522, length-delimited) followed by DeviceInfo_<GUID>.
  // Tombstone commits retain this tag, so no all-data node query is needed.
  const tags = new Set(await Promise.all(identities.map(async identity => {
    const input = new Uint8Array([
      0xd2, 0xb9, 0x4b, 0x00, ...new TextEncoder().encode('DeviceInfo_' + identity)
    ]);
    const digest = await crypto.subtle.digest('SHA-1', input);
    return btoa(String.fromCharCode(...new Uint8Array(digest)));
  })));
  const remaining = new Set(tags);
  const state = window.workstationDeviceRemoval = {
    since: Date.now(), requested: [], acknowledged: false,
    checks: Object.fromEntries(CHECK_NAMES.map(name => [name, false]))
  };
  const acknowledge = () => {
    state.acknowledged = remaining.size === 0;
    state.checks['Server Acknowledgement'] = state.acknowledged;
    if (state.acknowledged) {
      clearInterval(state.timer);
      window[binding]('true');
    }
  };
  state.listener = addWebUiListener('onProtocolEvent', event => {
    if (state.acknowledged || !Number.isFinite(event.time) || event.time < state.since) return;
    if (readBack === true && event.type === 'GetUpdates Response'
      && event.proto?.error_code === 'SUCCESS') {
      const details = /^Received ([1-9]\d*) update\(s\)\.(?: Some updates remain\.)?$/.exec(event.details);
      const entries = event.proto.get_updates?.entries;
      // A retried leave can download its already-committed tombstone before
      // Sync disables itself. Only fresh successful native server responses
      // for the exact captured GUID prove deletion; inactivity never does.
      if (details && Array.isArray(entries) && entries.length === Number(details[1])) {
        for (const entry of entries) {
          if (entry && remaining.has(entry.client_tag_hash) && entry.deleted === true
            && typeof entry.id_string === 'string' && entry.id_string
            && typeof entry.version === 'string' && /^[1-9]\d*$/.test(entry.version)) {
            state.checks['Device Tombstone'] = true;
            remaining.delete(entry.client_tag_hash);
          }
        }
        acknowledge();
      }
    }
    if (event.type === 'Commit Request') {
      state.checks['Commit Request'] = true;
      const entries = event.proto?.commit?.entries;
      state.requested = Array.isArray(entries) ? entries.map(entry =>
        remaining.has(entry.client_tag_hash) && entry.deleted === true
          && typeof entry.id_string === 'string' && entry.id_string ? entry.client_tag_hash : null) : [];
      if (state.requested.some(tag => tag !== null)) state.checks['Device Tombstone'] = true;
    }
    if (event.type === 'Commit Response') state.checks['Commit Response'] = true;
    if (event.type === 'Commit Response' && state.requested.length) {
      const entries = event.proto?.commit?.entryresponse;
      // Sync correlates responses by request position. Response IDs are optional
      // and may be reassigned; require the complete batch before matching it.
      if (Array.isArray(entries) && entries.length === state.requested.length) {
        if (state.requested.some(tag => tag !== null)) state.checks['Matching Response'] = true;
        entries.forEach((entry, index) => {
          if (entry.response_type === 'SUCCESS') remaining.delete(state.requested[index]);
        });
      }
      state.requested = [];
      acknowledge();
    }
  });
  chrome.send('setIncludeSpecifics', [false]);
  chrome.send('requestDataAndRegisterForUpdates');
  // Native refresh schedules commit work as well as downloads. Keep prompting
  // it while the leave handler waits, before that handler stops the Sync engine.
  state.timer = setInterval(() => chrome.send('triggerRefresh'), 100);
  return true;
})""".replace("REMOVAL_BINDING", json.dumps(_REMOVAL_BINDING)).replace("CHECK_NAMES", json.dumps(_REMOVAL_CHECKS))
