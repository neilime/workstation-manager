"""Prototype fresh download checkpoints; local data readback remains mandatory."""

from __future__ import annotations

import time
from collections.abc import Callable

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser.cdp import (
    BrowserPipe,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser.sync.checkpoint import (
    DOWNLOAD_OBSERVER,
    READ_DOWNLOAD_EVENTS,
    DownloadCheckpoint,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser.sync.native import (
    _GET_ABOUT,
    _SETTINGS_BRIDGE,
)

_OBSERVE = (
    "(async () => { if (!"
    + _SETTINGS_BRIDGE
    + ") return false; const ready = "
    + DOWNLOAD_OBSERVER
    + "; chrome.send('setIncludeSpecifics', [false]); chrome.send('requestDataAndRegisterForUpdates');"
    + " chrome.send('triggerRefresh'); return ready; })()"
)
_READ = READ_DOWNLOAD_EVENTS


_HEALTH = r"""(async () => {
  const response = await GET_ABOUT(1000, window.workstationSyncSettings);
  const about = response?.info;
  const stats = Object.fromEntries((about?.details || []).flatMap(
    section => section.data.map(item => [item.stat_name, item.stat_value])));
  const expected = {
    'Transport State': 'Active', 'Setup In Progress': false,
    'Sync First-Time Setup Complete': true, 'Sync Feature Enabled': true,
    'Cryptographer Ready To Encrypt': true, 'Cryptographer Has Pending Keys': false,
    'GetKey Step Failed': false, 'Throttled or Backoff': false,
    'Download Step Result': 'Success', 'Commit Step Result': 'Success'
  };
  const healthy = Object.entries(expected).every(([name, value]) => stats[name] === value)
    && ['Server Connection', 'Auth Error'].every(name => stats[name]?.startsWith('OK'))
    && about?.actionable_error_detected === false && about?.unrecoverable_error_detected === false
    && ['Bookmarks', 'Preferences'].every(name => response.rows.some(
      row => row.name === name && row.state === 'Running' && row.status === 'ok'));
  return {healthy, busy: stats['Sync Cycle Ongoing'] === true};
})()""".replace("GET_ABOUT", _GET_ABOUT)


class CheckpointProbe:
    """Exercise download evidence plus independent fixture readback inside a test VM."""

    def __init__(self, pipe: BrowserPipe, expected_types: list[int]) -> None:
        self.pipe = pipe
        self.checkpoint = DownloadCheckpoint(expected_types)
        self.page = pipe.page("brave://sync-internals")
        self.busy_observed = False
        self.busy_at_success = False
        self.healthy = False
        self.data_present = False
        if pipe.evaluate(self.page, _OBSERVE) is not True:
            raise ValueError("Checkpoint observer is unavailable")

    def wait(
        self,
        matches: Callable[[], bool],
        *,
        timeout: float,
        activity: Callable[[], None] | None = None,
    ) -> bool:
        """Require both fresh downloads and real fixture data while background Sync may run."""

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            packet = self.pipe.evaluate(self.page, _READ, timeout=5)
            self.checkpoint.consume(packet)
            status = self.pipe.evaluate(self.page, _HEALTH, timeout=5)
            if (
                not isinstance(status, dict)
                or set(status) != {"healthy", "busy"}
                or any(not isinstance(value, bool) for value in status.values())
            ):
                raise ValueError("Unsupported checkpoint health diagnostics")
            self.busy_observed |= status["busy"]
            self.healthy = status["healthy"]
            self.data_present = matches()
            if self.checkpoint.complete and self.healthy and self.data_present:
                self.busy_at_success = status["busy"]
                return True
            if activity is not None:
                activity()
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        return False

    def summary(self) -> str:
        """Report only fixed boolean evidence stages when the live experiment fails."""

        return (
            f"downloads={self.checkpoint.complete}, native_health={self.healthy}, "
            f"data_present={self.data_present}, busy_observed={self.busy_observed}"
        )
