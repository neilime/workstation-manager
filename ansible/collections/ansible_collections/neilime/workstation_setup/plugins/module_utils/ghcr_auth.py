"""Authenticate Docker to GHCR while keeping credentials in Secret Service."""

from __future__ import annotations

import copy
import hmac
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from ansible_collections.neilime.workstation_setup.plugins.module_utils.github_auth import (
    GitHubAuthentication,
)


# Authentication is a transaction; only ensure is part of the module's interface.
# pylint: disable=too-few-public-methods
class GhcrAuthentication:
    """Verify registry access before changing the user's Docker configuration."""

    def __init__(self, home: Path, account: str) -> None:
        self.account = account
        self.path = home / ".docker/config.json"
        self.github = GitHubAuthentication(home, "github.com", account)
        self.environment = {
            key: value for key, value in self.github.environment.items() if not key.startswith("DOCKER_")
        }

    def _run(self, command: list[str], data: str) -> subprocess.CompletedProcess[str]:
        # A replacement environment prevents Docker auth/config overrides from redirecting credentials.
        # pylint: disable-next=unknown-option-value
        # pylint: disable-next=ansible-bad-function
        return subprocess.run(
            command, input=data, env=self.environment, text=True, capture_output=True, check=False, timeout=60
        )

    @staticmethod
    def _unique_properties(pairs: list[tuple]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Docker configuration contains duplicate JSON properties")
            result[key] = value
        return result

    def _read_config(self) -> dict:
        if any(part.is_symlink() for part in (self.path, *self.path.parents)):
            raise ValueError("Docker configuration must use a private regular file without symlinked parents")
        if not self.path.exists():
            return {}
        if not self.path.is_file():
            raise ValueError("Docker configuration must be a regular file")
        try:
            config = json.loads(self.path.read_text(), object_pairs_hook=self._unique_properties)
        except (json.JSONDecodeError, UnicodeError) as error:
            raise ValueError("Docker config.json is malformed; repair it before running setup") from error
        if not isinstance(config, dict):
            raise ValueError("Docker config.json must contain a JSON object")
        for name, value_type in (("auths", dict), ("credHelpers", str)):
            entries = config.get(name, {})
            if not isinstance(entries, dict) or any(not isinstance(value, value_type) for value in entries.values()):
                raise ValueError(f"Docker config.json has an invalid {name} mapping")
        return config

    @staticmethod
    def _configured(config: dict) -> dict:
        updated = copy.deepcopy(config)
        updated.setdefault("credHelpers", {})["ghcr.io"] = "secretservice"
        # Docker accepts registry URL keys as well as hostnames in its auth map.
        for registry in list(updated.get("auths", {})):
            try:
                hostname = urlsplit(registry if "://" in registry else "//" + registry).hostname
            except ValueError as error:
                raise ValueError("Docker config.json has an invalid registry address") from error
            if hostname == "ghcr.io":
                del updated["auths"][registry]
        return updated

    def _stored_credentials(self) -> dict:
        result = self._run(["/usr/local/bin/docker-credential-secretservice", "get"], "ghcr.io\n")
        if result.returncode:
            if "credentials not found in native keychain" in result.stdout + result.stderr:
                return {}
            raise ValueError("Cannot read Docker's GHCR credential; unlock the desktop keyring and retry")
        try:
            credential = json.loads(result.stdout)
            if not isinstance(credential, dict) or any(
                not isinstance(credential.get(key), str) for key in ("Username", "Secret")
            ):
                raise ValueError("Invalid credential")
        except ValueError as error:
            raise ValueError("Docker's credential helper returned an invalid response") from error
        return credential

    def _matches(self, credential: dict, token: str) -> bool:
        return credential.get("Username") == self.account and hmac.compare_digest(
            credential.get("Secret", "").encode(), token.encode()
        )

    @staticmethod
    def _write_config(path: Path, config: dict) -> None:
        """Publish privately without exposing partially written configuration."""
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        original = path.stat() if path.exists() else None
        descriptor, temporary = tempfile.mkstemp(prefix=".workstation-docker-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(config, stream, indent=2)
                stream.write("\n")
                if original:
                    os.fchown(stream.fileno(), original.st_uid, original.st_gid)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def _login(self, token: str) -> None:
        # The temporary config contains only the helper selection, never the token.
        # Failed login must leave the original config and inline credentials recoverable.
        with tempfile.TemporaryDirectory(prefix="workstation-ghcr-") as temporary:
            self._write_config(Path(temporary) / "config.json", {"credHelpers": {"ghcr.io": "secretservice"}})
            result = self._run(
                [
                    "/usr/bin/docker",
                    "--config",
                    temporary,
                    "login",
                    "ghcr.io",
                    "--username",
                    self.account,
                    "--password-stdin",
                ],
                token,
            )
        if result.returncode:
            raise ValueError(
                "Docker login to ghcr.io failed; check connectivity, package permissions, organization SSO, "
                "and the unlocked desktop keyring, then rerun setup"
            )
        if not self._matches(self._stored_credentials(), token):
            raise ValueError("Docker login did not save the configured GHCR account in Secret Service")

    def ensure(self, *, terminal: str = "", check_mode: bool = False) -> dict:
        """Check account, package scope and registry login without publishing an image."""
        original = self._read_config()
        configured = self._configured(original)
        config_changed = (
            configured != original or not self.path.exists() or stat.S_IMODE(self.path.stat().st_mode) != 0o600
        )
        github = self.github.ensure(terminal=terminal, check_mode=check_mode, scopes=("write:packages",))
        if not github["authenticated"]:
            return {"changed": True, "authenticated": False, "account": self.account}
        token = self.github.read_token()
        matches = self._matches(self._stored_credentials(), token)
        changed = config_changed or github["changed"] or not matches
        if not check_mode:
            self._login(token)
            if config_changed:
                self._write_config(self.path, configured)
        return {"changed": changed, "authenticated": not check_mode, "account": self.account}
