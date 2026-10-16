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
    monkeypatch.setattr(browser_fixture, "BrowserPipe", lambda *_args: nullcontext(pipe))
    leave = mock.Mock()
    monkeypatch.setattr(browser_fixture, "leave_device", leave)
    fixture.leave()
    leave.assert_called_once_with(pipe, root / "Default", "test-device")
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


@pytest.mark.parametrize("matches", [False, True])
def test_live_device_identity_is_required_before_leaving(matches: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    """Native teardown requires an active tracker and the exact captured device GUID."""

    monkeypatch.setattr(browser_fixture, "NativeSync", mock.Mock())
    pipe = mock.Mock()
    pipe.evaluate.side_effect = [True, {"active": True, "matches": matches, "ready": True}, True, True, True]
    if matches:
        browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device")
        assert pipe.evaluate.call_count == 5
    else:
        with pytest.raises(ValueError, match="live browser device no longer matches"):
            browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device")
        assert pipe.evaluate.call_count == 2


def test_native_leave_callback_requires_server_deletion_acknowledgement(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful local leave callback cannot certify an uncommitted server deletion."""

    monkeypatch.setattr(browser_fixture, "NativeSync", mock.Mock())
    pipe = mock.Mock()
    pipe.evaluate.side_effect = [True, {"active": True, "matches": True, "ready": True}, True, True, False]
    with pytest.raises(ValueError, match="server did not confirm removal"):
        browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device")


def test_teardown_requires_native_callbacks_before_requesting_removal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unavailable native callbacks cannot authorize a captured device's removal."""

    monkeypatch.setattr(browser_fixture, "NativeSync", mock.Mock())
    pipe = mock.Mock()
    pipe.evaluate.return_value = False
    with pytest.raises(ValueError, match="could not request fresh Sync for teardown"):
        browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device")
    assert pipe.evaluate.call_count == 1
    assert "SyncSetupReset" not in pipe.evaluate.call_args.args[1]


def test_teardown_does_not_leave_when_sync_cannot_be_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unavailable server cannot turn a local reset into successful remote teardown."""

    monkeypatch.setattr(browser_fixture, "NativeSync", mock.Mock())
    ticks = iter([0, 0, 1, 121])
    monkeypatch.setattr(browser_fixture.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(browser_fixture.time, "sleep", lambda _seconds: None)
    pipe = mock.Mock()
    checks = dict.fromkeys(TEARDOWN_CHECKS, True)
    checks["Fresh Download"] = False
    checks["Server Connection"] = False
    pipe.evaluate.side_effect = [True, {"active": True, "matches": True, "ready": False}, checks]
    with pytest.raises(ValueError, match="incomplete checks: Fresh Download, Server Connection$"):
        browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device")
    assert pipe.evaluate.call_count == 3
    assert all("SyncSetupReset" not in call.args[1] for call in pipe.evaluate.call_args_list)


@pytest.mark.parametrize("invalid", [None, {"private-device-data": False}, {"Fresh Download": "private-response"}])
def test_teardown_diagnostics_never_report_untrusted_browser_fields(
    invalid: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed readiness evidence stays private and cannot authorize server removal."""

    monkeypatch.setattr(browser_fixture, "NativeSync", mock.Mock())
    ticks = iter([0, 0, 1, 121])
    monkeypatch.setattr(browser_fixture.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(browser_fixture.time, "sleep", lambda _seconds: None)
    pipe = mock.Mock()
    checks = {**dict.fromkeys(TEARDOWN_CHECKS, True), **invalid} if isinstance(invalid, dict) else invalid
    pipe.evaluate.side_effect = [True, {"active": True, "matches": True, "ready": False}, checks]
    with pytest.raises(ValueError, match="incomplete checks: unsupported teardown diagnostics$") as error:
        browser_fixture.leave_device(pipe, Path("/fixture/Default"), "test-device")
    assert "private" not in str(error.value)
    assert all("SyncSetupReset" not in call.args[1] for call in pipe.evaluate.call_args_list)


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
