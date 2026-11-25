"""Speak to Brave over inherited anonymous pipes, without a debugging listener."""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
from collections.abc import Callable
from types import TracebackType
from typing import Self
from urllib.parse import urlsplit, urlunsplit

# dup2 must run after Python's descriptor cleanup, before exec. No data or secrets
# are passed through this bootstrap, command arguments, or browser stderr.
_BOOTSTRAP = (
    "import os,sys; r,w=map(int,sys.argv[1:3]); "
    "os.dup2(r,3); os.dup2(w,4); "
    "[os.close(fd) for fd in (r,w) if fd not in (3,4)]; "
    "os.execv(sys.argv[3],sys.argv[3:])"
)


class BrowserProtocolError(ValueError):
    """Expose only a fixed diagnostic, never browser responses or JavaScript values."""


def _protocol_rejection(error: object) -> str:
    """Reduce protocol errors to numeric codes and exact known context-loss reasons."""

    code = error.get("code") if isinstance(error, dict) else None
    reason = error.get("message") if isinstance(error, dict) else None
    detail = "Brave rejected the automation request"
    if isinstance(code, int) and not isinstance(code, bool) and -32768 <= code < 0:
        detail += f" (protocol code {code})"
    if isinstance(reason, str) and reason in {
        "Execution context was destroyed.",
        "Cannot find context with specified id",
        "Inspected target navigated or closed",
        "Promise was collected",
    }:
        detail += ": " + reason
    return detail


class BrowserPipe:
    """Own one browser process and its private DevTools connection."""

    def __init__(self, arguments: list[str], environment: dict[str, str]) -> None:
        read_command, self.writer = os.pipe()
        self.reader, write_response = os.pipe()
        self.buffer = b""
        self.sequence = 0
        self.targets: list[str] = []
        self.acknowledgements: dict[tuple[str, str], bool] = {}
        try:
            # Persistent private IPC retains this process across calls; __exit__ closes and reaps it.
            # The Ansible-only checker is absent from standalone Pylint.
            # pylint: disable-next=unknown-option-value
            # pylint: disable-next=consider-using-with,ansible-bad-function
            self.process = subprocess.Popen(
                [sys.executable, "-c", _BOOTSTRAP, str(read_command), str(write_response), *arguments],
                pass_fds=(read_command, write_response),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            os.close(self.reader)
            os.close(self.writer)
            raise
        finally:
            os.close(read_command)
            os.close(write_response)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, _kind: type[BaseException] | None, _error: BaseException | None, _traceback: TracebackType | None
    ) -> None:
        try:
            self.close()
        finally:
            os.close(self.reader)
            os.close(self.writer)

    def call(self, method: str, params: dict | None = None, session: str | None = None, timeout: float = 30) -> dict:
        """Read a bounded response, retaining only explicitly watched acknowledgements."""

        self.sequence += 1
        request = {"id": self.sequence, "method": method, "params": params or {}}
        if session:
            request["sessionId"] = session
        try:
            data = memoryview(json.dumps(request).encode() + b"\0")
            while data:
                data = data[os.write(self.writer, data) :]
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                message = self._read_message(deadline)
                if message is None:
                    break
                if message.get("id") != self.sequence:
                    self._record_acknowledgement(message)
                    continue
                if "error" in message:
                    raise BrowserProtocolError(_protocol_rejection(message["error"]))
                if not isinstance(message.get("result"), dict):
                    raise BrowserProtocolError("Brave rejected the automation request")
                return message["result"]
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise BrowserProtocolError("Brave's automation connection failed") from error
        raise BrowserProtocolError("Brave's automation request timed out")

    def _read_message(self, deadline: float) -> dict | None:
        """Read one private-pipe frame within the caller's deadline."""

        try:
            while b"\0" not in self.buffer:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([self.reader], [], [], remaining)[0]:
                    return None
                chunk = os.read(self.reader, 65536)
                if not chunk:
                    raise BrowserProtocolError("Brave closed its automation connection")
                self.buffer += chunk
                if len(self.buffer) > 1024 * 1024:
                    raise BrowserProtocolError("Brave returned an oversized automation response")
            raw, self.buffer = self.buffer.split(b"\0", 1)
            message = json.loads(raw)
            if not isinstance(message, dict):
                raise BrowserProtocolError("Brave returned an invalid automation response")
            return message
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise BrowserProtocolError("Brave's automation connection failed") from error

    def watch_acknowledgement(self, session: str, name: str) -> Callable[[], bool]:
        """Latch a true binding signal outside page state for this connection's lifetime."""

        key = (session, name)
        if key in self.acknowledgements:
            raise ValueError("The browser acknowledgement is already being watched")
        self.acknowledgements[key] = False
        # V8 reinstalls bindings in new page contexts only while Runtime is
        # enabled. Diagnostic navigation must not silently lose the observer.
        self.call("Runtime.enable", session=session)
        self.call("Runtime.addBinding", {"name": name}, session)
        return lambda: self.acknowledgements[key]

    def wait_for_acknowledgement(self, session: str, name: str, timeout: float = 30) -> bool:
        """Wait for a watched event without relying on a command response or page context."""

        key = (session, name)
        if key not in self.acknowledgements:
            raise ValueError("The browser acknowledgement is not being watched")
        deadline = time.monotonic() + timeout
        while not self.acknowledgements[key] and time.monotonic() < deadline:
            message = self._read_message(deadline)
            if message is None:
                break
            self._record_acknowledgement(message)
        return self.acknowledgements[key]

    def _record_acknowledgement(self, message: dict) -> None:
        """Discard event payloads except a fixed true signal from a registered target and binding."""

        if message.get("method") != "Runtime.bindingCalled":
            return
        session = message.get("sessionId")
        params = message.get("params")
        if not isinstance(session, str) or not isinstance(params, dict):
            return
        name = params.get("name")
        if isinstance(name, str) and (session, name) in self.acknowledgements and params.get("payload") == "true":
            self.acknowledgements[(session, name)] = True

    def evaluate(self, session: str, expression: str, timeout: float = 30) -> object:
        """Return only explicitly selected values from trusted internal-page code."""

        response = self.call(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": True, "returnByValue": True},
            session,
            timeout,
        )
        result = response.get("result", {})
        if "exceptionDetails" in response or not isinstance(result, dict) or "value" not in result:
            message = "Brave's native Sync interface is unavailable"
            details = response.get("exceptionDetails", {})
            if isinstance(details, dict):
                exception = details.get("exception", {})
                kind = exception.get("className") if isinstance(exception, dict) else None
                line = details.get("lineNumber")
                column = details.get("columnNumber")
                # Exception text can contain recovery words or browser data.
                # Only fixed runtime classes and bounded source coordinates are
                # useful for identifying a failing trusted automation expression.
                if isinstance(kind, str) and kind in {
                    "Error",
                    "TypeError",
                    "ReferenceError",
                    "SyntaxError",
                    "RangeError",
                }:
                    message += f" ({kind}"
                    if isinstance(line, int) and not isinstance(line, bool) and 0 <= line < 10000:
                        message += f" at script line {line + 1}"
                        if isinstance(column, int) and not isinstance(column, bool) and 0 <= column < 10000:
                            message += f", column {column + 1}"
                    message += ")"
            raise BrowserProtocolError(message)
        return result["value"]

    def page(self, url: str) -> str:
        """Open an internal page in this process's selected native profile."""

        parsed = urlsplit(url)
        expected = urlunsplit(
            (
                "chrome" if parsed.scheme == "brave" else parsed.scheme,
                parsed.netloc,
                parsed.path or "/",
                parsed.query,
                parsed.fragment,
            )
        )
        target = self.call("Target.createTarget", {"url": url})["targetId"]
        self.targets.append(target)
        session = self.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            ready = self.evaluate(
                session,
                "document.readyState === 'complete' && location.protocol === 'chrome:' "
                f"&& location.href === {json.dumps(expected)}",
            )
            if ready:
                return session
            time.sleep(0.1)
        raise BrowserProtocolError("Brave's native Sync page did not load")

    def close(self) -> None:
        """Request a normal exit; never force-kill a process using real profile data."""

        if self.process.poll() is not None:
            return
        for target in self.targets:
            try:
                self.call("Target.closeTarget", {"targetId": target}, timeout=5)
            except BrowserProtocolError:
                # A normal window close may already have removed this target.
                # Still request browser shutdown so its private-pipe keepalive ends.
                continue
        try:
            self.call("Browser.close", timeout=5)
        except BrowserProtocolError:
            # Losing IPC is not permission to terminate a browser holding user data.
            pass
        try:
            self.process.wait(timeout=30)
        except subprocess.TimeoutExpired as error:
            raise BrowserProtocolError(
                "Brave did not close safely; backup stopped without forcing it to exit"
            ) from error
