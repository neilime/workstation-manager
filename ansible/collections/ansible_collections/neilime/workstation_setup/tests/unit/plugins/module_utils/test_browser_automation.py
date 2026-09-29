"""Private browser IPC, safe process selection, and evidence-based Sync completion."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
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

# Exercise actual anonymous-pipe framing with a tiny stand-in for the browser.
_CHILD = r"""
import json,os
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
    if method=='error': response={'id':message['id'],'error':{'message':'private-browser-secret'}}
    os.write(4,b'{"method":"event","params":{"secret":"private-event"}}\0')
    data=json.dumps(response).encode()+b'\0'
    os.write(4,data[:5]); os.write(4,data[5:])
    if method=='Browser.close': break
"""


def test_pipe_handles_events_and_partial_frames_without_a_network_listener() -> None:
    """Only matching command responses are returned, and shutdown reaps the child."""

    with BrowserPipe([sys.executable, "-c", _CHILD], dict(os.environ)) as pipe:
        assert pipe.call("fixture") == {"accepted": True}
    assert pipe.process.returncode == 0


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


@pytest.mark.parametrize(
    "result", [{"exceptionDetails": {"text": "private-code"}}, {"result": {"description": "private-code"}}]
)
def test_javascript_failures_never_expose_secret_values(result: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Native errors may contain recovery words and must never become module messages."""

    pipe = object.__new__(BrowserPipe)
    monkeypatch.setattr(pipe, "call", Mock(return_value=result))
    with pytest.raises(BrowserProtocolError, match="native Sync interface is unavailable"):
        pipe.evaluate("fixture", "trusted expression")


def test_native_profile_identity_must_match_before_accessing_recovery_words() -> None:
    """Restored windows must not cause code reads from another profile."""

    pipe = Mock()
    pipe.evaluate.return_value = False
    with pytest.raises(BrowserProtocolError, match="different profile"):
        native.NativeSync(pipe, "/fixture/Default")
    assert pipe.page.call_count == 1


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
    pipe.evaluate.side_effect = [True, True, dirty]
    ticks = iter([0, 0, 0, 2, 2])
    monkeypatch.setattr(native.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(native.time, "sleep", lambda _seconds: None)
    instance = native.NativeSync(pipe, "/fixture/Default")
    assert instance.wait(timeout=1) is False


def test_native_wait_requires_two_clean_observations(monkeypatch: pytest.MonkeyPatch) -> None:
    """The first clean status alone cannot race a pending commit."""

    clean = {"healthy": True, "pending": False, "fresh": True}
    pipe = Mock()
    pipe.evaluate.side_effect = [True, True, clean, {**clean, "pending": True}, clean, clean]
    monkeypatch.setattr(native.time, "sleep", lambda _seconds: None)
    instance = native.NativeSync(pipe, "/fixture/Default")
    assert instance.wait() is True
    assert pipe.evaluate.call_count == 6


def test_restore_uses_native_pairing_and_checks_the_result() -> None:
    """An explicit restore resets an old enrollment, uses the current suffix, and checks the resulting code."""

    code = " ".join(["synthetic"] * 24)
    pipe = Mock()
    pipe.evaluate.side_effect = [True, True, code + " suffix", True, code, True]
    instance = native.NativeSync(pipe, "/fixture/Default")
    instance.restore(code, reset=True)
    expressions = "\n".join(call.args[1] for call in pipe.evaluate.call_args_list)
    assert "SyncSetupReset" in expressions
    assert "SyncSetupSetSyncCode" in expressions
    assert "PermanentlyDelete" not in expressions


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


def test_desktop_environment_does_not_pass_vault_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Browser children receive session access, never the backup process's vault secrets."""

    monkeypatch.setenv("BW_SESSION", "private-vault-session")
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "private-vault-token")
    environment = lifecycle.browser_environment()
    assert "BW_SESSION" not in environment
    assert "BWS_ACCESS_TOKEN" not in environment
    assert "private-vault" not in json.dumps(environment)


def test_profile_lock_is_retained_without_launching_a_browser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale or foreign lock cannot be bypassed by automatic synchronization."""

    lock = tmp_path / "SingletonLock"
    lock.symlink_to("fixture-owner")
    monkeypatch.setattr(lifecycle, "browser_processes", lambda _root: [])
    launch = Mock()
    monkeypatch.setattr(lifecycle.subprocess, "Popen", launch)
    with pytest.raises(lifecycle.BrowserLifecycleBlocked, match="still locked"):
        with lifecycle.closed_browser(str(tmp_path)):
            pytest.fail("Locked profiles must not enter the operation")
    assert lock.is_symlink()
    launch.assert_not_called()


def test_existing_browser_is_reopened_even_when_sync_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Failed verification still restores the user's GUI, without remote debugging flags."""

    (tmp_path / "Local State").write_text(json.dumps({"profile": {"last_active_profiles": ["Default", "Profile 2"]}}))
    processes = iter([[123], [], [], []])
    monkeypatch.setattr(lifecycle, "browser_processes", lambda _root: next(processes))
    monkeypatch.setattr(lifecycle, "browser_environment", lambda: {"DISPLAY": ":0"})
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
