"""Reuse native AI account sessions and connect interactive login to the user's terminal."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from ansible_collections.neilime.workstation_setup.plugins.module_utils.desktop_session import (
    DesktopSession,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.github_auth import (
    GITHUB_CREDENTIAL_ENVIRONMENT,
)


# Authentication is one transaction with private provider-specific steps.
# pylint: disable-next=too-few-public-methods
class AiProviderAuthentication:
    """Check native client credentials without model requests or captured login output."""

    # Keep the module's user, client and GitHub identity inputs explicit.
    # pylint: disable-next=too-many-arguments
    def __init__(self, home: Path, provider: str, executable: str, *, host: str = "", account: str = "") -> None:
        self.home, self.provider, self.executable = home, provider, executable
        self.host, self.account = host, account
        self.environment = dict(os.environ)
        for name in list(self.environment):
            if name in {
                "OPENAI_API_KEY",
                "CODEX_API_KEY",
                "CODEX_ACCESS_TOKEN",
                "COPILOT_GITHUB_TOKEN",
                *GITHUB_CREDENTIAL_ENVIRONMENT,
            } or name.startswith("COPILOT_PROVIDER_"):
                self.environment.pop(name)
        self.environment.update(
            HOME=str(home),
            XDG_CONFIG_HOME=str(home / ".config"),
            XDG_DATA_HOME=str(home / ".local/share"),
            CODEX_HOME=str(home / ".codex"),
            COPILOT_HOME=str(home / ".copilot"),
            GH_CONFIG_DIR=str(home / ".config/gh"),
            PATH="/usr/local/bin:/usr/bin:/bin",
            XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}",
            DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{os.getuid()}/bus",
        )

    def _run(self, arguments: list[str], data: bytes | None = None) -> subprocess.CompletedProcess:
        # Native credentials must be checked without inherited automation tokens.
        # pylint: disable-next=unknown-option-value
        # pylint: disable-next=ansible-bad-function
        return subprocess.run(
            [self.executable, *arguments],
            input=data,
            env=self.environment,
            cwd=self.home,
            capture_output=True,
            check=False,
            timeout=45,
        )

    def _codex_status(self) -> bool:
        result = self._run(["login", "status"])
        status = (result.stdout + result.stderr).lower()
        if result.returncode == 0:
            if b"logged in using chatgpt" in status:
                return True
            raise ValueError("Codex requires ChatGPT sign-in; run codex login as the managed user and rerun setup")
        if result.returncode == 1 and b"not logged in" in status:
            return False
        raise ValueError("Cannot check Codex login; run codex login status privately and repair its configuration")

    def _copilot_status(self) -> bool:
        # Use the SDK's read-only JSON-RPC request; no chat session or tool execution is created.
        request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "auth.getStatus", "params": {}}).encode()
        result = self._run(
            ["--headless", "--stdio", "--no-auto-update", "--log-level", "error"],
            f"Content-Length: {len(request)}\r\n\r\n".encode() + request,
        )
        if result.returncode or len(result.stdout) > 1024 * 1024:
            raise ValueError("Cannot check Copilot login; check connectivity and run copilot login privately")
        status = self._copilot_response(result.stdout)
        if not status["isAuthenticated"]:
            return False
        host = status.get("host", "")
        try:
            actual_host = urlsplit(host if "://" in host else f"https://{host}").hostname
        except ValueError:
            raise ValueError("Copilot returned an invalid authentication status") from None
        if status.get("login") != self.account or actual_host != self.host:
            raise ValueError("Copilot must use the configured GitHub account and host; run copilot login to select it")
        return True

    @staticmethod
    def _copilot_response(remaining: bytes) -> dict:
        """Read the SDK status response without exposing invalid private payloads."""
        try:
            while remaining:
                header, body = remaining.split(b"\r\n\r\n", 1)
                if not header.startswith(b"Content-Length: "):
                    break
                length = int(header.removeprefix(b"Content-Length: "))
                if length < 1 or length > len(body):
                    break
                response = json.loads(body[:length])
                remaining = body[length:]
                if response.get("id") != 1:
                    continue
                status = response["result"]
                if not isinstance(status.get("isAuthenticated"), bool):
                    break
                if any(key in status and not isinstance(status[key], str) for key in ("login", "host")):
                    break
                return status
        except KeyError, TypeError, AttributeError, ValueError:
            pass
        raise ValueError("Copilot returned an invalid authentication status")

    def _status(self) -> bool:
        return self._codex_status() if self.provider == "codex" else self._copilot_status()

    def _login(self, terminal: str) -> None:
        if not terminal:
            raise ValueError(
                f"{self.provider} login is required; run {self.provider} login as the managed user, "
                "then rerun setup, or run setup from an interactive desktop terminal"
            )
        arguments = [self.executable, "login"]
        if self.provider == "copilot":
            arguments += ["--host", f"https://{self.host}"]
        result = DesktopSession.run_in_terminal(
            arguments, terminal=terminal, home=self.home, environment=self.environment
        )
        if result.returncode:
            raise ValueError(f"{self.provider} sign-in did not complete; run {self.provider} login and rerun setup")

    def ensure(self, *, terminal: str = "", check_mode: bool = False) -> dict:
        """Reuse stored login or perform native sign-in; previews launch no clients."""
        if check_mode:
            return {"changed": False, "authenticated": False, "deferred": True}
        if self._status():
            return {"changed": False, "authenticated": True, "deferred": False}
        self._login(terminal)
        if not self._status():
            raise ValueError(f"{self.provider} login is still missing after sign-in; rerun its login command privately")
        return {"changed": True, "authenticated": True, "deferred": False}
