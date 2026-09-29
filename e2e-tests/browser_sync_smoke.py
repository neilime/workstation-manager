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

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE / "ansible/collections"))

# pylint: disable=wrong-import-position
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_cdp import (  # noqa: E402
    BrowserPipe,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_lifecycle import (  # noqa: E402
    browser_environment,
    browser_processes,
    closed_browser,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_native_sync import (  # noqa: E402
    _ENABLE_EVERYTHING,
    _SNAPSHOT,
    _START,
    NativeSync,
)

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


def snapshot(pipe: BrowserPipe, page: str) -> dict:
    """Assert that diagnostic reduction returns structured, non-secret status."""

    result = pipe.evaluate(page, _SNAPSHOT)
    assert isinstance(result, dict)
    return result


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
    pipe.evaluate(page, "window.fixtureNodes[0].nodes[0].metadata.sequence_number = '2'; true")
    assert snapshot(pipe, page)["pending"] is True
    pipe.evaluate(page, "window.fixtureNodes[0].nodes[0].metadata.acked_sequence_number = '2'; true")
    tombstone = (
        "(async()=>{const {aboutInfo} = await import('./about.js'); "
        "aboutInfo.type_status[0].num_entries = 2; return true;})()"
    )
    pipe.evaluate(page, tombstone)
    assert snapshot(pipe, page)["pending"] is True
    pipe.evaluate(page, tombstone.replace("= 2", "= 1"))
    assert snapshot(pipe, page)["pending"] is False
    pipe.evaluate(
        page,
        "(async()=>{const {aboutInfo} = await import('./about.js'); "
        "aboutInfo.type_status[0].status = 'severity_error'; return true;})()",
    )
    assert snapshot(pipe, page)["healthy"] is False
    print(
        "Native diagnostic checks: stale success, pending upload, pending deletion, failure, and success passed.",
        flush=True,
    )


def pending_chain(pipe: BrowserPipe, native: NativeSync) -> str:
    """Persist a generated code through the native API while the Sync endpoint is disabled."""

    pairing = pipe.evaluate(
        native.settings,
        """(async () => {
      const {sendWithPromise} = await import('chrome://resources/js/cr.js');
      return await sendWithPromise('SyncSetupGetSyncCode');
    })()""",
    )
    assert isinstance(pairing, str) and len(pairing.split()) == 25
    code = " ".join(pairing.split()[:24])
    # The offline join cannot acknowledge success. Start it without awaiting the
    # server, then prove the native encrypted code survives a normal restart.
    pipe.evaluate(
        native.settings,
        """(async () => {
      const {sendWithPromise} = await import('chrome://resources/js/cr.js');
      void sendWithPromise('SyncSetupSetSyncCode', PAIRING).catch(() => {});
      return true;
    })()""".replace("PAIRING", json.dumps(pairing)),
    )
    deadline = time.monotonic() + 10
    while native.code() != code:
        assert time.monotonic() < deadline, "Native code was not saved"
        time.sleep(0.1)
    return code


def sync_selection(pipe: BrowserPipe, page: str) -> None:
    """Exercise the production selection code against native-shaped WebUI callbacks."""

    pipe.evaluate(
        page,
        """(async () => {
      const {webUIListenerCallback, webUIResponse} = await import('chrome://resources/js/cr.js');
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
        environment = browser_environment()
        with BrowserPipe(arguments, environment) as pipe:
            native = NativeSync(pipe, directory + "/Default")
            assert len(native.code().split()) == 24
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
