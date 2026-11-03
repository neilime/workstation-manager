"""Exercise native Sync diagnostic polling against synthetic WebUI responses."""

from __future__ import annotations

import json

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_cdp import (
    BrowserPipe,
    BrowserProtocolError,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_native_sync import (
    _DIAGNOSTIC_TYPES,
    _SNAPSHOT,
    _START,
)


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


def snapshot(pipe: BrowserPipe, page: str, timeout_ms: int = 30000) -> dict:
    """Assert that diagnostic reduction returns structured, non-secret status."""

    result = pipe.evaluate(page, f"{_SNAPSHOT}({timeout_ms})", timeout=timeout_ms / 1000 + 5)
    assert isinstance(result, dict)
    return result


def retry_failed_cycles(pipe: BrowserPipe, page: str) -> None:
    """An active engine retries download and commit failures, including after a fresh download."""

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
    pipe.evaluate(
        page,
        """(() => {
          const stats = window.fixtureAbout.details.flatMap(section => section.data);
          stats.find(item => item.stat_name === 'Download Step Result').stat_value = 'Success';
          stats.find(item => item.stat_name === 'Commit Step Result').stat_value = 'Network error';
          window.workstationSync.downloaded = true;
          return true;
        })()""",
    )
    assert snapshot(pipe, page) == {"healthy": False, "pending": True, "fresh": True}
    assert pipe.evaluate(page, "window.fixtureRefreshes") == 2


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


def entity_coverage_diagnostics(pipe: BrowserPipe, page: str) -> None:
    """Coverage gaps retain useful counts across busy or replaced status without triggering new cycles."""

    refreshes = pipe.evaluate(page, "window.fixtureRefreshes")
    pipe.evaluate(
        page, "window.fixtureHeldNodes = window.fixtureNodes[0].nodes; window.fixtureNodes[0].nodes = []; true"
    )
    assert snapshot(pipe, page) == {"healthy": True, "pending": True, "fresh": True}
    missing = [{"type": _DIAGNOSTIC_TYPES.index("Bookmarks"), "live": 1, "nodes": 0}]
    assert pipe.evaluate(page, "window.workstationSync.entityCoverage") == missing
    assert pipe.evaluate(page, "window.fixtureRefreshes") == refreshes
    busy = (
        "window.fixtureAbout.details.flatMap(section => section.data)"
        ".find(item => item.stat_name === 'Sync Cycle Ongoing').stat_value = true; true"
    )
    pipe.evaluate(page, busy)
    assert snapshot(pipe, page) == {"healthy": False, "pending": True, "fresh": True}
    assert pipe.evaluate(page, "window.workstationSync.entityCoverage") == missing
    assert pipe.evaluate(page, "window.fixtureRefreshes") == refreshes
    pipe.evaluate(page, busy.replace("= true", "= false"))
    pipe.evaluate(
        page,
        "window.fixtureNodes[0].nodes = window.fixtureHeldNodes; "
        "window.fixtureHeldGroup = window.fixtureNodes.pop(); true",
    )
    assert snapshot(pipe, page)["pending"] is True
    assert pipe.evaluate(page, "window.workstationSync.entityCoverage") == [
        {"type": _DIAGNOSTIC_TYPES.index("Device Info"), "live": 1, "nodes": -1}
    ]
    pipe.evaluate(page, "window.fixtureNodes.push(window.fixtureHeldGroup); true")
    pipe.evaluate(
        page,
        """(() => {
          const send = chrome.send;
          window.fixtureCoverageSend = send;
          chrome.send = (method, args) => {
            if (method === 'getAllNodes') window.fixturePublishAbout(window.fixtureAbout);
            send(method, args);
          };
          return true;
        })()""",
    )
    assert snapshot(pipe, page) == {"healthy": False, "pending": True, "fresh": True}
    assert pipe.evaluate(page, "window.workstationSync.entityCoverage") == [
        {"type": _DIAGNOSTIC_TYPES.index("Device Info"), "live": 1, "nodes": -1}
    ]
    pipe.evaluate(page, "chrome.send = window.fixtureCoverageSend; true")
    assert snapshot(pipe, page)["pending"] is False
    assert pipe.evaluate(page, "window.workstationSync.entityCoverage") == []


def session_export_coverage(pipe: BrowserPipe, page: str) -> None:
    """Sessions may omit unmapped tabs, but missing responses and pending changes still fail."""

    pipe.evaluate(
        page,
        """(() => {
          window.fixtureSessions = window.fixtureNodes.find(group => group.type === 'Sessions');
          window.fixtureSessionCounts = window.fixtureAbout.type_status.find(row => row.name === 'Sessions');
          window.fixtureSessionCounts.num_entries = window.fixtureSessionCounts.num_live = 3;
          return true;
        })()""",
    )
    assert snapshot(pipe, page) == {"healthy": True, "pending": False, "fresh": True}
    assert pipe.evaluate(page, "window.workstationSync.entityCoverage") == []
    pipe.evaluate(page, "window.fixtureSessions.nodes[0].metadata.sequence_number = '2'; true")
    assert snapshot(pipe, page)["pending"] is True
    assert pipe.evaluate(page, "window.workstationSync.checks['Entity Metadata']") is False
    pipe.evaluate(page, "window.fixtureSessions.nodes[0].metadata.acked_sequence_number = '2'; true")
    pipe.evaluate(page, "window.fixtureSessionCounts.num_entries = 4; true")
    assert snapshot(pipe, page)["pending"] is True
    assert pipe.evaluate(page, "window.workstationSync.checks['Entity Counts']") is False
    pipe.evaluate(page, "window.fixtureSessionCounts.num_entries = 3; true")
    # A gap cannot excuse an absent, empty, duplicated, or oversized export.
    for change, restore in (
        ("window.fixtureSessions.type = 'Missing'", "window.fixtureSessions.type = 'Sessions'"),
        (
            "window.fixtureSessionNodes = window.fixtureSessions.nodes; window.fixtureSessions.nodes = []",
            "window.fixtureSessions.nodes = window.fixtureSessionNodes",
        ),
        ("window.fixtureNodes.push(window.fixtureSessions)", "window.fixtureNodes.pop()"),
        (
            "window.fixtureSessionCounts.num_entries = window.fixtureSessionCounts.num_live = 0",
            "window.fixtureSessionCounts.num_entries = window.fixtureSessionCounts.num_live = 3",
        ),
    ):
        pipe.evaluate(page, change + "; true")
        assert snapshot(pipe, page)["pending"] is True
        assert pipe.evaluate(page, "window.workstationSync.checks['Entity Coverage']") is False
        pipe.evaluate(page, restore + "; true")
    pipe.evaluate(page, "window.fixtureSessionCounts.num_entries = window.fixtureSessionCounts.num_live = 1; true")
    assert snapshot(pipe, page)["pending"] is False


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
    entity_coverage_diagnostics(pipe, page)
    session_export_coverage(pipe, page)
    pipe.evaluate(page, "window.fixtureAbout.type_status[0].status = 'severity_error'; true")
    assert snapshot(pipe, page)["healthy"] is False
    assert pipe.evaluate(page, "window.workstationSync.checks['Data Type Status']") is False
    retry_failed_cycles(pipe, page)
    print(
        "Native diagnostics: canonical imports, fresh status/counts, stale busy/idle caches, "
        "pending upload/deletion, partial Sessions export, missing/late/rejected replies, status replacement, "
        "lost page state, redacted commit errors, failure, retry, and success passed.",
        flush=True,
    )
