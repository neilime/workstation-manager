"""Bounded stdio MCP verification with private process output and clean shutdown."""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import time
from typing import Self


class McpStdioSession:
    """Initialize a local MCP server and verify tools without forwarding its output."""

    def __init__(self, command: str, args: list[str], environment: dict[str, str], timeout: int = 30) -> None:
        self._argv, self._environment = [command, *args], environment
        self._timeout = timeout
        self._process: subprocess.Popen[bytes] | None = None
        self._selector: selectors.BaseSelector | None = None
        self._pending = b""
        self._identifier = 0

    def __enter__(self) -> Self:
        try:
            # MCP exchanges messages over live pipes; run_command waits for process exit.
            # The Ansible-only checker is absent from standalone Pylint.
            # pylint: disable-next=unknown-option-value
            # pylint: disable-next=ansible-bad-function
            self._process = subprocess.Popen(
                self._argv,
                env=self._environment,
                cwd=self._environment.get("HOME"),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self._selector = selectors.DefaultSelector()
            if self._process.stdout is None:
                raise ValueError("MCP server output pipe is unavailable")
            self._selector.register(self._process.stdout, selectors.EVENT_READ)
            initialized = self.request(
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "workstation-manager", "version": "1.0.0"},
                },
            )
            if initialized.get("protocolVersion") not in (
                "2025-11-25",
                "2025-06-18",
                "2025-03-26",
                "2024-11-05",
            ) or not isinstance(initialized.get("capabilities"), dict):
                raise ValueError("MCP initialization returned an invalid response")
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            return self
        except OSError, ValueError:
            self.close()
            raise ValueError("MCP initialization failed; inspect the selected client's server log privately") from None

    def __exit__(self, *_args) -> None:
        self.close()

    def close(self) -> None:
        """Stop only the server process group started for this verification."""
        if self._selector:
            self._selector.close()
        if self._process:
            try:
                os.killpg(self._process.pid, 15)
            except ProcessLookupError:
                pass
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self._process.pid, 9)
                except ProcessLookupError:
                    pass
                self._process.wait(timeout=3)
            for stream in (self._process.stdin, self._process.stdout):
                if stream is not None:
                    stream.close()
            self._process = None

    def _send(self, message: dict) -> None:
        if self._process is None or self._process.stdin is None:
            raise ValueError("MCP session is not running")
        self._process.stdin.write(json.dumps(message).encode() + b"\n")
        self._process.stdin.flush()

    def request(self, method: str, parameters: dict) -> dict:
        """Handle notifications and reject server errors without including their payloads."""
        if self._selector is None or self._process is None or self._process.stdout is None:
            raise ValueError("MCP session is not running")
        self._identifier += 1
        identifier = self._identifier
        self._send({"jsonrpc": "2.0", "id": identifier, "method": method, "params": parameters})
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            while b"\n" in self._pending:
                line, self._pending = self._pending.split(b"\n", 1)
                try:
                    message = json.loads(line)
                except ValueError, UnicodeError:
                    raise ValueError("MCP server returned invalid protocol data") from None
                if not isinstance(message, dict):
                    # Malformed wire data is a protocol error, not a caller type error.
                    raise ValueError("MCP server returned invalid protocol data")  # noqa: TRY004
                if message.get("id") == identifier and ("result" in message or "error" in message):
                    if "error" in message or not isinstance(message.get("result"), dict):
                        raise ValueError(f"MCP {method} failed; inspect the client log privately")
                    return message["result"]
                if "method" in message and "id" in message:
                    self._send(
                        {
                            "jsonrpc": "2.0",
                            "id": message["id"],
                            "error": {"code": -32601, "message": "Unsupported request"},
                        }
                    )
            if not self._selector.select(max(0, deadline - time.monotonic())):
                break
            chunk = os.read(self._process.stdout.fileno(), 65536)
            if not chunk:
                raise ValueError("MCP server exited before responding")
            self._pending += chunk
            if len(self._pending) > 4 * 1024 * 1024:
                raise ValueError("MCP response exceeded the verification limit")
        raise ValueError(f"MCP {method} timed out")

    def tools(self) -> list[str]:
        """Require advertised tools, including all pagination pages."""
        names: list[str] = []
        parameters: dict[str, str] = {}
        cursors: set[str] = set()
        for _page in range(100):
            result = self.request("tools/list", parameters)
            tools = result.get("tools")
            if not isinstance(tools, list) or any(
                not isinstance(t, dict) or not isinstance(t.get("name"), str) for t in tools
            ):
                raise ValueError("MCP tool discovery returned an invalid response")
            names.extend(tool["name"] for tool in tools)
            cursor = result.get("nextCursor")
            if not cursor:
                if not names:
                    raise ValueError("MCP server advertised no tools")
                return names
            if not isinstance(cursor, str) or cursor in cursors:
                raise ValueError("MCP tool discovery returned an invalid cursor")
            cursors.add(cursor)
            parameters = {"cursor": cursor}
        raise ValueError("MCP tool discovery exceeded the page limit")

    def check_access(self, check: dict, available_tools: list[str]) -> None:
        """Run the declared read-only authentication check without disclosing its result."""
        tool = check["tool"]
        if tool not in available_tools:
            raise ValueError("MCP authentication check requires a tool the server did not advertise")
        result = self.request("tools/call", {"name": tool, "arguments": check["arguments"]})
        if result.get("isError"):
            raise ValueError("MCP authentication or service access check failed")
        content = result.get("content")
        if not isinstance(content, list) or any(not isinstance(item, dict) for item in content):
            raise ValueError("MCP authentication check returned an invalid result")
        texts = [item.get("text") for item in content if item.get("type") == "text"]
        if any(not isinstance(text, str) for text in texts):
            raise ValueError("MCP authentication check returned invalid text content")
        text = "\n".join(texts)
        if check["expect_text"] and check["expect_text"] not in text:
            raise ValueError("MCP authentication check did not return the required service response")
