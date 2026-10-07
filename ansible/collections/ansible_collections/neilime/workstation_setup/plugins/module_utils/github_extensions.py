"""Install reviewed GitHub extension revisions without gh's latest-version upgrade path."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable


# Keep pin reconciliation and its state internal to one public operation.
# pylint: disable=too-few-public-methods
class GitHubExtensions:
    """Track managed pins while verifying the actual installed revision on every run."""

    def __init__(self, home: Path, record: Path, run: Callable) -> None:
        self.home, self.record, self.run = home, record, run

    def _command(self, arguments: list[str]) -> str:
        status, stdout, _stderr = self.run(arguments)
        if status:
            raise ValueError("GitHub extension operation failed; check repository access and rerun setup")
        return stdout

    def _installed(self) -> dict[str, str]:
        entries = {}
        for line in self._command(["gh", "extension", "list"]).splitlines():
            fields = line.split()
            if len(fields) >= 4 and fields[0] == "gh":
                entries[fields[2]] = fields[3]
        return entries

    def _revision(self, repository: str, revision: str, installed: dict[str, str]) -> str:
        if repository not in installed:
            return ""
        if re.fullmatch(r"[0-9a-f]{40}", revision):
            path = self.home / ".local/share/gh/extensions" / repository.split("/")[1]
            return self._command(["git", "-C", str(path), "rev-parse", "HEAD"]).strip()
        return installed[repository]

    def ensure(self, extensions: dict[str, str], *, check_mode: bool = False) -> bool:
        """Replace only selected extension code, preserving locally modified script checkouts."""
        if not extensions:
            return False
        pins = json.loads(self.record.read_text(encoding="utf-8")) if self.record.exists() else {}
        if not isinstance(pins, dict):
            raise ValueError("Invalid managed GitHub extension revision record")
        installed = self._installed()
        changed = False
        for repository, revision in extensions.items():
            if (
                not isinstance(repository, str)
                or not isinstance(revision, str)
                or re.fullmatch(r"[\w.-]+/gh-[\w.-]+", repository) is None
                or re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+|[0-9a-f]{40}", revision) is None
            ):
                raise ValueError("GitHub extensions require a repository and an exact release tag or commit")
            name = repository.split("/")[1]
            if any(other != repository and other.split("/")[-1] == name for other in installed):
                raise ValueError(f"An extension from another repository already owns {name}; reconcile it before setup")
            if pins.get(repository) == revision and self._revision(repository, revision, installed) == revision:
                continue
            path = self.home / ".local/share/gh/extensions" / name
            if (path / ".git").exists() and self._command(["git", "-C", str(path), "status", "--porcelain"]):
                raise ValueError(f"Preserve local changes in {path} before updating the selected extension")
            changed = True
            if check_mode:
                continue
            if repository in installed:
                self._command(["gh", "extension", "remove", name])
            self._command(["gh", "extension", "install", repository, "--pin", revision])
            installed = self._installed()
            if self._revision(repository, revision, installed) != revision:
                raise ValueError(f"GitHub extension {repository} did not install the configured revision")
            pins[repository] = revision
        if changed and not check_mode:
            self.record.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            self.record.write_text(json.dumps(pins) + "\n", encoding="utf-8")
            self.record.chmod(0o600)
        return changed
