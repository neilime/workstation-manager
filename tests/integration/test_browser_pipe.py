"""Exercise browser protocol framing, acknowledgements, and cleanup across real anonymous pipes."""

from __future__ import annotations

import os
import sys

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_cdp import (
    BrowserPipe,
    BrowserProtocolError,
)

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

    with (
        BrowserPipe([sys.executable, "-c", _CHILD], dict(os.environ)) as pipe,
        pytest.raises(BrowserProtocolError) as error,
    ):
        pipe.call("error", {"code": -32000, "message": reason, "data": "private-browser-data"})
    assert "protocol code -32000" in str(error.value)
    assert ("Promise was collected" in str(error.value)) is (reason == "Promise was collected")
    assert "private" not in str(error.value)
