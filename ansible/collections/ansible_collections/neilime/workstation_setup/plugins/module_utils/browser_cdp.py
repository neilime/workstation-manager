"""Speak to Brave over inherited anonymous pipes, without a debugging listener."""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
from types import TracebackType

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


class BrowserPipe:
    """Own one browser process and its private DevTools connection."""

    def __init__(self, arguments: list[str], environment: dict[str, str]) -> None:
        read_command, self.writer = os.pipe()
        self.reader, write_response = os.pipe()
        self.buffer = b""
        self.sequence = 0
        self.targets: list[str] = []
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

    def __enter__(self) -> BrowserPipe:
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
        """Read a bounded response while discarding unrelated protocol events."""

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
                if b"\0" not in self.buffer:
                    if not select.select([self.reader], [], [], max(0, deadline - time.monotonic()))[0]:
                        break
                    chunk = os.read(self.reader, 65536)
                    if not chunk:
                        raise BrowserProtocolError("Brave closed its automation connection")
                    self.buffer += chunk
                    if len(self.buffer) > 1024 * 1024:
                        raise BrowserProtocolError("Brave returned an oversized automation response")
                    continue
                raw, self.buffer = self.buffer.split(b"\0", 1)
                message = json.loads(raw)
                if not isinstance(message, dict):
                    raise BrowserProtocolError("Brave returned an invalid automation response")
                if message.get("id") != self.sequence:
                    continue
                if "error" in message or not isinstance(message.get("result"), dict):
                    raise BrowserProtocolError("Brave rejected the automation request")
                return message["result"]
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise BrowserProtocolError("Brave's automation connection failed") from error
        raise BrowserProtocolError("Brave's automation request timed out")

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
            raise BrowserProtocolError("Brave's native Sync interface is unavailable")
        return result["value"]

    def page(self, url: str) -> str:
        """Open an internal page in this process's selected native profile."""

        target = self.call("Target.createTarget", {"url": url})["targetId"]
        self.targets.append(target)
        session = self.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            ready = self.evaluate(session, "document.readyState === 'complete' && location.protocol === 'chrome:'")
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
