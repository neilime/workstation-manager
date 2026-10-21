"""Keep browser fixture ownership separate from preexisting workstation devices."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

import pytest

MODULE_PATH = Path(__file__).parents[1] / "browser_sync_fixture.py"
SPEC = importlib.util.spec_from_file_location("browser_sync_fixture", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
browser_fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(browser_fixture)
# Build synthetic diagnostics with the implementation's fixed, private allowlist.
TEARDOWN_CHECKS = browser_fixture._TEARDOWN_CHECKS  # pylint: disable=protected-access
REMOVAL_CHECKS = browser_fixture._REMOVAL_CHECKS  # pylint: disable=protected-access


def write_device(root: Path, name: str, guid: str, *, initialized: bool = True) -> None:
    """Create synthetic encrypted-seed presence and native device identity metadata."""

    profile = root / name
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "Preferences").write_text(
        json.dumps(
            {
                "brave_sync_v2": {"seed": "encrypted-fixture-seed"},
                "sync": {
                    "transport_data_per_account": {
                        "fixture-account": {"sync.cache_guid": guid, "sync.birthday": "1" if initialized else ""}
                    }
                },
            }
        )
    )


def test_existing_browser_tree_cannot_be_claimed_by_tests(tmp_path: Path) -> None:
    """Fixture preparation rejects preexisting profiles before recording ownership."""

    root = tmp_path / "browser"
    write_device(root, "Everyday", "existing-device")
    manifest = tmp_path / "fixture.json"
    with pytest.raises(ValueError, match="fresh VM"):
        browser_fixture.BrowserSyncFixture(root, manifest).prepare()
    assert not manifest.exists()
    assert browser_fixture.device_identity(root / "Everyday") == "existing-device"


def test_fixture_records_only_initialized_devices_created_after_prepare(tmp_path: Path) -> None:
    """A fresh fixture captures exact device GUIDs, excluding incomplete enrollment."""

    root = tmp_path / "browser"
    manifest = tmp_path / "fixture.json"
    fixture = browser_fixture.BrowserSyncFixture(root, manifest)
    fixture.prepare()
    write_device(root, "Default", "test-device")
    write_device(root, "Profile 2", "uninitialized-device", initialized=False)
    fixture.capture()
    record = fixture.load()
    assert record["devices"] == {"Default": "test-device"}
    assert record["phase"] == "captured"
    assert manifest.stat().st_mode & 0o777 == 0o600
    assert "encrypted-fixture-seed" not in manifest.read_text()
    with pytest.raises(ValueError, match="already captured"):
        fixture.capture()


def test_fixture_ownership_cannot_move_to_another_vm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A copied manifest cannot authorize operations on another machine's profiles."""

    fixture = browser_fixture.BrowserSyncFixture(tmp_path / "browser", tmp_path / "fixture.json")
    fixture.prepare()
    monkeypatch.setattr(browser_fixture.platform, "node", lambda: "another-machine")
    with pytest.raises(ValueError, match="ownership does not match"):
        fixture.load()


def test_successful_setup_must_capture_every_recovered_identity(tmp_path: Path) -> None:
    """Unsupported identity metadata cannot silently omit a device after successful setup."""

    root = tmp_path / "browser"
    fixture = browser_fixture.BrowserSyncFixture(root, tmp_path / "fixture.json")
    fixture.prepare()
    write_device(root, "Default", "test-device", initialized=False)
    with pytest.raises(ValueError, match="no initialized device identity"):
        fixture.capture(require_initialized=True)
    assert fixture.load()["phase"] == "prepared"


def test_browser_fixture_cli_refuses_the_development_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """The VM-only command fails before inspecting or changing host browser data."""

    monkeypatch.setattr(browser_fixture.platform, "node", lambda: "development-host")
    constructor = mock.Mock()
    monkeypatch.setattr(browser_fixture, "BrowserSyncFixture", constructor)
    with pytest.raises(SystemExit, match="Lima VM"):
        browser_fixture.main()
    constructor.assert_not_called()


def test_teardown_leaves_only_captured_test_identities(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Profiles introduced after fixture capture never become teardown targets."""

    root = tmp_path / "browser"
    fixture = browser_fixture.BrowserSyncFixture(root, tmp_path / "fixture.json")
    fixture.prepare()
    write_device(root, "Default", "test-device")
    fixture.capture()
    write_device(root, "Everyday", "untracked-device")
    monkeypatch.setattr(browser_fixture, "closed_browser", lambda _root: nullcontext(("brave", {})))
    pipe = mock.Mock()
    browser = mock.Mock(return_value=nullcontext(pipe))
    monkeypatch.setattr(browser_fixture, "BrowserPipe", browser)
    leave = mock.Mock()
    monkeypatch.setattr(browser_fixture, "leave_device", leave)
    fixture.leave()
    leave.assert_called_once_with(pipe, root / "Default", "test-device")
    assert "--sync-short-nudge-delay-for-test" in browser.call_args.args[0]
    assert browser_fixture.device_identity(root / "Everyday") == "untracked-device"
    assert not fixture.load()["devices"]
    fixture.leave()
    assert leave.call_count == 1


def test_teardown_refuses_a_replaced_device_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reusing a captured profile directory for another device cannot authorize leaving it."""

    root = tmp_path / "browser"
    fixture = browser_fixture.BrowserSyncFixture(root, tmp_path / "fixture.json")
    fixture.prepare()
    write_device(root, "Default", "test-device")
    fixture.capture()
    write_device(root, "Default", "replacement-device")
    monkeypatch.setattr(browser_fixture, "closed_browser", lambda _root: nullcontext(("brave", {})))
    leave = mock.Mock()
    monkeypatch.setattr(browser_fixture, "leave_device", leave)
    with pytest.raises(ValueError, match="no longer matches"):
        fixture.leave()
    leave.assert_not_called()
    assert fixture.load()["devices"] == {"Default": "test-device"}


def teardown_state(*, matches: bool = True, failed: tuple[str, ...] = (), needs_navigation: bool = False) -> dict:
    """Build one synthetic atomic readiness observation without browser data."""

    checks = dict.fromkeys(TEARDOWN_CHECKS, True)
    checks.update(dict.fromkeys(failed, False))
    return {
        "active": not needs_navigation and checks["Transport State"],
        "ready": not needs_navigation and all(checks.values()),
        "matches": matches,
        "needsNavigation": needs_navigation,
        "checks": checks,
    }


def mock_teardown_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Advance the verification deadline only when a test explicitly waits."""

    clock = [0.0]
    monkeypatch.setattr(browser_fixture.time, "monotonic", lambda: clock[0])

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    monkeypatch.setattr(browser_fixture.time, "sleep", sleep)


@pytest.mark.parametrize("successful", [False, True])
def test_native_leave_preserves_the_native_callback_result(successful: bool) -> None:
    """Only the native boolean acknowledgement can complete a captured device's leave."""

    pipe = mock.Mock()
    pipe.evaluate.return_value = successful
    assert browser_fixture.reset_device(pipe, "settings", "captured-device") is successful
    pipe.evaluate.assert_called_once()
    assert pipe.evaluate.call_args.kwargs["timeout"] == 120


def test_native_leave_refuses_a_different_settings_device() -> None:
    """A matching diagnostic tab cannot authorize resetting another settings profile."""

    pipe = mock.Mock()
    pipe.evaluate.return_value = None
    with pytest.raises(ValueError, match="settings page no longer matches"):
        browser_fixture.reset_device(pipe, "settings", "captured-device")
    pipe.evaluate.assert_called_once()


@pytest.mark.parametrize("invalid", ["private-response", {"successful": True}])
def test_native_leave_rejects_untrusted_callback_state(invalid: object) -> None:
    """An unsupported native result cannot enter diagnostics or authorize VM deletion."""

    pipe = mock.Mock()
    pipe.evaluate.return_value = invalid
    with pytest.raises(ValueError, match="unsupported native leave diagnostics$"):
        browser_fixture.reset_device(pipe, "settings", "captured-device")


@pytest.mark.parametrize("matches", [False, True])
def test_live_device_identity_is_required_before_leaving(matches: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    """Native teardown requires an active tracker and the exact captured device GUID."""

    monkeypatch.setattr(browser_fixture, "NativeSync", mock.Mock())
    pipe = mock.Mock()
    pipe.wait_for_acknowledgement.return_value = True
    pipe.evaluate.side_effect = [teardown_state(matches=matches), True, True]
    if matches:
        browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device")
        assert pipe.evaluate.call_count == 3
        pipe.call.assert_called_once_with(
            "Runtime.removeBinding", {"name": "workstationDeviceRemoved"}, pipe.page.return_value
        )
    else:
        with pytest.raises(ValueError, match="live browser device no longer matches"):
            browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device")
        assert pipe.evaluate.call_count == 1
        pipe.call.assert_not_called()


@pytest.mark.parametrize("removed,acknowledged", [(True, False), (False, True)])
def test_native_leave_requires_both_local_and_server_confirmation(
    removed: bool, acknowledged: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The native leave callback and server deletion acknowledgement must both succeed."""

    monkeypatch.setattr(browser_fixture, "NativeSync", mock.Mock())
    pipe = mock.Mock()
    pipe.wait_for_acknowledgement.return_value = acknowledged
    pipe.evaluate.side_effect = [teardown_state(), True, removed, dict.fromkeys(REMOVAL_CHECKS, False)]
    message = "server did not confirm removal" if removed else "Brave did not confirm leaving"
    with pytest.raises(ValueError, match=message):
        browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device")
    pipe.call.assert_not_called()


def test_missing_removal_reports_only_incomplete_protocol_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Distinguish a missing tombstone from an unconfirmed response without logging device data."""

    monkeypatch.setattr(browser_fixture, "NativeSync", mock.Mock())
    pipe = mock.Mock()
    pipe.wait_for_acknowledgement.return_value = False
    checks = {**dict.fromkeys(REMOVAL_CHECKS, True), "Matching Response": False, "Server Acknowledgement": False}
    pipe.evaluate.side_effect = [teardown_state(), True, True, checks]
    with pytest.raises(ValueError, match="incomplete checks: Matching Response, Server Acknowledgement$"):
        browser_fixture.leave_device(pipe, Path("/fixture/Default"), "private-test-device")
    pipe.call.assert_not_called()


@pytest.mark.parametrize("invalid", [None, {"private-device": False}, dict.fromkeys(REMOVAL_CHECKS, "private-value")])
def test_removal_diagnostics_reject_untrusted_fields(invalid: object) -> None:
    """Malformed diagnostic payloads never enter the teardown error message."""

    pipe = mock.Mock()
    pipe.evaluate.return_value = invalid
    assert browser_fixture.incomplete_removal_checks(pipe, "session") == "removal observer unavailable"


def test_teardown_waits_for_server_evidence_before_removing_the_observer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful leave callback can precede the diagnostic target's server event."""

    monkeypatch.setattr(browser_fixture, "NativeSync", mock.Mock())
    pipe = mock.Mock()
    pipe.watch_acknowledgement.return_value = lambda: False
    pipe.evaluate.side_effect = [teardown_state(), True, True]

    def delayed_acknowledgement(session: str, name: str) -> bool:
        assert session == pipe.page.return_value
        assert name == "workstationDeviceRemoved"
        assert pipe.evaluate.call_count == 3
        pipe.call.assert_not_called()
        return True

    pipe.wait_for_acknowledgement.side_effect = delayed_acknowledgement
    browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device")
    pipe.wait_for_acknowledgement.assert_called_once()
    pipe.call.assert_called_once_with(
        "Runtime.removeBinding", {"name": "workstationDeviceRemoved"}, pipe.page.return_value
    )


@pytest.mark.parametrize("acknowledged", [False, True])
def test_teardown_retains_server_confirmation_after_diagnostic_page_loss(
    acknowledged: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Losing page globals after native leave neither loses nor invents server confirmation."""

    monkeypatch.setattr(browser_fixture, "NativeSync", mock.Mock())
    pipe = mock.Mock()
    pipe.wait_for_acknowledgement.return_value = acknowledged
    pipe.evaluate.side_effect = [
        teardown_state(),
        True,
        True,
        browser_fixture.BrowserProtocolError("diagnostic page globals were discarded"),
    ]
    if acknowledged:
        browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device")
    else:
        with pytest.raises(ValueError, match="server did not confirm removal"):
            browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device")
    assert pipe.evaluate.call_count == (3 if acknowledged else 4)


def test_native_leave_failure_is_not_masked_by_diagnostic_page_loss(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed native leave stays failed even when its observer page also disappears."""

    monkeypatch.setattr(browser_fixture, "NativeSync", mock.Mock())
    pipe = mock.Mock()
    pipe.wait_for_acknowledgement.return_value = True
    pipe.evaluate.side_effect = [
        teardown_state(),
        True,
        ValueError("native leave failed"),
        ValueError("diagnostic page globals were discarded"),
    ]
    with pytest.raises(ValueError, match="native leave failed"):
        browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device")
    assert pipe.evaluate.call_count == 3


def test_teardown_requires_native_callbacks_before_requesting_removal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unavailable native callbacks cannot authorize a captured device's removal."""

    monkeypatch.setattr(browser_fixture, "NativeSync", mock.Mock())
    mock_teardown_clock(monkeypatch)
    pipe = mock.Mock()
    pipe.evaluate.return_value = teardown_state(
        failed=("Native Callbacks", "Readiness Observer"), needs_navigation=True
    )
    pipe.call.return_value = {}
    with pytest.raises(ValueError, match="incomplete checks: Native Callbacks, Readiness Observer$"):
        browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device", timeout=1)
    assert pipe.evaluate.call_count == 1
    assert "SyncSetupReset" not in pipe.evaluate.call_args.args[1]
    pipe.call.assert_called_once_with(
        "Page.navigate", {"url": "chrome://sync-internals/"}, pipe.page.return_value, timeout=1
    )


@pytest.mark.parametrize("matches", [False, True])
def test_teardown_reloads_a_lost_context_and_rechecks_identity(matches: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the owned diagnostic target is recovered before checking readiness and identity again."""

    monkeypatch.setattr(browser_fixture, "NativeSync", mock.Mock())
    mock_teardown_clock(monkeypatch)
    pipe = mock.Mock()
    pipe.wait_for_acknowledgement.return_value = True
    pipe.evaluate.side_effect = [
        teardown_state(failed=("Diagnostic Page", "Readiness Observer"), needs_navigation=True),
        teardown_state(matches=matches),
        True,
        True,
    ]
    pipe.call.return_value = {}
    if matches:
        browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device", timeout=5)
        assert pipe.evaluate.call_count == 4
    else:
        with pytest.raises(ValueError, match="live browser device no longer matches"):
            browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device", timeout=5)
        assert pipe.evaluate.call_count == 2
    expected = [mock.call("Page.navigate", {"url": "chrome://sync-internals/"}, pipe.page.return_value, timeout=5)]
    if matches:
        expected.append(
            mock.call("Runtime.removeBinding", {"name": "workstationDeviceRemoved"}, pipe.page.return_value)
        )
    assert pipe.call.call_args_list == expected
    observations = [call for call in pipe.method_calls if call[0] in {"evaluate", "call"}]
    first_poll, navigation, second_poll = observations[:3]
    assert [first_poll[0], navigation[0], second_poll[0]] == ["evaluate", "call", "evaluate"]
    assert "SyncSetupReset" not in first_poll.args[1]
    assert second_poll.kwargs["timeout"] == 8


def test_teardown_context_recovery_cannot_extend_the_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated unavailable contexts stop within the original verification deadline without resetting Sync."""

    monkeypatch.setattr(browser_fixture, "NativeSync", mock.Mock())
    mock_teardown_clock(monkeypatch)
    pipe = mock.Mock()
    pipe.evaluate.return_value = teardown_state(failed=("Diagnostic Page",), needs_navigation=True)
    pipe.call.return_value = {}
    with pytest.raises(ValueError, match="incomplete checks: Diagnostic Page$"):
        browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device", timeout=3)
    assert [call.kwargs["timeout"] for call in pipe.evaluate.call_args_list] == [8, 6]
    assert [call.kwargs["timeout"] for call in pipe.call.call_args_list] == [3, 1]
    assert all("SyncSetupReset" not in call.args[1] for call in pipe.evaluate.call_args_list)


@pytest.mark.parametrize("failure", ["navigation", "snapshot", "navigation-result"])
def test_teardown_context_recovery_preserves_protocol_failures(failure: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed native protocol operation is not converted into readiness or a successful removal."""

    monkeypatch.setattr(browser_fixture, "NativeSync", mock.Mock())
    pipe = mock.Mock()
    error = ValueError("synthetic protocol failure")
    pipe.evaluate.return_value = teardown_state(needs_navigation=True)
    if failure == "navigation":
        pipe.call.side_effect = error
    elif failure == "snapshot":
        pipe.evaluate.side_effect = error
    else:
        pipe.call.return_value = {"errorText": "private-page-error"}
    message = "could not reopen Sync diagnostics" if failure == "navigation-result" else "synthetic protocol failure"
    with pytest.raises(ValueError, match=message) as raised:
        browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device")
    assert "private" not in str(raised.value)
    assert all("SyncSetupReset" not in call.args[1] for call in pipe.evaluate.call_args_list)


def test_teardown_does_not_leave_when_sync_cannot_be_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unavailable server cannot turn a local reset into successful remote teardown."""

    monkeypatch.setattr(browser_fixture, "NativeSync", mock.Mock())
    mock_teardown_clock(monkeypatch)
    pipe = mock.Mock()
    pipe.evaluate.side_effect = [teardown_state(failed=("Fresh Download", "Server Connection"))]
    with pytest.raises(ValueError, match="incomplete checks: Fresh Download, Server Connection$"):
        browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device", timeout=1)
    assert pipe.evaluate.call_count == 1
    pipe.call.assert_not_called()
    assert all("SyncSetupReset" not in call.args[1] for call in pipe.evaluate.call_args_list)


@pytest.mark.parametrize("invalid", [None, {"private-device-data": False}, {"Fresh Download": "private-response"}])
def test_teardown_diagnostics_never_report_untrusted_browser_fields(
    invalid: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed readiness evidence stays private and cannot authorize server removal."""

    monkeypatch.setattr(browser_fixture, "NativeSync", mock.Mock())
    pipe = mock.Mock()
    checks = {**dict.fromkeys(TEARDOWN_CHECKS, True), **invalid} if isinstance(invalid, dict) else invalid
    pipe.evaluate.return_value = {**teardown_state(), "checks": checks}
    with pytest.raises(ValueError, match="unsupported teardown diagnostics") as error:
        browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device")
    assert "private" not in str(error.value)
    pipe.call.assert_not_called()
    assert all("SyncSetupReset" not in call.args[1] for call in pipe.evaluate.call_args_list)


@pytest.mark.parametrize("invalid", [False, {}, {"active": "private-response"}])
def test_teardown_rejects_malformed_readiness_snapshots(invalid: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unsupported result structures fail immediately without logging untrusted payloads or spinning."""

    monkeypatch.setattr(browser_fixture, "NativeSync", mock.Mock())
    pipe = mock.Mock()
    pipe.evaluate.return_value = invalid
    with pytest.raises(ValueError, match="unsupported teardown diagnostics") as error:
        browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device")
    assert "private" not in str(error.value)
    assert pipe.evaluate.call_count == 1
    pipe.call.assert_not_called()


@pytest.mark.parametrize("cleanup_status", [0, 17])
def test_vm_deletion_requires_successful_browser_fixture_teardown(tmp_path: Path, cleanup_status: int) -> None:
    """A failed leave operation retains the VM and its identities for a retry."""

    commands = tmp_path / "bin"
    commands.mkdir()
    log = tmp_path / "commands"
    limactl = commands / "limactl"
    limactl.write_text(
        "#!/bin/bash\n"
        'printf "%s\\n" "$1" >>"$TEST_COMMAND_LOG"\n'
        'case "$1" in\n'
        '  list) if [[ "$2" == --format ]]; then echo fixture; else echo Running; fi ;;\n'
        '  shell) exit "$TEST_CLEANUP_STATUS" ;;\n'
        "esac\n"
    )
    limactl.chmod(0o700)
    result = subprocess.run(
        ["bash", str(MODULE_PATH.parent / "e2e-down.sh"), "fixture"],
        env={
            **os.environ,
            "PATH": f"{commands}:/usr/bin:/bin",
            "TEST_COMMAND_LOG": str(log),
            "TEST_CLEANUP_STATUS": str(cleanup_status),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == (1 if cleanup_status else 0), result.stderr
    assert log.read_text().splitlines() == ["list", "list", "shell"] + ([] if cleanup_status else ["stop", "delete"])
