#!/usr/bin/env python3
"""Exercise native Brave automation in a disposable Lima profile, without a remote chain."""

from __future__ import annotations

import json
import os
import platform
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE / "ansible/collections"))

# pylint: disable=wrong-import-position
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
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desktop_session import (  # noqa: E402
    DesktopSession,
)
from browser_sync_fixture import _WATCH_REMOVAL  # noqa: E402

# pylint: enable=wrong-import-position


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
    types = ["Bookmarks", "Passwords", "Preferences", "Extensions", "Sessions"]
    return {
        "about": {
            "details": [{"data": [{"stat_name": key, "stat_value": value} for key, value in stats.items()]}],
            "actionable_error_detected": False,
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


def snapshot(pipe: BrowserPipe, page: str, timeout_ms: int = 30000) -> dict:
    """Assert that diagnostic reduction returns structured, non-secret status."""

    result = pipe.evaluate(page, f"{_SNAPSHOT}({timeout_ms})", timeout=timeout_ms / 1000 + 5)
    assert isinstance(result, dict)
    return result


def retry_failed_download(pipe: BrowserPipe, page: str) -> None:
    """An active engine must retry a failed download before diagnostics can become healthy."""

    pipe.evaluate(
        page,
        """(async () => {
      const {aboutInfo} = await import('./about.js');
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
    tombstone = (
        "(async()=>{const {aboutInfo} = await import('./about.js'); "
        "aboutInfo.type_status[0].num_entries = 2; return true;})()"
    )
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


def diagnostics(pipe: BrowserPipe, page: str) -> None:
    """Run production JavaScript against stale, pending, errored, and complete native-shaped responses."""

    pipe.evaluate(page, _START)
    assert snapshot(pipe, page) == {"healthy": False, "pending": True, "fresh": False}
    fixture = diagnostic_fixture()
    prepare = """(async () => {
      const {aboutInfo} = await import('./about.js');
      const {webUIResponse} = await import('chrome://resources/js/cr.js');
      const fixture = FIXTURE;
      Object.assign(aboutInfo, fixture.about);
      window.fixtureNodes = fixture.nodes;
      chrome.send = (method, args) => {
        if (method === 'getAllNodes') webUIResponse(args[0], true, window.fixtureNodes);
      };
      return true;
    })()""".replace("FIXTURE", json.dumps(fixture))
    assert pipe.evaluate(page, prepare) is True
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
    retry_pending_changes(pipe, page)
    retry_missing_nodes(pipe, page)
    pipe.evaluate(
        page,
        "(async()=>{const {aboutInfo} = await import('./about.js'); "
        "aboutInfo.type_status[0].status = 'severity_error'; return true;})()",
    )
    assert snapshot(pipe, page)["healthy"] is False
    assert pipe.evaluate(page, "window.workstationSync.checks['Data Type Status']") is False
    retry_failed_download(pipe, page)
    print(
        "Native diagnostics: stale success, pending upload/deletion, missing/late/rejected node replies, "
        "lost page state, redacted commit errors, failure, retry, and success passed.",
        flush=True,
    )
    device_removal_acknowledgement(pipe, page)


def device_removal_acknowledgement(pipe: BrowserPipe, page: str) -> None:
    """Only a fresh successful commit for the captured device proves server removal."""

    pipe.evaluate(
        page,
        """(() => {
          window.fixtureNodes = [{type: 'Device Info', nodes: [{
            SPECIFICS: {device_info: {cache_guid: 'captured-device'}},
            metadata: {server_id: 'captured-server-id'}
          }]}];
          window.fixtureRefreshes = 0;
          return true;
        })()""",
    )
    assert pipe.evaluate(page, f"{_WATCH_REMOVAL}('another-device')") is False
    assert pipe.evaluate(page, f"{_WATCH_REMOVAL}('captured-device')") is True
    # Exercise the actual interval which prompts uploads during native leave.
    assert (
        pipe.evaluate(
            page,
            "new Promise(resolve => setTimeout(() => resolve(window.fixtureRefreshes > 0), 200))",
        )
        is True
    )
    cases = [
        # Stale responses, updates, other devices, and failed commits do not prove deletion.
        ("captured-server-id", True, "captured-server-id", "SUCCESS", -10000, False),
        ("captured-server-id", False, "captured-server-id", "SUCCESS", 0, False),
        ("another-server-id", True, "another-server-id", "SUCCESS", 0, False),
        ("captured-server-id", True, "captured-server-id", "TRANSIENT_ERROR", 0, False),
        ("captured-server-id", True, "another-server-id", "SUCCESS", 0, False),
        ("captured-server-id", True, "captured-server-id", "SUCCESS", 0, True),
    ]
    for request_id, deleted, response_id, response_type, offset, expected in cases:
        event = {
            "request": {"commit": {"entries": [{"id_string": request_id, "deleted": deleted}]}},
            "response": {"commit": {"entryresponse": [{"id_string": response_id, "response_type": response_type}]}},
        }
        result = pipe.evaluate(
            page,
            """(async () => {
              const {webUIListenerCallback} = await import('chrome://resources/js/cr.js');
              const fixture = FIXTURE;
              const time = Date.now() + OFFSET;
              webUIListenerCallback('onProtocolEvent', {time, type: 'Commit Request', proto: fixture.request});
              webUIListenerCallback('onProtocolEvent', {time, type: 'Commit Response', proto: fixture.response});
              return window.workstationDeviceRemoval.acknowledged;
            })()""".replace("FIXTURE", json.dumps(event)).replace("OFFSET", str(offset)),
        )
        assert result is expected
    pipe.evaluate(page, "clearInterval(window.workstationDeviceRemoval.timer); true")
    print("Device removal requires a fresh successful server commit for its captured identity.", flush=True)


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
        with closed_browser(str(root)):
            with BrowserPipe([*arguments, "--profile-directory=Profile 3"], environment) as automated:
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
        with BrowserPipe(arguments, environment) as pipe:
            requested_page(pipe)
            native = NativeSync(pipe, directory + "/Default")
            assert len(native.code().split()) == 24
            settings_callbacks(pipe)
            pipe.call("Target.createTarget", {"url": "data:text/plain,workstation-session-fixture"})
            diagnostics(pipe, pipe.page("brave://sync-internals"))
            code = pending_chain(pipe, native)
            sync_selection(pipe, native.settings)
        with BrowserPipe(arguments, environment) as pipe:
            native = NativeSync(pipe, directory + "/Default")
            assert native.code() == code, "Native code could not be decrypted after restarting"
            assert native.wait(timeout=2) is False, "Offline Sync was incorrectly verified"
            targets = pipe.call("Target.getTargets")["targetInfos"]
            assert any(target["url"] == "data:text/plain,workstation-session-fixture" for target in targets), (
                "Previous session tab was not restored"
            )
        for profile in ("Profile 2", "Default"):
            selected = [argument for argument in arguments if not argument.startswith("--profile-directory=")]
            with BrowserPipe([*selected, f"--profile-directory={profile}"], environment) as pipe:
                NativeSync(pipe, directory + "/" + profile)
        assert not (Path(directory) / "SingletonLock").exists()
    restore_open_profiles(environment)
    print(
        "Encrypted code persistence, offline rejection, Sync selection, "
        "profile identity, session preservation, and cleanup passed.",
        flush=True,
    )


if __name__ == "__main__":
    main()
