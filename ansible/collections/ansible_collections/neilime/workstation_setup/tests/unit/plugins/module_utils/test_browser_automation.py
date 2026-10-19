"""Private browser IPC, safe process selection, and evidence-based Sync completion."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    browser_cdp as cdp,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    browser_lifecycle as lifecycle,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    browser_native_sync as native,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_cdp import (
    BrowserPipe,
    BrowserProtocolError,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_lifecycle import (
    _request_close,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_native_sync import (
    _DIAGNOSTIC_CHECKS,
)

_ENCRYPTION_READY = {"available": True, "decryptionFailed": False}

# Exercise actual anonymous-pipe framing with a tiny stand-in for the browser.
_CHILD = r"""
import json,os,time
buffer=b''
while True:
    while b'\0' not in buffer:
        chunk=os.read(3,65536)
        if not chunk: raise SystemExit
        buffer+=chunk
    raw,buffer=buffer.split(b'\0',1)
    message=json.loads(raw)
    method=message['method']
    if method=='timeout': continue
    if method=='oversized':
        os.write(4,b'x'*(1024*1024+1)); continue
    if method=='invalid':
        os.write(4,b'private-malformed-response\0'); continue
    response={'id':message['id'],'result':{'accepted':True}}
    if method=='error':
        response={'id':message['id'],'error':message.get('params') or {'message':'private-browser-secret'}}
    if method=='events':
        for event in message['params']['events']:
            os.write(4,json.dumps(event).encode()+b'\0')
    os.write(4,b'{"method":"event","params":{"secret":"private-event"}}\0')
    data=json.dumps(response).encode()+b'\0'
    os.write(4,data[:5]); os.write(4,data[5:])
    if method=='delayed-events':
        time.sleep(0.05)
        for event in message['params']['events']:
            os.write(4,json.dumps(event).encode()+b'\0')
    if method=='Browser.close': break
"""


def test_pipe_handles_events_and_partial_frames_without_a_network_listener() -> None:
    """Only matching command responses are returned, and shutdown reaps the child."""

    with BrowserPipe([sys.executable, "-c", _CHILD], dict(os.environ)) as pipe:
        assert pipe.call("fixture") == {"accepted": True}
    assert pipe.process.returncode == 0


def test_binding_acknowledgement_survives_context_loss_and_is_scoped_to_its_target() -> None:
    """Only the watched target's true signal survives navigation while other event data is discarded."""

    def event(session: object = "diagnostics", name: object = "confirmed", payload: object = "true") -> dict:
        return {"method": "Runtime.bindingCalled", "sessionId": session, "params": {"name": name, "payload": payload}}

    with BrowserPipe([sys.executable, "-c", _CHILD], dict(os.environ)) as pipe:
        acknowledged = pipe.watch_acknowledgement("diagnostics", "confirmed")
        other = pipe.watch_acknowledgement("other", "confirmed")
        pipe.call(
            "events",
            {
                "events": [
                    event("other"),
                    event(name="unwatched"),
                    event(payload="false"),
                    event(payload=True),
                    event(payload="private-browser-data"),
                    event(name=[]),
                    event(session=[]),
                    {"method": "Runtime.bindingCalled", "sessionId": "diagnostics", "params": None},
                ]
            },
        )
        assert acknowledged() is False
        assert other() is True
        pipe.call(
            "events",
            {
                "events": [
                    event(),
                    {"method": "Runtime.executionContextsCleared", "sessionId": "diagnostics"},
                    event(payload="false"),
                ]
            },
        )
        assert acknowledged() is True
        with pytest.raises(ValueError, match="already being watched"):
            pipe.watch_acknowledgement("diagnostics", "confirmed")


def test_closed_diagnostic_target_does_not_prevent_browser_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tab closed during normal exit must not retain the private-pipe keepalive."""

    with BrowserPipe([sys.executable, "-c", _CHILD], dict(os.environ)) as pipe:
        pipe.targets = ["already-closed"]
        original_call = pipe.call

        def call(method: str, params: dict | None = None, session: str | None = None, timeout: float = 30) -> dict:
            if method == "Target.closeTarget":
                raise BrowserProtocolError("Brave rejected the automation request")
            return original_call(method, params, session, timeout)

        monkeypatch.setattr(pipe, "call", call)
    assert pipe.process.returncode == 0


@pytest.mark.parametrize(
    "session,payload,expected",
    [("diagnostics", "true", True), ("other", "true", False), ("diagnostics", "false", False)],
)
def test_acknowledgement_wait_receives_events_after_the_command_response(
    session: str, payload: str, expected: bool
) -> None:
    """Delayed server evidence must arrive from the watched target, within a bounded wait."""

    with BrowserPipe([sys.executable, "-c", _CHILD], dict(os.environ)) as pipe:
        acknowledged = pipe.watch_acknowledgement("diagnostics", "confirmed")
        pipe.call(
            "delayed-events",
            {
                "events": [
                    {
                        "method": "Runtime.bindingCalled",
                        "sessionId": session,
                        "params": {"name": "confirmed", "payload": payload},
                    }
                ]
            },
        )
        assert acknowledged() is False
        assert pipe.wait_for_acknowledgement("diagnostics", "confirmed", timeout=0.2) is expected
        assert acknowledged() is expected


def test_acknowledgement_wait_requires_registration_and_accepts_a_latched_signal() -> None:
    """A completed acknowledgement needs no live page or additional pipe traffic."""

    with BrowserPipe([sys.executable, "-c", _CHILD], dict(os.environ)) as pipe:
        with pytest.raises(ValueError, match="not being watched"):
            pipe.wait_for_acknowledgement("diagnostics", "unwatched")
        pipe.watch_acknowledgement("diagnostics", "confirmed")
        pipe.call(
            "events",
            {
                "events": [
                    {
                        "method": "Runtime.bindingCalled",
                        "sessionId": "diagnostics",
                        "params": {"name": "confirmed", "payload": "true"},
                    }
                ]
            },
        )
        assert pipe.wait_for_acknowledgement("diagnostics", "confirmed", timeout=0) is True


def test_partial_event_traffic_cannot_extend_the_acknowledgement_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unfinished event must time out even when more bytes keep arriving."""

    pipe = object.__new__(BrowserPipe)
    pipe.reader = 42
    pipe.buffer = b""
    pipe.acknowledgements = {("diagnostics", "confirmed"): False}
    ticks = iter(range(10))
    monkeypatch.setattr(cdp.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(cdp.select, "select", lambda *_args: ([pipe.reader], [], []))
    monkeypatch.setattr(cdp.os, "read", lambda *_args: b"unfinished")
    assert pipe.wait_for_acknowledgement("diagnostics", "confirmed", timeout=3) is False
    assert pipe.buffer == b"unfinished"


@pytest.mark.parametrize("method", ["timeout", "error", "invalid", "oversized"])
def test_protocol_failures_are_bounded_and_never_echo_browser_payloads(method: str) -> None:
    """Malformed, oversized, missing, and rejected responses fail without secret diagnostics."""

    with BrowserPipe([sys.executable, "-c", _CHILD], dict(os.environ)) as pipe:
        with pytest.raises(BrowserProtocolError) as error:
            pipe.call(method, timeout=0.5)
        assert "private-" not in str(error.value)
        # Discard the deliberately oversized partial frame so the fixture can
        # receive its normal close request without waiting for its delimiter.
        pipe.buffer = b""
    assert pipe.process.returncode is not None


@pytest.mark.parametrize("reason", ["Promise was collected", "private-browser-secret"])
def test_protocol_rejections_report_only_codes_and_fixed_context_reasons(reason: str) -> None:
    """Context loss is distinguishable without exposing arbitrary protocol error messages."""

    with BrowserPipe([sys.executable, "-c", _CHILD], dict(os.environ)) as pipe:
        with pytest.raises(BrowserProtocolError) as error:
            pipe.call("error", {"code": -32000, "message": reason, "data": "private-browser-data"})
    assert "protocol code -32000" in str(error.value)
    assert ("Promise was collected" in str(error.value)) is (reason == "Promise was collected")
    assert "private" not in str(error.value)


@pytest.mark.parametrize(
    "result", [{"exceptionDetails": {"text": "private-code"}}, {"result": {"description": "private-code"}}]
)
def test_javascript_failures_never_expose_secret_values(result: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Native errors may contain recovery words and must never become module messages."""

    pipe = object.__new__(BrowserPipe)
    monkeypatch.setattr(pipe, "call", Mock(return_value=result))
    with pytest.raises(BrowserProtocolError, match="native Sync interface is unavailable"):
        pipe.evaluate("fixture", "trusted expression")


@pytest.mark.parametrize(
    ("kind", "line", "column", "suffix"),
    [
        ("TypeError", 73, 42, " (TypeError at script line 74, column 43)"),
        ("TypeError", 73, "private", " (TypeError at script line 74)"),
        ("private-error", 0, 0, ""),
        (["private-error"], "private", "private", ""),
    ],
)
def test_javascript_failures_report_only_fixed_classes_and_source_coordinates(
    kind: object, line: object, column: object, suffix: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Runtime locations aid diagnosis without exposing exception messages or browser values."""

    pipe = object.__new__(BrowserPipe)
    response = {
        "exceptionDetails": {
            "lineNumber": line,
            "columnNumber": column,
            "text": "private-browser-data",
            "exception": {"className": kind, "description": "private-recovery-code"},
        }
    }
    monkeypatch.setattr(pipe, "call", Mock(return_value=response))
    with pytest.raises(BrowserProtocolError) as error:
        pipe.evaluate("fixture", "trusted expression")
    assert str(error.value) == "Brave's native Sync interface is unavailable" + suffix


def test_native_profile_identity_must_match_before_accessing_recovery_words() -> None:
    """Restored windows must not cause code reads from another profile."""

    pipe = Mock()
    pipe.evaluate.return_value = False
    with pytest.raises(BrowserProtocolError, match="different profile"):
        native.NativeSync(pipe, "/fixture/Default")
    assert pipe.page.call_count == 1


def test_profile_identity_query_failure_stops_before_sync() -> None:
    """A missing native profile response must fail before opening recovery settings."""

    pipe = Mock()
    pipe.evaluate.side_effect = BrowserProtocolError("Brave's automation request timed out")
    with pytest.raises(BrowserProtocolError, match="checking the selected profile.*timed out"):
        native.NativeSync(pipe, "/fixture/Default")
    pipe.page.assert_called_once_with("brave://version")


def test_native_sync_requires_the_existing_page_callbacks() -> None:
    """Missing WebUI callbacks stop recovery before any code can be accessed."""

    pipe = Mock()
    pipe.evaluate.side_effect = [True, False]
    with pytest.raises(BrowserProtocolError, match="native Sync callbacks are unavailable"):
        native.NativeSync(pipe, "/fixture/Default")
    assert pipe.evaluate.call_count == 2


def test_native_request_failure_identifies_the_operation_without_recovery_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected chain join names its native operation while keeping arguments and browser errors private."""

    pipe = object.__new__(BrowserPipe)
    monkeypatch.setattr(pipe, "page", Mock(return_value="fixture"))
    response = Mock(side_effect=[{"result": {"value": value}} for value in (True, True, _ENCRYPTION_READY)])
    monkeypatch.setattr(pipe, "call", response)
    instance = native.NativeSync(pipe, "/fixture/Default")
    code = " ".join(["private"] * 24)
    response.side_effect = [
        {"result": {"value": code + " suffix"}},
        {"exceptionDetails": {"text": "private-browser-error"}},
        {"exceptionDetails": {"text": "private-diagnostic-error"}},
    ]

    with pytest.raises(BrowserProtocolError, match="calling SyncSetupSetSyncCode") as error:
        instance.restore(code)
    assert "private" not in str(error.value)


def test_recovery_code_access_waits_for_native_desktop_encryption(monkeypatch: pytest.MonkeyPatch) -> None:
    """Code generation starts only after Brave's asynchronous OS encryption initialization completes."""

    code = " ".join(["synthetic"] * 24)
    pipe = Mock()
    pipe.evaluate.side_effect = [
        True,
        True,
        {"available": False, "decryptionFailed": False},
        _ENCRYPTION_READY,
        code,
    ]
    sleep = Mock()
    monkeypatch.setattr(native.time, "sleep", sleep)
    instance = native.NativeSync(pipe, "/fixture/Default")
    assert instance.code() == code
    sleep.assert_called_once()
    assert "SyncSetupGetPureSyncCode" in pipe.evaluate.call_args.args[1]


@pytest.mark.parametrize("status", [{"available": False, "decryptionFailed": False}, {}])
def test_unavailable_encryption_stops_before_recovery_code_access(
    status: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A locked or unsupported encryption backend times out without reading or replacing a chain."""

    pipe = Mock()
    pipe.evaluate.side_effect = [True, True, status]
    ticks = iter([0, 0, 31])
    monkeypatch.setattr(native.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(native.time, "sleep", lambda _seconds: None)
    with pytest.raises(BrowserProtocolError, match="unlock the desktop keyring"):
        native.NativeSync(pipe, "/fixture/Default")
    assert pipe.evaluate.call_count == 3


def test_saved_seed_decryption_failure_stops_before_recovery_code_access() -> None:
    """An available keyring must still decrypt an existing seed before any chain change is allowed."""

    pipe = Mock()
    pipe.evaluate.side_effect = [True, True, {"available": True, "decryptionFailed": True}]
    with pytest.raises(BrowserProtocolError, match="could not decrypt its saved recovery code"):
        native.NativeSync(pipe, "/fixture/Default")
    assert pipe.evaluate.call_count == 3


@pytest.mark.parametrize(
    "dirty",
    [
        {"healthy": False, "pending": False, "fresh": True},
        {"healthy": True, "pending": True, "fresh": True},
        {"healthy": True, "pending": False, "fresh": False},
    ],
)
def test_native_wait_rejects_errors_pending_uploads_and_stale_success(
    dirty: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A current download and repeated clean state are both required for verification."""

    pipe = Mock()
    checks = dict.fromkeys(_DIAGNOSTIC_CHECKS, True)
    incomplete = "Entity Metadata" if dirty["pending"] else "Fresh Download" if not dirty["fresh"] else "Auth Error"
    checks[incomplete] = False
    pipe.evaluate.side_effect = [True, True, _ENCRYPTION_READY, True, dirty, checks, []]
    ticks = iter([0, 0, 0, 0, 0, 2, 2])
    monkeypatch.setattr(native.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(native.time, "sleep", lambda _seconds: None)
    instance = native.NativeSync(pipe, "/fixture/Default")
    assert instance.wait(timeout=1) is False
    assert instance.pending_reason == incomplete


@pytest.mark.parametrize("invalid", [{"private-recovery-word": False}, {"Auth Error": "private-browser-error"}])
def test_timeout_diagnostics_reject_unrecognized_fields_and_private_values(
    invalid: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only known check names with boolean results may appear in an uncensored recovery error."""

    pipe = Mock()
    dirty = {"healthy": False, "pending": True, "fresh": False}
    checks = {**dict.fromkeys(_DIAGNOSTIC_CHECKS, True), **invalid}
    pipe.evaluate.side_effect = [True, True, _ENCRYPTION_READY, True, dirty, checks]
    ticks = iter([0, 0, 0, 0, 0, 2, 2])
    monkeypatch.setattr(native.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(native.time, "sleep", lambda _seconds: None)
    instance = native.NativeSync(pipe, "/fixture/Default")
    with pytest.raises(BrowserProtocolError, match="unsupported Sync diagnostics") as error:
        instance.wait(timeout=1)
    assert "private-" not in str(error.value)


def test_native_wait_requires_two_clean_observations(monkeypatch: pytest.MonkeyPatch) -> None:
    """The first clean status alone cannot race a pending commit."""

    clean = {"healthy": True, "pending": False, "fresh": True}
    pipe = Mock()
    pipe.evaluate.side_effect = [True, True, _ENCRYPTION_READY, True, clean, {**clean, "pending": True}, clean, clean]
    monkeypatch.setattr(native.time, "sleep", lambda _seconds: None)
    instance = native.NativeSync(pipe, "/fixture/Default")
    assert instance.wait() is True
    assert pipe.evaluate.call_count == 8


@pytest.mark.parametrize("commit_errors", [["TRANSIENT_ERROR"], ["private-server-error"]])
def test_failed_sync_reports_only_known_commit_error_categories(
    commit_errors: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failed recovery retains safe server error evidence from the original browser process."""

    pipe = Mock()
    dirty = {"healthy": False, "pending": True, "fresh": True}
    checks = {**dict.fromkeys(_DIAGNOSTIC_CHECKS, True), "Commit Step Result": False}
    pipe.evaluate.side_effect = [True, True, _ENCRYPTION_READY, True, dirty, checks, commit_errors]
    pipe.call.return_value = {
        "histograms": [
            {
                "name": "Sync.PostedClientToServerMessageError2",
                "buckets": [{"low": 8, "count": 1}, {"low": "private-code", "count": 1}, {"low": True, "count": 1}],
            }
        ]
    }
    ticks = iter([0, 0, 0, 0, 0, 2, 2])
    monkeypatch.setattr(native.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(native.time, "sleep", lambda _seconds: None)
    instance = native.NativeSync(pipe, "/fixture/Default")
    if commit_errors == ["TRANSIENT_ERROR"]:
        assert instance.wait(timeout=1) is False
        assert instance.pending_reason == (
            "Commit Step Result; commit responses: TRANSIENT_ERROR; Sync protocol error codes: 8"
        )
    else:
        with pytest.raises(BrowserProtocolError, match="unsupported commit diagnostics") as error:
            instance.wait(timeout=1)
        assert "private" not in str(error.value)


def test_restore_uses_native_pairing_and_checks_the_result() -> None:
    """Restore waits for remote leave/join acknowledgements and verifies the current pairing and resulting code."""

    code = " ".join(["synthetic"] * 24)
    pipe = Mock()
    responses = iter([True, True, _ENCRYPTION_READY, True, code + " suffix", True, code, True])

    def evaluate(_session: str, expression: str, timeout: float = 30) -> object:
        # Native leave/join completes only after contacting the server. Model
        # an acknowledgement slower than a local automation round trip.
        if any(method in expression for method in ("SyncSetupReset", "SyncSetupSetSyncCode")) and timeout < 45:
            raise BrowserProtocolError("Brave's automation request timed out")
        return next(responses)

    pipe.evaluate.side_effect = evaluate
    instance = native.NativeSync(pipe, "/fixture/Default")
    instance.restore(code, reset=True)
    expressions = "\n".join(call.args[1] for call in pipe.evaluate.call_args_list)
    assert "SyncSetupReset" in expressions
    assert "SyncSetupSetSyncCode" in expressions
    assert "PermanentlyDelete" not in expressions


@pytest.mark.parametrize("healthy", [False, True])
def test_failed_enrollment_reports_checks_without_accepting_a_healthy_engine(
    healthy: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Diagnostic observations cannot replace the native chain enrollment acknowledgement."""

    pipe = Mock()
    code = " ".join(["synthetic"] * 24)
    pipe.evaluate.side_effect = [
        True,
        True,
        _ENCRYPTION_READY,
        code + " suffix",
        BrowserProtocolError("Native Sync request rejected"),
    ]
    instance = native.NativeSync(pipe, "/fixture/Default")
    wait = Mock(return_value=healthy)
    monkeypatch.setattr(instance, "wait", wait)
    instance.pending_reason = "Server Connection"
    detail = "enrollment acknowledgement" if healthy else "Server Connection"
    with pytest.raises(BrowserProtocolError, match=f"request rejected; incomplete checks: {detail}"):
        instance.restore(code)
    wait.assert_called_once_with(timeout=5)


@pytest.mark.parametrize("response_code,throttled", [(3, True), (8, False)])
def test_enrollment_throttling_reports_an_action_without_server_payloads(
    response_code: int, throttled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Protocol throttling explains a stalled join without exposing recovery words or server data."""

    pipe = Mock()
    code = " ".join(["private"] * 24)
    pipe.evaluate.side_effect = [
        True,
        True,
        _ENCRYPTION_READY,
        code + " suffix",
        BrowserProtocolError("Native enrollment timed out"),
    ]
    pipe.call.return_value = {
        "histograms": [
            {
                "name": "Sync.PostedClientToServerMessageError2",
                "buckets": [{"low": response_code, "high": response_code + 1, "count": 1}],
                "extra": "private-server-payload",
            }
        ]
    }
    instance = native.NativeSync(pipe, "/fixture/Default")
    monkeypatch.setattr(instance, "wait", Mock(return_value=False))
    with pytest.raises(BrowserProtocolError) as error:
        instance.restore(code)
    assert ("device limit" in str(error.value)) is throttled
    assert "private" not in str(error.value)


def test_process_selection_is_scoped_to_the_managed_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unrelated browsers, roots, and renderer processes are never selected for shutdown."""

    entries = [
        ["/opt/brave.com/brave/brave", "--user-data-dir=/fixture"],
        ["/opt/brave.com/brave/brave", "--user-data-dir=/other"],
        ["brave", "--type=renderer", "--user-data-dir=/fixture"],
        ["unrelated", "--user-data-dir=/fixture"],
        ["brave", "--user-data-dir", "/fixture"],
        ["/opt/brave.com/brave/brave --user-data-dir=/fixture --profile-directory=Profile 2"],
        ["brave --user-data-dir=/fixture with spaces --profile-directory=Default"],
        ["brave --type=renderer --user-data-dir=/fixture"],
    ]
    for number, arguments in enumerate(entries, 1):
        process = tmp_path / str(number)
        process.mkdir()
        (process / "cmdline").write_bytes("\0".join(arguments).encode() + b"\0")
    monkeypatch.setattr(lifecycle, "Path", lambda value: tmp_path if value == "/proc" else Path(value))
    assert set(lifecycle.browser_processes(Path("/fixture"))) == {1, 5, 6}
    assert lifecycle.browser_processes(Path("/fixture with spaces")) == [7]


def test_profile_lock_is_retained_without_launching_a_browser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A live or foreign lock cannot be bypassed by automatic synchronization."""

    lock = tmp_path / "SingletonLock"
    lock.symlink_to("fixture-owner")
    monkeypatch.setattr(lifecycle, "browser_processes", lambda _root: [])
    monkeypatch.setattr(lifecycle.DesktopSession, "environment", dict)
    launch = Mock()
    monkeypatch.setattr(lifecycle.subprocess, "Popen", launch)
    with pytest.raises(lifecycle.BrowserLifecycleBlocked, match="still locked"):
        with lifecycle.closed_browser(str(tmp_path)):
            pytest.fail("Locked profiles must not enter the operation")
    assert lock.is_symlink()
    launch.assert_not_called()


def test_stale_local_profile_lock_is_cleared_before_operation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A lock this host left behind after Brave exited is cleared so recovery can proceed."""

    lock = tmp_path / "SingletonLock"
    lock.symlink_to(f"{socket.gethostname()}-2147483646")
    (tmp_path / "SingletonSocket").symlink_to("/run/user/0/stale.sock")
    monkeypatch.setattr(lifecycle, "browser_processes", lambda _root: [])
    monkeypatch.setattr(lifecycle.DesktopSession, "environment", lambda: {"DISPLAY": ":0"})
    launch = Mock()
    monkeypatch.setattr(lifecycle.subprocess, "Popen", launch)
    entered = False
    with lifecycle.closed_browser(str(tmp_path)) as (executable, _environment):
        entered = True
        assert executable
        assert not os.path.lexists(lock)
        assert not os.path.lexists(tmp_path / "SingletonSocket")
    assert entered
    launch.assert_not_called()


def test_existing_browser_is_reopened_even_when_sync_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Failed verification still restores the user's GUI, without remote debugging flags."""

    (tmp_path / "Local State").write_text(json.dumps({"profile": {"last_active_profiles": ["Default", "Profile 2"]}}))
    processes = iter([[123], [], [], []])
    monkeypatch.setattr(lifecycle, "browser_processes", lambda _root: next(processes))
    monkeypatch.setattr(lifecycle.DesktopSession, "environment", lambda: {"DISPLAY": ":0"})
    terminate = Mock()
    launch = Mock()
    launch.return_value.wait.side_effect = subprocess.TimeoutExpired("fixture", 2)
    monkeypatch.setattr(lifecycle, "_request_close", terminate)
    monkeypatch.setattr(lifecycle.subprocess, "Popen", launch)
    with pytest.raises(ValueError, match="fixture failure"):
        with lifecycle.closed_browser(str(tmp_path)):
            raise ValueError("fixture failure")
    terminate.assert_called_once_with(123)
    assert launch.call_count == 2
    for call, profile in zip(launch.call_args_list, ["Default", "Profile 2"]):
        assert "--restore-last-session" in call.args[0]
        assert f"--profile-directory={profile}" in call.args[0]
        assert all("debugging" not in argument for argument in call.args[0])


@pytest.mark.parametrize("handled", [False, True])
def test_close_never_sends_an_unhandled_signal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, handled: bool) -> None:
    """A second retry after Chromium resets its handler cannot force-kill the browser."""

    process = tmp_path / "123"
    process.mkdir()
    (process / "status").write_text(f"SigCgt:\t{2 if handled else 0:016x}\n")
    monkeypatch.setattr(lifecycle, "Path", lambda value: tmp_path if value == "/proc" else Path(value))
    signal_process = Mock()
    monkeypatch.setattr(lifecycle.os, "kill", signal_process)
    if handled:
        _request_close(123)
        signal_process.assert_called_once_with(123, lifecycle.signal.SIGINT)
    else:
        with pytest.raises(lifecycle.BrowserLifecycleBlocked, match="another safe close request"):
            _request_close(123)
        signal_process.assert_not_called()
