"""Keep browser fixture ownership separate from preexisting workstation devices."""

from __future__ import annotations

import importlib.util
import json
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

import pytest

MODULE_PATH = Path(__file__).parents[2] / "e2e-tests/browser_sync_fixture.py"
SPEC = importlib.util.spec_from_file_location("browser_sync_fixture", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
browser_fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(browser_fixture)
# Build synthetic diagnostics with the implementation's fixed, private allowlist.
TEARDOWN_CHECKS = browser_fixture._TEARDOWN_CHECKS  # pylint: disable=protected-access
REMOVAL_CHECKS = browser_fixture._REMOVAL_CHECKS  # pylint: disable=protected-access
PROTOCOL_BINDING = browser_fixture._PROTOCOL_BINDING  # pylint: disable=protected-access


@pytest.fixture(autouse=True)
def isolated_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise orchestration without starting browser processes or networking."""

    monkeypatch.setattr(browser_fixture, "closed_browser", lambda _root, **_kwargs: nullcontext(("brave", {})))
    monkeypatch.setattr(browser_fixture, "SyncNetworkGate", lambda: nullcontext(mock.Mock(proxy_url="http://gate")))
    monkeypatch.setattr(browser_fixture.time, "sleep", lambda _seconds: None)


@pytest.fixture(name="captured_fixture")
def make_captured_fixture(tmp_path: Path):
    """Capture one initialized device and leave a subsequently added profile untracked."""

    root = tmp_path / "browser"
    fixture = browser_fixture.BrowserSyncFixture(root, tmp_path / "fixture.json")
    fixture.prepare()
    write_device(root, "Default", "captured-device")
    fixture.capture()
    write_device(root, "Everyday", "untracked-device")
    return fixture


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


@pytest.mark.parametrize("change", ["none", "missing", "replaced", "additional", "uninitialized"])
def test_repeat_setup_preserves_the_exact_captured_identities(tmp_path: Path, monkeypatch, change: str) -> None:
    """Verification detects device drift without claiming identities or exposing private metadata."""

    root = tmp_path / "browser"
    fixture = browser_fixture.BrowserSyncFixture(root, tmp_path / "fixture.json")
    fixture.prepare()
    write_device(root, "Default", "captured-device")
    fixture.capture(require_initialized=True)
    manifest_before = fixture.manifest.read_bytes()
    saved = mock.Mock()
    monkeypatch.setattr(browser_fixture, "write_private_json", saved)
    if change == "missing":
        (root / "Default/Preferences").unlink()
    elif change == "replaced":
        write_device(root, "Default", "replacement-device")
    elif change == "additional":
        write_device(root, "Additional", "additional-device")
    elif change == "uninitialized":
        write_device(root, "Default", "uninitialized-device", initialized=False)

    if change == "none":
        fixture.verify()
    else:
        message = "no initialized device identity" if change == "uninitialized" else "no longer match"
        with pytest.raises(ValueError, match=message) as error:
            fixture.verify()
        assert all(
            value not in str(error.value)
            for value in (
                "captured-device",
                "replacement-device",
                "additional-device",
                "uninitialized-device",
                "Default",
            )
        )

    saved.assert_not_called()
    assert fixture.manifest.read_bytes() == manifest_before


def test_repeat_setup_requires_captured_fixture_ownership(tmp_path: Path) -> None:
    """A prepared manifest cannot authorize setup to reuse uncaptured browser identities."""

    fixture = browser_fixture.BrowserSyncFixture(tmp_path / "browser", tmp_path / "fixture.json")
    fixture.prepare()
    before = fixture.manifest.read_bytes()
    with pytest.raises(ValueError, match="not captured"):
        fixture.verify()
    assert fixture.manifest.read_bytes() == before


def test_browser_fixture_cli_refuses_the_development_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """The VM-only command fails before inspecting or changing host browser data."""

    monkeypatch.setattr(browser_fixture.platform, "node", lambda: "development-host")
    constructor = mock.Mock()
    monkeypatch.setattr(browser_fixture, "BrowserSyncFixture", constructor)
    with pytest.raises(SystemExit, match="Lima VM"):
        browser_fixture.main()
    constructor.assert_not_called()


def test_teardown_leaves_only_captured_identities_in_isolated_copies(captured_fixture, monkeypatch) -> None:
    """Only the copied captured profile can be reset, and the desktop stays closed afterward."""

    fixture = captured_fixture
    browser = mock.Mock(return_value=nullcontext(mock.sentinel.pipe))
    monkeypatch.setattr(browser_fixture, "BrowserPipe", browser)
    closed = mock.Mock(return_value=nullcontext(("brave", {})))
    monkeypatch.setattr(browser_fixture, "closed_browser", closed)

    def leave(pipe, copied, identity, *, network):
        assert pipe is mock.sentinel.pipe
        assert copied != fixture.root / "Default"
        assert browser_fixture.device_identity(copied) == identity == "captured-device"
        assert not (copied.parent / "Everyday").exists()
        assert network.proxy_url == "http://gate"
        (copied / "Preferences").write_text("{}")

    leaving = mock.Mock(side_effect=leave)
    monkeypatch.setattr(browser_fixture, "leave_device", leaving)
    fixture.leave()
    closed.assert_called_once_with(str(fixture.root), reopen=False)
    arguments = browser.call_args.args[0]
    assert "--proxy-server=http://gate" in arguments
    assert "--disable-quic" in arguments
    assert "--restore-last-session" not in arguments
    assert browser_fixture.device_identity(fixture.root / "Default") == "captured-device"
    assert browser_fixture.device_identity(fixture.root / "Everyday") == "untracked-device"
    assert not fixture.load()["devices"]
    fixture.leave()
    leaving.assert_called_once()


def test_teardown_refuses_a_replaced_device_identity(captured_fixture, monkeypatch) -> None:
    """A captured directory reused by another identity cannot authorize its removal."""

    fixture = captured_fixture
    write_device(fixture.root, "Default", "replacement-device")
    leave = mock.Mock()
    monkeypatch.setattr(browser_fixture, "leave_device", leave)
    with pytest.raises(ValueError, match="no longer matches"):
        fixture.leave()
    leave.assert_not_called()
    assert fixture.load()["devices"] == {"Default": "captured-device"}


@pytest.mark.parametrize("successful", [False, True])
@pytest.mark.parametrize("failure", [browser_fixture.UnconfirmedDeviceRemoval, browser_fixture.BrowserProtocolError])
def test_teardown_retries_from_intact_state_after_reset(
    captured_fixture, monkeypatch, successful, failure, capsys
) -> None:
    """Lost server replies or IPC after a destructive reset cannot destroy retry state."""

    fixture = captured_fixture
    source = fixture.root / "Default"
    (source / "Sync Data").mkdir()
    (source / "Sync Data/state").write_text("private-tracker")
    monkeypatch.setattr(browser_fixture, "BrowserPipe", lambda _args, _env: nullcontext(mock.sentinel.pipe))
    attempts = []

    def leave(_pipe, copied, identity, *, network):
        assert browser_fixture.device_identity(copied) == identity == "captured-device"
        assert (copied / "Sync Data/state").read_text() == "private-tracker"
        assert network is not None
        assert fixture.load()["devices"] == {"Default": "captured-device"}
        attempts.append(copied)
        (copied / "Preferences").write_text("{}")
        (copied / "Sync Data/state").unlink()
        if not successful or len(attempts) == 1:
            raise failure("Missing server confirmation")

    monkeypatch.setattr(browser_fixture, "leave_device", leave)
    if successful:
        fixture.leave()
        assert len(attempts) == 2
        assert not fixture.load()["devices"]
    else:
        with pytest.raises(failure, match="Missing server confirmation"):
            fixture.leave()
        assert len(attempts) == 3
        assert fixture.load()["devices"] == {"Default": "captured-device"}
    assert len(set(attempts)) == len(attempts)
    assert all(not copy.parent.exists() for copy in attempts)
    assert browser_fixture.device_identity(source) == "captured-device"
    assert (source / "Sync Data/state").read_text() == "private-tracker"
    output = capsys.readouterr().out
    assert "Retrying E2E device removal" in output
    assert "private" not in output and "captured-device" not in output


def test_confirmed_removal_is_saved_before_browser_shutdown(captured_fixture, monkeypatch) -> None:
    """A close failure after server proof cannot cause a second deletion on rerun."""

    fixture = captured_fixture
    pipe = mock.MagicMock()
    pipe.__exit__.side_effect = browser_fixture.BrowserProtocolError("Shutdown failed")
    browser = mock.Mock(return_value=pipe)
    monkeypatch.setattr(browser_fixture, "BrowserPipe", browser)
    leave = mock.Mock()
    monkeypatch.setattr(browser_fixture, "leave_device", leave)
    with pytest.raises(browser_fixture.BrowserProtocolError, match="Shutdown failed"):
        fixture.leave()
    assert not fixture.load()["devices"]
    fixture.leave()
    browser.assert_called_once()
    leave.assert_called_once()


def test_teardown_cannot_overlap_a_retained_browser(captured_fixture, monkeypatch) -> None:
    """Even confirmed devices cannot authorize VM deletion while a copied writer remains live."""

    fixture = captured_fixture
    copy = fixture.manifest.parent / "browser-teardown-retained"
    copy.mkdir()
    monkeypatch.setattr(browser_fixture, "browser_processes", lambda _root: [123])
    browser = mock.Mock()
    monkeypatch.setattr(browser_fixture, "BrowserPipe", browser)
    with pytest.raises(ValueError, match="still running"):
        fixture.leave()
    browser.assert_not_called()
    assert copy.exists()
    assert fixture.load()["devices"] == {"Default": "captured-device"}


def teardown_state(*, matches=True, failed=(), needs_navigation=False, stopped=False):
    """Build a synthetic atomic status observation with the fixed diagnostic allowlist."""

    checks = {**dict.fromkeys(TEARDOWN_CHECKS, True), **dict.fromkeys(failed, False)}
    return {
        "active": not stopped and not needs_navigation and checks["Transport State"],
        "stopped": stopped,
        "ready": not needs_navigation and all(checks.values()),
        "matches": matches,
        "needsNavigation": needs_navigation,
        "checks": checks,
    }


@pytest.fixture(name="native_pipe")
def make_native_pipe(monkeypatch):
    """Provide ready native callbacks while retaining explicit control over server proof."""

    monkeypatch.setattr(browser_fixture, "NativeSync", mock.Mock())
    pipe = mock.Mock()
    pipe.forwarded = mock.Mock(return_value=True)
    pipe.readback = mock.Mock(return_value=False)
    pipe.committed = mock.Mock(return_value=False)
    pipe.commit_response = mock.Mock(return_value=True)
    pipe.watch_acknowledgement.side_effect = lambda _session, binding: {
        PROTOCOL_BINDING: pipe.forwarded,
        "workstationDeviceRemoved": pipe.readback,
        "workstationDeviceRemovedCommit": pipe.committed,
    }[binding]
    pipe.wait_for_acknowledgement.side_effect = lambda _session, binding, **_kwargs: {
        PROTOCOL_BINDING: pipe.forwarded,
        "workstationDeviceRemovedCommit": pipe.commit_response,
    }[binding]()
    return pipe


def leave_device(pipe, *, timeout=120, network=None):
    """Invoke fixture deletion with an explicitly controlled startup gate."""

    browser_fixture.leave_device(
        pipe, Path("/fixture/Default"), "captured-device", timeout, network=network or mock.Mock()
    )


def test_observer_is_installed_before_sync_can_receive_a_server_tombstone(native_pipe) -> None:
    """A retry observes its own server deletion even when Brave then disables its tracker."""

    pipe = native_pipe
    pipe.evaluate.side_effect = [
        True,
        True,
        teardown_state(stopped=True, failed=("Transport State", "Device Info State")),
    ]
    acknowledged = pipe.readback
    network = mock.Mock()

    def release():
        assert pipe.evaluate.call_count == 2
        pipe.watch_acknowledgement.assert_has_calls(
            [
                mock.call(pipe.page.return_value, PROTOCOL_BINDING),
                mock.call(pipe.page.return_value, "workstationDeviceRemoved"),
            ]
        )
        pipe.wait_for_acknowledgement.assert_called_once_with(pipe.page.return_value, PROTOCOL_BINDING, timeout=30)
        pipe.forwarded.assert_called_once()
        pipe.commit_response.assert_not_called()
        acknowledged.return_value = True

    network.release.side_effect = release
    leave_device(pipe, network=network)
    network.release.assert_called_once()
    assert pipe.evaluate.call_count == 3
    assert all("SyncSetupReset" not in call.args[1] for call in pipe.evaluate.call_args_list)


def test_missing_backend_protocol_forwarding_keeps_network_gated(native_pipe, monkeypatch) -> None:
    """Page listeners cannot authorize server traffic until the Sync thread forwards native events."""

    pipe = native_pipe
    pipe.evaluate.side_effect = [True, True]
    pipe.forwarded.return_value = False
    network = mock.Mock()
    reset = mock.Mock()
    monkeypatch.setattr(browser_fixture, "reset_device", reset)
    with pytest.raises(browser_fixture.BrowserProtocolError, match="did not enable native protocol forwarding"):
        leave_device(pipe, timeout=1, network=network)
    pipe.wait_for_acknowledgement.assert_called_once_with(pipe.page.return_value, PROTOCOL_BINDING, timeout=1)
    network.release.assert_not_called()
    reset.assert_not_called()
    pipe.readback.assert_not_called()
    pipe.commit_response.assert_not_called()
    assert pipe.evaluate.call_count == 2


@pytest.mark.parametrize("committed", [False, True])
def test_active_client_requires_new_commit_proof_after_downloading_its_tombstone(native_pipe, committed) -> None:
    """A pending local update can recreate a deleted device, invalidating its earlier readback."""

    pipe = native_pipe
    pipe.readback.return_value = True
    pipe.evaluate.side_effect = [True, True, teardown_state(), True, True, dict.fromkeys(REMOVAL_CHECKS, False)]
    pipe.commit_response.return_value = committed
    if committed:
        leave_device(pipe)
    else:
        with pytest.raises(browser_fixture.UnconfirmedDeviceRemoval, match="did not confirm removal"):
            leave_device(pipe)
    bindings = [call.args[1] for call in pipe.watch_acknowledgement.call_args_list]
    assert bindings == [PROTOCOL_BINDING, "workstationDeviceRemoved", "workstationDeviceRemovedCommit"]
    assert pipe.wait_for_acknowledgement.call_args_list == [
        mock.call(pipe.page.return_value, PROTOCOL_BINDING, timeout=30),
        mock.call(pipe.page.return_value, bindings[-1]),
    ]
    assert "SyncSetupReset" in pipe.evaluate.call_args_list[4].args[1]


def test_server_tombstone_requires_a_fresh_disabled_transport(native_pipe, monkeypatch) -> None:
    """A missing or stale status response cannot rule out a pending device update."""

    clock = [0.0]
    monkeypatch.setattr(browser_fixture.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(browser_fixture.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    pipe = native_pipe
    pipe.readback.return_value = True
    pipe.evaluate.side_effect = [True, True, teardown_state(stopped=True, failed=("Status Response",))]
    with pytest.raises(ValueError, match="could not verify Sync readiness"):
        leave_device(pipe, timeout=1)
    pipe.wait_for_acknowledgement.assert_called_once_with(pipe.page.return_value, PROTOCOL_BINDING, timeout=1)
    pipe.commit_response.assert_not_called()


@pytest.mark.parametrize("acknowledged", [False, True])
@pytest.mark.parametrize("operation", ["readiness", "reset"])
def test_server_proof_survives_protocol_loss_during_teardown(native_pipe, acknowledged, operation) -> None:
    """Discarded page state cannot erase proven deletion or certify an unproven device."""

    pipe = native_pipe
    responses = [True, True]
    if operation == "reset":
        responses.extend([teardown_state(), True])

    def evaluate(*_args, **_kwargs):
        if responses:
            return responses.pop(0)
        pipe.readback.return_value = acknowledged
        pipe.committed.return_value = acknowledged
        raise browser_fixture.BrowserProtocolError("Execution context was destroyed")

    pipe.evaluate.side_effect = evaluate
    if acknowledged and operation == "reset":
        leave_device(pipe)
    else:
        with pytest.raises(browser_fixture.BrowserProtocolError, match="Execution context was destroyed"):
            leave_device(pipe)


@pytest.mark.parametrize("installed", [False, True])
def test_missing_observer_keeps_network_gated(native_pipe, installed) -> None:
    """No server contact is allowed until both native listeners and the proof observer exist."""

    pipe = native_pipe
    pipe.evaluate.side_effect = [installed, False]
    network = mock.Mock()
    with pytest.raises(browser_fixture.BrowserProtocolError, match="could not observe"):
        leave_device(pipe, network=network)
    network.release.assert_not_called()
    pipe.wait_for_acknowledgement.assert_not_called()


@pytest.mark.parametrize("matches", [False, True])
def test_native_reset_requires_an_active_exact_captured_identity(native_pipe, matches) -> None:
    """An active diagnostic page cannot authorize resetting a different device."""

    pipe = native_pipe
    pipe.evaluate.side_effect = [True, True, teardown_state(matches=matches), True, True]
    if matches:
        leave_device(pipe)
        assert pipe.evaluate.call_count == 5
        pipe.commit_response.assert_called_once()
    else:
        with pytest.raises(ValueError, match="live browser device no longer matches"):
            leave_device(pipe)
        assert pipe.evaluate.call_count == 3
        pipe.commit_response.assert_not_called()
    pipe.forwarded.assert_called_once()


@pytest.mark.parametrize("removed,acknowledged", [(True, False), (False, True), (True, True)])
def test_new_removal_requires_native_completion_and_server_proof(native_pipe, removed, acknowledged) -> None:
    """A local reset alone cannot certify that the server removed the captured device."""

    pipe = native_pipe
    pipe.commit_response.return_value = acknowledged
    checks = {**dict.fromkeys(REMOVAL_CHECKS, True), "Server Acknowledgement": False}
    pipe.evaluate.side_effect = [True, True, teardown_state(), True, removed, checks]
    if removed and acknowledged:
        leave_device(pipe)
    else:
        message = "Server Acknowledgement" if removed else "did not confirm leaving"
        with pytest.raises(ValueError, match=message):
            leave_device(pipe)


@pytest.mark.parametrize("acknowledged", [False, True])
def test_page_loss_cannot_erase_or_invent_server_confirmation(native_pipe, acknowledged) -> None:
    """IPC-latched proof survives page globals; unavailable diagnostics remain unverified."""

    pipe = native_pipe
    pipe.commit_response.return_value = acknowledged
    pipe.evaluate.side_effect = [
        True,
        True,
        teardown_state(),
        True,
        True,
        browser_fixture.BrowserProtocolError("Page lost"),
    ]
    if acknowledged:
        leave_device(pipe)
    else:
        with pytest.raises(browser_fixture.UnconfirmedDeviceRemoval, match="observer unavailable"):
            leave_device(pipe)


def test_lost_observer_requires_a_new_gated_attempt(native_pipe) -> None:
    """Reloading after server traffic could lose a self-deletion, so the attempt stops safely."""

    pipe = native_pipe
    pipe.evaluate.side_effect = [True, True, teardown_state(needs_navigation=True)]
    with pytest.raises(browser_fixture.BrowserProtocolError, match="lost its teardown observer"):
        leave_device(pipe)
    pipe.call.assert_not_called()


@pytest.mark.parametrize("failed", [("Fresh Download", "Server Connection"), ("Transport State",)])
def test_unverified_readiness_never_resets_a_device(native_pipe, monkeypatch, failed) -> None:
    """Neither unavailable service nor inactive transport proves a captured device was removed."""

    clock = [0.0]
    monkeypatch.setattr(browser_fixture.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(browser_fixture.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    pipe = native_pipe
    pipe.evaluate.side_effect = [True, True, teardown_state(failed=failed)]
    with pytest.raises(ValueError, match="could not verify Sync readiness"):
        leave_device(pipe, timeout=1)
    assert pipe.evaluate.call_count == 3
    pipe.wait_for_acknowledgement.assert_called_once_with(pipe.page.return_value, PROTOCOL_BINDING, timeout=1)
    pipe.commit_response.assert_not_called()


@pytest.mark.parametrize("invalid", [None, {"private-device": False}, dict.fromkeys(REMOVAL_CHECKS, "private-value")])
def test_removal_diagnostics_reject_untrusted_fields(invalid) -> None:
    """Malformed payloads cannot enter the teardown error message."""

    pipe = mock.Mock()
    pipe.evaluate.return_value = invalid
    assert browser_fixture.incomplete_removal_checks(pipe, "session") == "removal observer unavailable"


@pytest.mark.parametrize("invalid", [None, {"private-data": False}, {"active": "private-response"}])
def test_readiness_diagnostics_reject_untrusted_fields(native_pipe, invalid) -> None:
    """Unsupported diagnostic schemas fail without logging browser data or requesting reset."""

    pipe = native_pipe
    pipe.evaluate.side_effect = [True, True, invalid]
    with pytest.raises(ValueError, match="unsupported teardown diagnostics") as error:
        leave_device(pipe)
    assert "private" not in str(error.value)
    assert pipe.evaluate.call_count == 3


@pytest.mark.parametrize("result", [None, "private-response", {"successful": True}])
def test_native_reset_rejects_mismatched_or_unsupported_callback_state(result) -> None:
    """Only an exact current identity and boolean native result can finish a reset."""

    pipe = mock.Mock()
    pipe.evaluate.return_value = result
    message = "settings page no longer matches" if result is None else "unsupported native leave diagnostics"
    with pytest.raises(ValueError, match=message):
        browser_fixture.reset_device(pipe, "settings", "captured-device")
