"""Establish a persistent GitHub login without mistaking environment tokens for one."""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any


# Authentication is a single transaction; its steps are deliberately private.
# pylint: disable=too-few-public-methods
class GitHubAuthentication:
    """Keep authentication in the managed user's OS credential store."""

    def __init__(self, home: Path, host: str, account: str) -> None:
        if not account.strip():
            raise ValueError("A GitHub account is required for persistent authentication")
        account = account.strip()
        self.home, self.host, self.account = home, host, account
        self.environment = dict(os.environ)
        for name in (
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "GH_ENTERPRISE_TOKEN",
            "GITHUB_ENTERPRISE_TOKEN",
            "WORKSTATION_MANAGER_GITHUB_TOKEN",
            "GH_DEBUG",
        ):
            self.environment.pop(name, None)
        self.environment.update(
            HOME=str(home),
            XDG_CONFIG_HOME=str(home / ".config"),
            XDG_DATA_HOME=str(home / ".local/share"),
            GH_CONFIG_DIR=str(home / ".config/gh"),
            GH_PROMPT_DISABLED="1",
            GIT_TERMINAL_PROMPT="0",
            PATH="/usr/local/bin:/usr/bin:/bin",
            XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}",
            DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{os.getuid()}/bus",
        )

    def _run(
        self, command: list[str], *, data: str | None = None, environment: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        # run_command merges inherited tokens; this call requires a fully sanitized environment.
        # The Ansible-specific checker is absent from standalone Pylint.
        # pylint: disable-next=unknown-option-value
        # pylint: disable-next=ansible-bad-function
        return subprocess.run(
            command,
            input=data,
            env=environment or self.environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=45,
        )

    def _status(self) -> dict[str, Any]:
        result = self._run(["/usr/bin/gh", "auth", "status", "--hostname", self.host, "--active", "--json", "hosts"])
        if result.returncode and not result.stdout.strip():
            if "not logged" in result.stderr.lower():
                return {}
            raise ValueError("Cannot check GitHub authentication; check connectivity and run gh auth status privately")
        try:
            entries = json.loads(result.stdout)["hosts"].get(self.host, [])
            active: dict[str, Any] = next((entry for entry in entries if entry.get("active")), {})
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise ValueError("GitHub CLI returned an invalid authentication status") from error
        if active.get("state") == "timeout":
            raise ValueError("GitHub authentication timed out; restore network access before retrying")
        return active

    def _check_credential_store(self) -> None:
        """Verify secret-service writes before gh could fall back to a plaintext token file."""
        identifier = uuid.uuid4().hex
        attributes = ["application", "workstation-manager-probe", "id", identifier]
        written = False
        try:
            stored = self._run(
                ["secret-tool", "store", "--label=Workstation credential-store check", *attributes], data=identifier
            )
            written = stored.returncode == 0
            read = self._run(["secret-tool", "lookup", *attributes])
            if stored.returncode or read.returncode or read.stdout.strip() != identifier:
                raise ValueError(
                    "Unlock the GNOME credential store in the managed user's desktop session and rerun setup"
                )
        finally:
            cleared = self._run(["secret-tool", "clear", *attributes])
            if written and cleared.returncode:
                raise ValueError("Cannot clear the credential-store test entry; unlock the desktop keyring and retry")

    def _login(self, token: str, terminal: str) -> None:
        if not token and not terminal:
            raise ValueError("Persistent GitHub login is missing or expired; run setup from an unlocked GNOME terminal")
        self._check_credential_store()
        command = ["/usr/bin/gh", "auth", "login", "--hostname", self.host, "--git-protocol", "https"]
        if token:
            result = self._run([*command, "--with-token"], data=token)
        else:
            environment = {key: value for key, value in self.environment.items() if key != "GH_PROMPT_DISABLED"}
            with open(terminal, "r+", encoding="utf-8") as tty:
                if not tty.isatty():
                    raise ValueError("GitHub login requires the managed user's terminal")
                # Browser/device login needs the real terminal, never Ansible-captured output.
                # pylint: disable-next=unknown-option-value
                # pylint: disable-next=ansible-bad-function
                result = subprocess.run(
                    [*command, "--web"],
                    stdin=tty,
                    stdout=tty,
                    stderr=tty,
                    env=environment,
                    text=True,
                    check=False,
                    timeout=300,
                )
        if result.returncode:
            raise ValueError("GitHub login failed; verify account access with gh auth status, then rerun setup")

    def _git_helper_ready(self) -> bool:
        result = self._run(["git", "config", "--global", "--get-all", f"credential.https://{self.host}.helper"])
        if result.returncode not in (0, 1):
            raise ValueError("Cannot inspect the managed user's Git credential configuration")
        helpers = result.stdout.strip().splitlines()
        return bool(helpers) and helpers[-1].replace("! ", "!") in (
            "!/usr/bin/gh auth git-credential",
            "!gh auth git-credential",
        )

    def _ensure_git_helper(self, check_mode: bool) -> bool:
        if self._git_helper_ready():
            return False
        if not check_mode:
            # Dynamic settings share restored signing configuration, not the Chezmoi-owned file.
            config_path = self.home / ".config/git/config"
            config_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            configured = self._run(
                ["/usr/bin/gh", "auth", "setup-git", "--hostname", self.host],
                environment={**self.environment, "GIT_CONFIG_GLOBAL": str(config_path)},
            )
            if configured.returncode or not self._git_helper_ready():
                raise ValueError("GitHub login works but Git credential integration could not be configured")
        return True

    def ensure(self, *, token: str = "", terminal: str = "", check_mode: bool = False) -> dict[str, Any]:
        """Verify the account, keyring storage, and Git credential integration."""
        status = self._status()
        authenticated = status.get("state") == "success"
        secure = authenticated and status.get("tokenSource") == "keyring"
        if authenticated and status.get("login") != self.account:
            raise ValueError(
                f"Select the configured GitHub account with gh auth switch --hostname {self.host} --user {self.account}"
            )
        changed = not secure
        if not secure and not check_mode:
            if authenticated and not token:
                existing = self._run(["/usr/bin/gh", "auth", "token", "--hostname", self.host])
                if existing.returncode:
                    raise ValueError("Cannot migrate the existing GitHub credential into the OS credential store")
                token = existing.stdout.strip()
            self._login(token, terminal)
            status = self._status()
            if status.get("state") != "success" or status.get("tokenSource") != "keyring":
                raise ValueError(
                    "GitHub login is not verified in the OS credential store; repair the keyring and rerun setup"
                )
            if status.get("login") != self.account:
                raise ValueError(
                    "GitHub authenticated a different account; select the configured account and rerun setup"
                )
        if status.get("state") == "success":
            changed = self._ensure_git_helper(check_mode) or changed
        return {
            "changed": changed,
            "authenticated": status.get("state") == "success" and status.get("tokenSource") == "keyring",
            "account": status.get("login", ""),
        }
