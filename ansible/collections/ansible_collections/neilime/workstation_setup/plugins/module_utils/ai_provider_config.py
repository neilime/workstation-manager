"""Reconcile owned MCP entries without replacing personal provider configuration."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import tomllib
from pathlib import Path

from ansible_collections.neilime.workstation_setup.plugins.module_utils.jsonc_document import (
    JsoncDocument,
)


class AiProviderConfiguration:
    """Merge JSONC server properties or an explicitly owned TOML section."""

    BEGIN = "# BEGIN workstation-manager MCP\n"
    END = "# END workstation-manager MCP\n"

    @staticmethod
    def digest(value: object) -> str:
        """Track ownership without storing a second copy of credentials."""
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def private_path(path: Path) -> None:
        """Refuse symlinks rather than writing credentials into a dotfile source."""
        if not path.is_absolute():
            raise ValueError("AI configuration paths must be absolute")
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError("AI configuration paths must not traverse symlinks; use a private regular file")
        if path.exists() and not path.is_file():
            raise ValueError("AI configuration requires a regular file")

    @staticmethod
    def write_private(path: Path, content: str) -> None:
        """Atomically replace a validated path using a private temporary file."""
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".workstation-ai-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                stream.write(content)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    # Paths and native format are explicit inputs at the adapter boundary.
    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    def reconcile(
        self, path: Path, state_path: Path, format_name: str, key: str, servers: dict, check: bool = False
    ) -> bool:
        """Validate the entire merge before privately and atomically writing either file."""
        self.private_path(path)
        self.private_path(state_path)
        if path == state_path or re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", key) is None:
            raise ValueError("AI configuration needs a distinct ownership file and a valid server-map key")
        with path.open(encoding="utf-8", newline="") if path.exists() else open(os.devnull, encoding="utf-8") as stream:
            original = stream.read()
        try:
            previous = json.loads(state_path.read_text()) if state_path.exists() else {}
            if not isinstance(previous, dict) or any(not isinstance(v, str) for v in previous.values()):
                raise ValueError("Invalid ownership state")
            if format_name == "toml":
                updated = self._toml(original, key, servers, previous)
            else:
                updated = self._json(original, key, servers, previous)
        except (json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
            raise ValueError("AI configuration or ownership state is malformed; repair it before setup") from error
        ownership = {name: self.digest(value) for name, value in servers.items()}
        changed = updated != original or previous != ownership
        changed = changed or any(p.exists() and stat.S_IMODE(p.stat().st_mode) != 0o600 for p in (path, state_path))
        if not path.exists() and servers:
            changed = True
        if changed and not check:
            self.write_private(path, updated)
            self.write_private(state_path, json.dumps(ownership, indent=2) + "\n")
        return changed

    def _check_ownership(self, current: dict, desired: dict, previous: dict) -> None:
        for name in previous.keys() | desired.keys():
            if name not in current:
                continue
            if name in previous and name in desired and current[name] == desired[name]:
                continue  # Recover updates interrupted between configuration and ownership writes.
            if self.digest(current[name]) != previous.get(name):
                raise ValueError(
                    f"MCP entry {name} conflicts with user configuration; preserve or rename it before setup"
                )

    def _json(self, content: str, key: str, servers: dict, previous: dict) -> str:
        document = JsoncDocument()
        current = document.loads(content).get(key, {})
        if not isinstance(current, dict):
            raise ValueError("The MCP server map must be an object")
        self._check_ownership(current, servers, previous)
        for name in previous.keys() - servers.keys():
            content = document.remove(content, (key, name))
        for name, server in servers.items():
            content = document.set(content, (key, name), server)
        return content

    def _toml(self, content: str, key: str, servers: dict, previous: dict) -> str:
        original = tomllib.loads(content)
        current = original.get(key, {})
        if not isinstance(current, dict):
            raise ValueError("The MCP server map must be a table")
        self._check_ownership(current, servers, previous)
        outside = self._outside_block(content)
        personal = tomllib.loads(outside)
        unmanaged = personal.get(key, {})
        if any(name in unmanaged for name in previous.keys() | servers.keys()):
            raise ValueError("MCP TOML entries outside the managed block must be renamed or moved before setup")
        # Reject user-added entries inside the block before replacing it.
        if current.keys() - unmanaged.keys() - previous.keys() - servers.keys() or {
            name: value for name, value in original.items() if name != key
        } != {name: value for name, value in personal.items() if name != key}:
            raise ValueError("The managed MCP block contains user entries; move them outside the block")
        if not servers:
            return outside
        updated = outside + ("" if not outside or outside.endswith("\n") else "\n")
        updated += self.BEGIN + self._toml_servers(key, servers) + self.END
        if tomllib.loads(updated).get(key) != {**unmanaged, **servers}:
            raise ValueError("The generated MCP TOML does not match the declaration")
        return updated

    def _outside_block(self, content: str) -> str:
        """Isolate the exact user-owned text around a single well-formed block."""
        if content.count(self.BEGIN) != content.count(self.END) or content.count(self.BEGIN) > 1:
            raise ValueError("The managed MCP TOML block is malformed")
        if self.BEGIN in content:
            start, end = content.index(self.BEGIN), content.index(self.END)
            if end < start:
                raise ValueError("The managed MCP TOML block is malformed")
            return content[:start] + content[end + len(self.END) :]
        return content

    @staticmethod
    def _toml_servers(key: str, servers: dict) -> str:
        """Render the small native launch schema using TOML-compatible JSON strings."""
        lines = []
        for name, server in servers.items():
            lines.append(f"[{key}.{json.dumps(name)}]")
            for field, value in server.items():
                if field != "env":
                    lines.append(f"{field} = {json.dumps(value, ensure_ascii=False)}")
            if server.get("env"):
                lines.append(f"[{key}.{json.dumps(name)}.env]")
                lines.extend(f"{json.dumps(k)} = {json.dumps(v, ensure_ascii=False)}" for k, v in server["env"].items())
            lines.append("")
        return "\n".join(lines)
