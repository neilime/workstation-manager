#!/usr/bin/env python3
"""Exercise native Brave automation in a disposable Lima profile, without a remote chain."""

from __future__ import annotations

import json
import os
import platform
import re
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE / "ansible/collections"))

# pylint: disable=wrong-import-position
from ansible_collections.neilime.workstation_setup.plugins.module_utils import (  # noqa: E402
    browser_profile_preferences,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_cdp import (  # noqa: E402
    BrowserPipe,
    BrowserProtocolError,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_lifecycle import (  # noqa: E402
    browser_processes,
    closed_browser,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_native_sync import (  # noqa: E402
    _ENABLE_EVERYTHING,
    _SETTINGS_BRIDGE,
    _SNAPSHOT,
    _START,
    NativeSync,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_sync_devices import (  # noqa: E402
    _REMOVAL_BINDING,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desktop_session import (  # noqa: E402
    DesktopSession,
)
from browser_sync_fixture import (  # noqa: E402
    _LEAVE_DEVICE,
    _PROTOCOL_BINDING,
    _START_TEARDOWN,
    _TEARDOWN_CHECKS,
    _TEARDOWN_STATE,
    _WATCH_TEARDOWN_REMOVAL,
    BrowserSyncFixture,
    UnconfirmedDeviceRemoval,
    reset_device,
)
from browser_sync_removal_smoke import (  # noqa: E402
    device_removal_acknowledgement,
    device_removal_readback,
)

# pylint: enable=wrong-import-position

SMOKE_SCENARIOS = frozenset(
    {"native-api", "recovery-persistence", "profile-switching", "teardown-retry", "window-restoration"}
)


@contextmanager
def timed_scenario(name: str) -> Iterator[None]:
    """Report public scenario timings without exposing browser state or exceptions."""

    if name not in SMOKE_SCENARIOS:
        raise ValueError("Unsupported browser smoke timing scenario")
    started = time.monotonic()
    status = "failed"
    try:
        yield
        status = "passed"
    finally:
        elapsed = time.monotonic() - started
        print(f"E2E browser timing: scenario={name} elapsed={elapsed:.2f}s status={status}", flush=True)


def timing_lines(output: str) -> Iterator[str]:
    """Select only fixed scenario labels, numeric timings, and public status values."""

    for line in output.splitlines():
        match = re.fullmatch(
            r"E2E browser timing: scenario=([a-z-]+) elapsed=[0-9]+\.[0-9]{2}s status=(?:passed|failed)", line
        )
        if match and match.group(1) in SMOKE_SCENARIOS:
            yield line


def diagnostic_fixture() -> dict:
    """Supply synthetic diagnostics to the real WebUI runtime, never real user data."""

    stats = {
        "Transport State": "Active",
        "User Actionable Error": "None",
        "Sync Feature Enabled": True,
        "Setup In Progress": False,
        "Sync First-Time Setup Complete": True,
        "Sync Cycle Ongoing": False,
        "Throttled or Backoff": False,
        "Cryptographer Ready To Encrypt": True,
        "Cryptographer Has Pending Keys": False,
        "GetKey Step Failed": False,
        "Download Step Result": "Success",
        "Commit Step Result": "Success",
        "Server Connection": "OK",
        "Auth Error": "OK",
    }
    types = ["Bookmarks", "Passwords", "Preferences", "Extensions", "Sessions", "Device Info"]
    return {
        "about": {
            "details": [{"data": [{"stat_name": key, "stat_value": value} for key, value in stats.items()]}],
            "actionable_error_detected": False,
            "actionable_error": [],
            "unrecoverable_error_detected": False,
            "type_status": [
                {"name": name, "state": "Running", "status": "ok", "num_entries": 1, "num_live": 1} for name in types
            ],
        },
        "nodes": [
            {"type": name, "nodes": [{"metadata": {"sequence_number": "1", "acked_sequence_number": "1"}}]}
            for name in types
        ],
    }


def requested_page(pipe: BrowserPipe) -> None:
    """A loaded internal page cannot satisfy readiness for a different navigation."""

    existing = pipe.page("brave://version")
    assert pipe.evaluate(existing, "location.href === 'chrome://version/'") is True
    target = pipe.targets.pop()
    original_call = pipe.call
    navigated = False

    def call(method: str, params: dict | None = None, session: str | None = None, timeout: float = 30) -> dict:
        nonlocal navigated
        if method == "Target.createTarget":
            # Hold the requested navigation on an already-loaded internal page.
            return {"targetId": target}
        result = original_call(method, params, session, timeout)
        if method == "Runtime.evaluate" and not navigated and result.get("result", {}).get("value") is False:
            original_call("Page.navigate", {"url": "brave://sync-internals"}, session)
            navigated = True
        return result

    with patch.object(pipe, "call", side_effect=call):
        page = pipe.page("brave://sync-internals")
    assert navigated, "Readiness accepted a different internal page before navigation completed"
    assert pipe.evaluate(page, "location.href === 'chrome://sync-internals/'") is True
    print("Native page readiness waited for the requested navigation.", flush=True)


def delayed_profile_identity(pipe: BrowserPipe, profile_path: str) -> NativeSync:
    """Verify native identity even while the version page's displayed path is empty."""

    version = pipe.page("brave://version")
    assert (
        pipe.evaluate(
            version,
            """(() => {
      const path = document.querySelector('#profile_path');
      if (!path) return false;
      Object.defineProperty(path, 'textContent', {configurable: true, get: () => '', set: () => {}});
      window.fixtureProfileRequests = 0;
      window.fixtureSend = chrome.send;
      chrome.send = (method, args) => {
        if (method === 'requestPathInfo') {
          window.fixtureProfileRequests++;
          setTimeout(() => window.fixtureSend(method, args), 100);
        } else {
          window.fixtureSend(method, args);
        }
      };
      return true;
    })()""",
        )
        is True
    )
    original_page = pipe.page
    try:
        with patch.object(
            pipe, "page", side_effect=lambda url: version if url == "brave://version" else original_page(url)
        ):
            native = NativeSync(pipe, profile_path)
        assert pipe.evaluate(version, "window.fixtureProfileRequests === 1") is True
    finally:
        pipe.evaluate(
            version,
            "delete document.querySelector('#profile_path').textContent; chrome.send = window.fixtureSend; true",
        )
    print("Native profile identity verified despite delayed path delivery and an empty displayed path.", flush=True)
    return native


def snapshot(pipe: BrowserPipe, page: str, timeout_ms: int = 30000) -> dict:
    """Assert that diagnostic reduction returns structured, non-secret status."""

    result = pipe.evaluate(page, f"{_SNAPSHOT}({timeout_ms})", timeout=timeout_ms / 1000 + 5)
    assert isinstance(result, dict)
    return result


def retry_failed_download(pipe: BrowserPipe, page: str) -> None:
    """An active engine must retry a failed download before diagnostics can become healthy."""

    pipe.evaluate(
        page,
        """(() => {
      const aboutInfo = window.fixtureAbout;
      aboutInfo.type_status[0].status = 'ok';
      const download = aboutInfo.details.flatMap(section => section.data)
        .find(item => item.stat_name === 'Download Step Result');
      download.stat_value = 'Network error';
      window.workstationSync.downloaded = false;
      window.fixtureRefreshes = 0;
      const send = chrome.send;
      chrome.send = (method, args) => {
        if (method === 'triggerRefresh') window.fixtureRefreshes++;
        else send(method, args);
      };
      return true;
    })()""",
    )
    assert snapshot(pipe, page) == {"healthy": False, "pending": True, "fresh": False}
    assert pipe.evaluate(page, "window.fixtureRefreshes") == 1


def retry_pending_changes(pipe: BrowserPipe, page: str) -> None:
    """A completed download must not stop retries for uploads or deletion acknowledgements."""

    pipe.evaluate(
        page,
        """(() => {
      window.fixtureRefreshes = 0;
      const send = chrome.send;
      chrome.send = (method, args) => {
        if (method === 'triggerRefresh') window.fixtureRefreshes++;
        else send(method, args);
      };
      return true;
    })()""",
    )
    pipe.evaluate(page, "window.fixtureNodes[0].nodes[0].metadata.sequence_number = '2'; true")
    assert snapshot(pipe, page) == {"healthy": True, "pending": True, "fresh": True}
    assert pipe.evaluate(page, "window.workstationSync.checks['Entity Metadata']") is False
    assert pipe.evaluate(page, "window.fixtureRefreshes") == 1
    pipe.evaluate(page, "window.fixtureNodes[0].nodes[0].metadata.acked_sequence_number = '2'; true")
    tombstone = "window.fixtureAbout.type_status[0].num_entries = 2; true"
    pipe.evaluate(page, tombstone)
    assert snapshot(pipe, page)["pending"] is True
    assert pipe.evaluate(page, "window.workstationSync.checks['Entity Counts']") is False
    assert pipe.evaluate(page, "window.fixtureRefreshes") == 2
    pipe.evaluate(page, tombstone.replace("= 2", "= 1"))
    assert snapshot(pipe, page)["pending"] is False
    assert pipe.evaluate(page, "window.fixtureRefreshes") == 2


def retry_missing_nodes(pipe: BrowserPipe, page: str) -> None:
    """Missing node callbacks remain unverified; late replies cannot certify a later observation."""

    pipe.evaluate(
        page,
        """(() => {
      window.fixtureNodeSend = chrome.send;
      chrome.send = (method, args) => {
        if (method === 'getAllNodes') window.fixtureNodeRequest = args[0];
        else window.fixtureNodeSend(method, args);
      };
      return true;
    })()""",
    )
    for _ in range(2):
        assert snapshot(pipe, page, timeout_ms=50) == {"healthy": True, "pending": True, "fresh": True}
        assert pipe.evaluate(page, "window.workstationSync.checks['Entity Response']") is False
        # The timed-out request can still complete, but its result is no longer
        # evidence for this or the next observation.
        pipe.evaluate(
            page,
            """(async () => {
          const {webUIResponse} = await import('chrome://resources/js/cr.js');
          webUIResponse(window.fixtureNodeRequest, true, window.fixtureNodes);
          return true;
        })()""",
        )
        assert pipe.evaluate(page, "window.workstationSync.checks['Entity Response']") is False
    pipe.evaluate(page, "chrome.send = window.fixtureNodeSend; true")
    assert snapshot(pipe, page) == {"healthy": True, "pending": False, "fresh": True}
    assert pipe.evaluate(page, "window.workstationSync.checks['Entity Response']") is True

    pipe.evaluate(
        page,
        """(async () => {
      const {webUIResponse} = await import('chrome://resources/js/cr.js');
      chrome.send = (method, args) => {
        if (method === 'getAllNodes') webUIResponse(args[0], false, 'synthetic-private-error');
        else window.fixtureNodeSend(method, args);
      };
      return true;
    })()""",
    )
    try:
        snapshot(pipe, page)
    except BrowserProtocolError as error:
        assert "native Sync interface is unavailable" in str(error)
        assert "synthetic-private-error" not in str(error)
    else:
        raise AssertionError("A rejected native node request was incorrectly retried")
    finally:
        pipe.evaluate(page, "chrome.send = window.fixtureNodeSend; true")


def prepare_diagnostics(pipe: BrowserPipe, page: str) -> None:
    """Publish native status replacements before asynchronous per-type entity counts."""

    prepare = """(async () => {
      const {webUIListenerCallback, webUIResponse} = await import('chrome://resources/js/cr.js');
      const fixture = FIXTURE;
      window.fixtureAbout = fixture.about;
      window.fixtureNodes = fixture.nodes;
      window.fixturePublishAbout = source => {
        const about = structuredClone(source);
        for (const row of about.type_status) {
          delete row.num_entries;
          delete row.num_live;
        }
        webUIListenerCallback('onAboutInfoUpdated', about);
      };
      window.fixturePublishCounts = source => {
        for (const row of source.type_status) {
          webUIListenerCallback('onEntityCountsUpdated', {entityCounts: {
            dataType: row.name, entities: row.num_entries, nonTombstoneEntities: row.num_live
          }});
        }
      };
      chrome.send = (method, args) => {
        if (method === 'getAllNodes') webUIResponse(args[0], true, window.fixtureNodes);
        if (method === 'requestDataAndRegisterForUpdates') {
          const about = structuredClone(window.fixtureAbout);
          window.fixturePublishAbout(about);
          setTimeout(() => window.fixturePublishCounts(about), 0);
        }
      };
      return true;
    })()""".replace("FIXTURE", json.dumps(diagnostic_fixture()))
    assert pipe.evaluate(page, prepare) is True


def fresh_diagnostics(pipe: BrowserPipe, page: str) -> None:
    """Current native replies supersede cached busy and idle cycle states."""

    for current_busy in (False, True):
        pipe.evaluate(
            page,
            """(() => {
          const current = window.fixtureAbout.details.flatMap(section => section.data)
            .find(item => item.stat_name === 'Sync Cycle Ongoing');
          current.stat_value = CURRENT;
          const cached = structuredClone(window.fixtureAbout);
          cached.details.flatMap(section => section.data)
            .find(item => item.stat_name === 'Sync Cycle Ongoing').stat_value = !CURRENT;
          window.fixturePublishAbout(cached);
          window.fixturePublishCounts(cached);
          return true;
        })()""".replace("CURRENT", json.dumps(current_busy)),
        )
        assert snapshot(pipe, page) == {"healthy": not current_busy, "pending": current_busy, "fresh": True}
    pipe.evaluate(
        page,
        "window.fixtureAbout.details.flatMap(section => section.data)"
        ".find(item => item.stat_name === 'Sync Cycle Ongoing').stat_value = false; true",
    )
    assert snapshot(pipe, page) == {"healthy": True, "pending": False, "fresh": True}


def retry_missing_diagnostics(pipe: BrowserPipe, page: str) -> None:
    """Missing status or counts cannot reuse cached success or accept a timed-out callback."""

    for callback in ("About", "Counts"):
        pipe.evaluate(
            page,
            "window.fixturePublishHeld = window.fixturePublishCALLBACK; "
            "window.fixturePublishCALLBACK = () => {}; true".replace("CALLBACK", callback),
        )
        for _ in range(2):
            result = snapshot(pipe, page, timeout_ms=50)
            assert result == {"healthy": False, "pending": True, "fresh": True}
            assert pipe.evaluate(page, "window.workstationSync.checks['Entity Counts']") is False
            pipe.evaluate(page, "window.fixturePublishHeld(window.fixtureAbout); true")
            assert pipe.evaluate(page, "window.workstationSync.checks['Entity Counts']") is False
        pipe.evaluate(page, f"window.fixturePublish{callback} = window.fixturePublishHeld; true")
        assert snapshot(pipe, page) == {"healthy": True, "pending": False, "fresh": True}


def reject_replaced_diagnostics(pipe: BrowserPipe, page: str) -> None:
    """A new status during node aggregation invalidates the in-flight observation."""

    pipe.evaluate(
        page,
        """(() => {
      window.fixtureBeforeReplacement = chrome.send;
      chrome.send = (method, args) => {
        if (method === 'getAllNodes') {
          window.fixturePublishAbout(window.fixtureAbout);
          window.fixturePublishCounts(window.fixtureAbout);
        }
        window.fixtureBeforeReplacement(method, args);
      };
      return true;
    })()""",
    )
    try:
        result = snapshot(pipe, page)
        assert result == {"healthy": False, "pending": True, "fresh": True}
        assert pipe.evaluate(page, "window.workstationSync.checks['Status Response']") is False
    finally:
        pipe.evaluate(page, "chrome.send = window.fixtureBeforeReplacement; true")
    assert snapshot(pipe, page) == {"healthy": True, "pending": False, "fresh": True}


def diagnostics(pipe: BrowserPipe, page: str) -> None:
    """Run production JavaScript against stale, pending, errored, and complete native-shaped responses."""

    # Brave's page base can use its branded scheme while location.href remains
    # chrome:. Relative imports then fetch a brave: resource and reject with a
    # TypeError. Native resources must use their canonical chrome: addresses.
    assert (
        pipe.evaluate(
            page,
            """(() => {
          const base = document.createElement('base');
          base.href = 'brave://sync-internals/';
          document.head.prepend(base);
          return document.baseURI === 'brave://sync-internals/'
            && location.href === 'chrome://sync-internals/';
        })()""",
        )
        is True
    )
    pipe.evaluate(page, _START)
    assert snapshot(pipe, page) == {"healthy": False, "pending": True, "fresh": False}
    prepare_diagnostics(pipe, page)
    stale = snapshot(pipe, page)
    assert stale == {"healthy": True, "pending": False, "fresh": False}, stale
    assert pipe.evaluate(page, "window.workstationSync.checks['Fresh Download']") is False
    event = """(async () => {
      const {webUIListenerCallback} = await import('chrome://resources/js/cr.js');
      webUIListenerCallback('onProtocolEvent', {time: Date.now() OFFSET,
        type: 'GetUpdates Response', details: 'Received 0 update(s).'});
      return true;
    })()"""
    pipe.evaluate(page, event.replace("OFFSET", "- 10000"))
    assert snapshot(pipe, page)["fresh"] is False
    pipe.evaluate(page, event.replace("OFFSET", ""))
    assert snapshot(pipe, page) == {"healthy": True, "pending": False, "fresh": True}
    # A discarded/reloaded page loses its diagnostic state. Previously observed
    # success cannot certify the new context; it must request a fresh download.
    pipe.evaluate(page, "delete window.workstationSync; true")
    assert snapshot(pipe, page) == {"healthy": True, "pending": False, "fresh": False}
    pipe.evaluate(page, event.replace("OFFSET", ""))
    assert snapshot(pipe, page) == {"healthy": True, "pending": False, "fresh": True}
    assert pipe.evaluate(
        page,
        """(async () => {
      const {webUIListenerCallback} = await import('chrome://resources/js/cr.js');
      webUIListenerCallback('onProtocolEvent', {time: Date.now(), type: 'Commit Response', proto: {
        commit: {entryresponse: [{response_type: 'TRANSIENT_ERROR', error_message: 'private-data'},
          {response_type: 'private-error'}]}
      }});
      return window.workstationSync.commitErrors;
    })()""",
    ) == ["TRANSIENT_ERROR"]
    fresh_diagnostics(pipe, page)
    retry_missing_diagnostics(pipe, page)
    reject_replaced_diagnostics(pipe, page)
    retry_pending_changes(pipe, page)
    retry_missing_nodes(pipe, page)
    pipe.evaluate(page, "window.fixtureAbout.type_status[0].status = 'severity_error'; true")
    assert snapshot(pipe, page)["healthy"] is False
    assert pipe.evaluate(page, "window.workstationSync.checks['Data Type Status']") is False
    retry_failed_download(pipe, page)
    print(
        "Native diagnostics: canonical imports, fresh status/counts, stale busy/idle caches, "
        "pending upload/deletion, missing/late/rejected replies, status replacement, "
        "lost page state, redacted commit errors, failure, retry, and success passed.",
        flush=True,
    )


def navigate_teardown_page(pipe: BrowserPipe, page: str, url: str) -> None:
    """Wait for the owned diagnostic tab to finish its requested navigation."""

    pipe.call("Page.navigate", {"url": url}, page)
    deadline = time.monotonic() + 10
    while not pipe.evaluate(page, f"location.href === {json.dumps(url)} && document.readyState === 'complete'"):
        assert time.monotonic() < deadline, "Teardown diagnostic page did not finish navigation"
        time.sleep(0.1)


def fresh_teardown_diagnostics(pipe: BrowserPipe, page: str, readiness_snapshot: Callable[[], dict]) -> None:
    """Only fresh idle status with complete counts can authorize native leave."""

    for busy in (True, False):
        pipe.evaluate(
            page,
            "window.fixtureAbout.details[0].data.find(item => item.stat_name === 'Sync Cycle Ongoing')"
            f".stat_value = {json.dumps(busy)}; true",
        )
        assert readiness_snapshot()["ready"] is not busy
    pipe.evaluate(page, "window.fixtureHeldCounts = window.fixtureCounts; window.fixtureCounts = null; true")
    assert readiness_snapshot()["ready"] is False
    pipe.evaluate(page, "window.fixtureCounts = window.fixtureHeldCounts; true")
    assert readiness_snapshot()["ready"] is True


def teardown_readiness(pipe: BrowserPipe) -> None:
    """Native callbacks verify teardown, and lost pages request context recovery."""

    page = pipe.page("brave://version")

    def teardown_snapshot(identity: str = "captured-device") -> dict:
        result = pipe.evaluate(page, f"{_TEARDOWN_STATE}({json.dumps(identity)}, 50)")
        assert isinstance(result, dict)
        checks = result.pop("checks")
        assert set(checks) == set(_TEARDOWN_CHECKS)
        assert all(isinstance(value, bool) for value in checks.values())
        return result

    unavailable = {"active": False, "stopped": False, "ready": False, "matches": False, "needsNavigation": True}
    pending = {**unavailable, "needsNavigation": False}
    assert pipe.evaluate(page, _START_TEARDOWN) is False
    assert teardown_snapshot() == unavailable
    pipe.call("Network.enable", session=page)
    pipe.call(
        "Network.setBlockedURLs",
        {
            "urlPatterns": [
                {"urlPattern": "chrome://sync-internals/about.js", "block": True},
                {"urlPattern": "chrome://resources/js/cr.js", "block": True},
            ]
        },
        page,
    )
    navigate_teardown_page(pipe, page, "chrome://sync-internals/")
    for resource in ("chrome://sync-internals/about.js", "chrome://resources/js/cr.js"):
        assert pipe.evaluate(page, f"import({json.dumps(resource)}).then(() => false, () => true)") is True
    # Exercise the callback contract independently of the page's module loader.
    # Missing native callbacks must not certify readiness or request a refresh.
    pipe.evaluate(page, "delete window.cr; true")
    assert pipe.evaluate(page, _START_TEARDOWN) is False
    assert teardown_snapshot() == unavailable
    pipe.evaluate(
        page,
        """(() => {
          window.cr = {webUIResponse: () => {}, webUIListenerCallback: () => {}};
          window.fixtureRefreshes = 0;
          window.fixtureAbout = null;
          window.fixtureCounts = null;
          chrome.send = method => {
            if (method === 'getAllNodes') throw Error('Unexpected query');
            if (method === 'triggerRefresh') window.fixtureRefreshes++;
            if (method === 'requestDataAndRegisterForUpdates' && window.fixtureAbout) {
              cr.webUIListenerCallback('onAboutInfoUpdated', structuredClone(window.fixtureAbout));
              if (window.fixtureCounts) setTimeout(() =>
                cr.webUIListenerCallback('onEntityCountsUpdated', {entityCounts: window.fixtureCounts}), 0);
            }
          };
          return true;
        })()""",
    )
    pipe.evaluate(page, "Object.defineProperty(document, 'readyState', {value: 'loading', configurable: true}); true")
    assert teardown_snapshot() == pending
    assert pipe.evaluate(page, "!window.workstationSync && window.fixtureRefreshes === 0") is True
    pipe.evaluate(page, "delete document.readyState; true")
    assert pipe.evaluate(page, _START_TEARDOWN) is True
    assert teardown_snapshot() == pending
    about = diagnostic_fixture()["about"]
    about["details"][0]["data"].append({"stat_name": "Sync Client ID", "stat_value": "captured-device"})
    about["type_status"] = [{"name": "Device Info", "state": "Running", "status": "ok"}]
    pipe.evaluate(
        page,
        f"window.fixtureAbout = {json.dumps(about)}; true",
    )
    # Unrelated counts and stale downloads cannot certify the captured device.
    for data_type, entries, live, offset, ready in (
        ("Bookmarks", 1, 1, -10000, False),
        ("Device Info", 1, 1, -10000, False),
        ("Device Info", 2, 1, 0, False),
        ("Device Info", 1, 1, 0, True),
    ):
        pipe.evaluate(
            page,
            "(() => { const {webUIListenerCallback} = window.cr; "
            f"window.fixtureCounts = {{dataType: {json.dumps(data_type)}, "
            f"entities: {entries}, nonTombstoneEntities: {live}}}; "
            f"webUIListenerCallback('onProtocolEvent', {{time: Date.now() + {offset}, "
            "type: 'GetUpdates Response', details: 'Received 0 update(s).'}); return true; })()",
        )
        responding = data_type == "Device Info"
        assert teardown_snapshot() == {
            "active": responding,
            "stopped": False,
            "ready": ready,
            "matches": responding,
            "needsNavigation": False,
        }
    assert teardown_snapshot("another-device") == {
        "active": True,
        "stopped": False,
        "ready": True,
        "matches": False,
        "needsNavigation": False,
    }
    for state in ("Paused", "Disabled", "Active"):
        pipe.evaluate(
            page,
            "window.fixtureAbout.details[0].data.find(item => item.stat_name === 'Transport State')"
            f".stat_value = {json.dumps(state)}; true",
        )
        assert teardown_snapshot()["stopped"] is (state == "Disabled")
    fresh_teardown_diagnostics(pipe, page, teardown_snapshot)
    acknowledged = device_removal_acknowledgement(pipe, page)
    # A navigation discards all observer state. Recover the owned page and require
    # fresh evidence; a previously ready context must not authorize device removal.
    navigate_teardown_page(pipe, page, "about:blank")
    assert pipe.evaluate(page, _START_TEARDOWN) is False
    assert teardown_snapshot() == unavailable
    assert pipe.evaluate(page, "typeof window.workstationDeviceRemoval === 'undefined'") is True
    # Runtime bindings must be reinstalled in the replacement page context,
    # even though the JavaScript observer itself has been discarded.
    assert pipe.evaluate(page, f"typeof window[{json.dumps(_REMOVAL_BINDING)}] === 'function'") is True
    pipe.call("Runtime.removeBinding", {"name": _REMOVAL_BINDING}, page)
    assert acknowledged() is True
    pipe.call("Network.setBlockedURLs", {"urlPatterns": []}, page)
    navigate_teardown_page(pipe, page, "chrome://sync-internals/")
    # This short snapshot can remain pending or receive fresh Disabled status.
    # Both must recover the page without certifying an active device for removal.
    assert {**teardown_snapshot(), "stopped": False} == pending
    print(
        "Teardown retains confirmed removal across navigation, and recovers lost pages with fresh evidence.",
        flush=True,
    )


def native_fixture_leave(pipe: BrowserPipe) -> None:
    """Verify the leave target and observe deletion without scheduling competing downloads."""

    page = pipe.page("brave://version")
    pipe.evaluate(
        page,
        """(() => {
          window.fixtureDevices = [];
          window.fixtureResets = 0;
          window.fixtureRefreshes = 0;
          window.workstationDeviceRemoved = () => {};
          window.workstationSyncSettings = {
            addWebUiListener: () => {},
            sendWithPromise: method => {
              if (method === 'SyncGetDeviceList') return Promise.resolve(window.fixtureDevices);
              if (method !== 'SyncSetupReset') throw Error('Unexpected fixture method');
              window.fixtureResets++;
              return Promise.resolve(window.fixtureLeaveResult);
            }
          };
          chrome.send = method => {
            if (method === 'triggerRefresh') window.fixtureRefreshes++;
          };
          return true;
        })()""",
    )
    assert pipe.evaluate(page, f"{_WATCH_TEARDOWN_REMOVAL}(['captured-device'])") is True
    assert (
        pipe.evaluate(
            page,
            "new Promise(resolve => setTimeout(() => resolve(window.fixtureRefreshes), 200))",
        )
        == 0
    )
    for devices in (
        [],
        [{"guid": "another-device", "isCurrentDevice": True}],
        [{"guid": "captured-device", "isCurrentDevice": False}],
        [{"guid": "captured-device", "isCurrentDevice": True}] * 2,
    ):
        pipe.evaluate(page, f"window.fixtureDevices = {json.dumps(devices)}; true")
        assert pipe.evaluate(page, f"{_LEAVE_DEVICE}('captured-device')") is None
        assert pipe.evaluate(page, "window.fixtureResets") == 0
    for successful in (False, True):
        pipe.evaluate(
            page,
            "window.fixtureDevices = [{guid: 'captured-device', isCurrentDevice: true}]; "
            f"window.fixtureLeaveResult = {json.dumps(successful)}; true",
        )
        assert reset_device(pipe, page, "captured-device") is successful


def pending_chain(pipe: BrowserPipe, native: NativeSync) -> str:
    """Persist a generated code through the native API while the Sync endpoint is disabled."""

    pairing = pipe.evaluate(
        native.settings,
        "window.workstationSyncSettings.sendWithPromise('SyncSetupGetSyncCode')",
    )
    assert isinstance(pairing, str) and len(pairing.split()) == 25
    code = " ".join(pairing.split()[:24])
    # The offline join cannot acknowledge success. Start it without awaiting the
    # server, then prove the native encrypted code survives a normal restart.
    pipe.evaluate(
        native.settings,
        """(async () => {
      const {sendWithPromise} = window.workstationSyncSettings;
      void sendWithPromise('SyncSetupSetSyncCode', PAIRING).catch(() => {});
      return true;
    })()""".replace("PAIRING", json.dumps(pairing)),
    )
    deadline = time.monotonic() + 10
    while native.code() != code:
        assert time.monotonic() < deadline, "Native code was not saved"
        time.sleep(0.1)
    return code


def retry_native_fixture_leave(arguments: list[str], environment: dict[str, str], root: Path, code: str) -> None:
    """A destructive native reset in a copy leaves the original encrypted recovery state reusable."""

    fixture = BrowserSyncFixture(root, root / "fixture.json")
    attempts = []
    confirmed = []

    def reset_without_server_reply(pipe: BrowserPipe, profile: Path, identity: str, *, network) -> None:
        assert profile.parent != root
        native = NativeSync(pipe, str(profile))
        assert native.code() == code, "The copied profile could not decrypt the original recovery code"
        # This smoke chain is offline. Native reset still exercises destructive
        # local clearing without contacting any saved recovery chain.
        assert not network.released.is_set()
        diagnostic = pipe.page("brave://sync-internals")
        pipe.watch_acknowledgement(diagnostic, _PROTOCOL_BINDING)
        assert pipe.evaluate(diagnostic, _START_TEARDOWN) is True
        assert pipe.wait_for_acknowledgement(diagnostic, _PROTOCOL_BINDING) is True, (
            "Native protocol forwarding did not activate while server access was blocked"
        )
        assert (
            pipe.evaluate(native.settings, "window.workstationSyncSettings.sendWithPromise('SyncSetupReset')") is True
        )
        attempts.append(identity)
        if len(attempts) == 1:
            raise UnconfirmedDeviceRemoval("Simulated missing server acknowledgement")

    with patch("browser_sync_fixture.leave_device", side_effect=reset_without_server_reply):
        fixture.leave_captured_device(
            root / "Default", "captured-device", arguments[0], environment, lambda: confirmed.append(True)
        )
    assert attempts == ["captured-device", "captured-device"]
    assert confirmed == [True]
    assert not list(root.glob("browser-teardown-*")), "Private teardown copies were retained"
    with BrowserPipe(arguments, environment) as original:
        assert NativeSync(original, str(root / "Default")).code() == code, "The original recovery state changed"
    print("Native reset retries preserve original encrypted recovery state and remove private copies.", flush=True)


def settings_callbacks(pipe: BrowserPipe) -> None:
    """Route private requests without replacing the bundled page's own callbacks."""

    page = pipe.page("brave://version")
    pipe.evaluate(
        page,
        """(() => {
      window.fixtureResponses = [];
      window.fixtureEvents = [];
      window.fixtureRequests = [];
      window.cr = {
        webUIResponse: (...args) => window.fixtureResponses.push(args),
        webUIListenerCallback: (...args) => window.fixtureEvents.push(args)
      };
      chrome.send = (method, args) => {
        if (method === 'throw') throw new Error('synthetic-private-error');
        window.fixtureRequests.push([method, args]);
      };
      return true;
    })()""",
    )
    assert pipe.evaluate(page, _SETTINGS_BRIDGE) is True
    # Reusing an initialized page must retain pending requests and listeners.
    pipe.evaluate(page, "window.fixtureBridge = window.workstationSyncSettings; true")
    assert pipe.evaluate(page, _SETTINGS_BRIDGE) is True
    assert (
        pipe.evaluate(
            page,
            """(async () => {
      const bridge = window.workstationSyncSettings;
      if (bridge !== window.fixtureBridge) return false;
      const first = bridge.sendWithPromise('first', 'synthetic-argument');
      const second = bridge.sendWithPromise('second').catch(error => error.message);
      const [[method, [firstId, argument]], [, [secondId]]] = window.fixtureRequests;
      cr.webUIResponse('page-owned-request', true, 'page-owned-response');
      cr.webUIResponse(secondId, false, 'synthetic-private-rejection');
      cr.webUIResponse(firstId, true, 'synthetic-result');
      const thrown = await bridge.sendWithPromise('throw').catch(error => error.message);
      let observed = 0;
      const listener = bridge.addWebUiListener('fixture-event', value => { observed += value; });
      cr.webUIListenerCallback('other-event', 10);
      cr.webUIListenerCallback('fixture-event', 1);
      const removed = bridge.removeWebUiListener(listener);
      cr.webUIListenerCallback('fixture-event', 2);
      return method === 'first' && argument === 'synthetic-argument' && firstId !== secondId
        && await first === 'synthetic-result' && await second === 'Native Sync request rejected'
        && thrown === 'Native Sync request failed' && removed && observed === 1
        && JSON.stringify(window.fixtureResponses) ===
          JSON.stringify([['page-owned-request', true, 'page-owned-response']])
        && JSON.stringify(window.fixtureEvents) ===
          JSON.stringify([['other-event', 10], ['fixture-event', 1], ['fixture-event', 2]]);
    })()""",
        )
        is True
    )


def sync_selection(pipe: BrowserPipe, page: str) -> None:
    """Exercise the production selection code against native-shaped WebUI callbacks."""

    pipe.evaluate(
        page,
        """(() => {
      const {webUIListenerCallback, webUIResponse} = window.cr;
      window.fixturePrefs = {syncAllDataTypes: false, bookmarksSynced: true, preferencesSynced: false};
      chrome.send = (method, args) => {
        if (method === 'SyncPrefsDispatch')
          webUIListenerCallback('sync-prefs-changed', window.fixturePrefs);
        if (method === 'SyncSetupSetDatatypes') {
          window.fixturePrefs = JSON.parse(args[1]);
          webUIResponse(args[0], true, 'configure');
        }
      };
      return true;
    })()""",
    )
    assert pipe.evaluate(page, _ENABLE_EVERYTHING) is True
    assert pipe.evaluate(page, "window.fixturePrefs.syncAllDataTypes === true") is True


def restore_open_profiles(environment: dict[str, str]) -> None:
    """Reopen original profile windows after automation visits a different profile."""

    with tempfile.TemporaryDirectory(prefix="workstation-session-restore-") as directory:
        root = Path(directory)
        arguments = [
            "/usr/bin/brave-browser",
            "--remote-debugging-pipe",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={root}",
            "--restore-last-session",
            "--sync-url=http://127.0.0.1:1",
        ]
        for profile in ("Default", "Profile 2"):
            with BrowserPipe([*arguments, f"--profile-directory={profile}"], environment) as original:
                NativeSync(original, str(root / profile))
                original.call("Target.createTarget", {"url": "data:text/plain,original-profile"})
        # Reproduce an ordinary desktop session without an automation keepalive.
        desktop = [argument for argument in arguments if argument != "--remote-debugging-pipe"]
        for profile in ("Default", "Profile 2"):
            # The fixture browser outlives its launcher until closed_browser runs.
            # pylint: disable-next=consider-using-with
            launched = subprocess.Popen(
                [*desktop, f"--profile-directory={profile}", "--new-window", "data:text/plain,original-profile"],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                assert launched.wait(timeout=3) == 0
            except subprocess.TimeoutExpired:
                pass
        # The secondary launcher returns before its window finishes opening.
        time.sleep(3)
        with (
            closed_browser(str(root)),
            BrowserPipe([*arguments, "--profile-directory=Profile 3"], environment) as automated,
        ):
            NativeSync(automated, str(root / "Profile 3"))
        time.sleep(3)
        assert browser_processes(root), "Previous browser session was not reopened"
        for process in browser_processes(root):
            os.kill(process, signal.SIGINT)
        deadline = time.monotonic() + 30
        while browser_processes(root) and time.monotonic() < deadline:
            time.sleep(0.2)
        assert not browser_processes(root), "Fixture browser did not close"
        previous = json.loads((root / "Local State").read_text())["profile"]["last_active_profiles"]
        assert set(previous) == {"Default", "Profile 2"}, f"Previously open profiles were not restored: {previous}"
    print("Original profile windows restored; the temporary automation profile stayed closed.", flush=True)


def profile_preferences(pipe: BrowserPipe, native: NativeSync) -> None:
    """Exercise native visibility writes and readback without joining a real chain."""

    for choices in (
        {"bookmark_bar": "never", "confirm_close_tabs": False},
        {"bookmark_bar": "new_tab", "confirm_close_tabs": True},
        {"bookmark_bar": "always", "confirm_close_tabs": False},
    ):
        expected = json.dumps(browser_profile_preferences.native_profile_preferences(choices))
        result = pipe.evaluate(
            native.settings, f"{browser_profile_preferences.PROFILE_PREFERENCES_SCRIPT}({expected}, true)"
        )
        assert isinstance(result, dict)
        assert result["supported"] is True and result["matches"] is True
        native.profile_preferences(choices, restore=False)
    print("Per-profile bookmark-bar and close-tabs settings passed native readback.", flush=True)


def main() -> None:
    """Run only inside Lima, preserving a synthetic tab across automation restarts."""

    if not platform.node().startswith("lima-"):
        raise SystemExit("Run this smoke test inside the Lima VM, never against a workstation browser.")
    with tempfile.TemporaryDirectory(prefix="workstation-browser-smoke-") as directory:
        arguments = [
            "/usr/bin/brave-browser",
            "--remote-debugging-pipe",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={directory}",
            "--profile-directory=Default",
            "--restore-last-session",
            "--sync-url=http://127.0.0.1:1",
        ]
        environment = DesktopSession.environment()
        with timed_scenario("native-api"), BrowserPipe(arguments, environment) as pipe:
            requested_page(pipe)
            native = delayed_profile_identity(pipe, directory + "/Default")
            assert len(native.code().split()) == 24
            settings_callbacks(pipe)
            pipe.call("Target.createTarget", {"url": "data:text/plain,workstation-session-fixture"})
            diagnostics(pipe, pipe.page("brave://sync-internals"))
            teardown_readiness(pipe)
            device_removal_readback(pipe)
            native_fixture_leave(pipe)
            code = pending_chain(pipe, native)
            sync_selection(pipe, native.settings)
            profile_preferences(pipe, native)
        with timed_scenario("recovery-persistence"), BrowserPipe(arguments, environment) as pipe:
            native = NativeSync(pipe, directory + "/Default")
            assert native.code() == code, "Native code could not be decrypted after restarting"
            native.profile_preferences({"bookmark_bar": "always", "confirm_close_tabs": False}, restore=False)
            assert native.wait(timeout=2) is False, "Offline Sync was incorrectly verified"
            targets = pipe.call("Target.getTargets")["targetInfos"]
            assert any(target["url"] == "data:text/plain,workstation-session-fixture" for target in targets), (
                "Previous session tab was not restored"
            )
        with timed_scenario("profile-switching"):
            for profile in ("Profile 2", "Default"):
                selected = [argument for argument in arguments if not argument.startswith("--profile-directory=")]
                with BrowserPipe([*selected, f"--profile-directory={profile}"], environment) as pipe:
                    NativeSync(pipe, directory + "/" + profile)
        with timed_scenario("teardown-retry"):
            retry_native_fixture_leave(arguments, environment, Path(directory), code)
            assert not (Path(directory) / "SingletonLock").exists()
    with timed_scenario("window-restoration"):
        restore_open_profiles(environment)
    print(
        "Encrypted code persistence, offline rejection, Sync selection, "
        "profile identity, session preservation, and cleanup passed.",
        flush=True,
    )


if __name__ == "__main__":
    main()
