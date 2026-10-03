"""Resolve the extraction directory for home-relative and single-source backups."""

from __future__ import annotations

import posixpath
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

from ansible_collections.neilime.workstation_restore.plugins.module_utils.archive_safety import (
    validate_archive,
)


# The planner exposes one operation to its Ansible adapter.
# pylint: disable-next=too-few-public-methods
class ArchiveRestorePlanner:
    """Recover the archive root without using the source computer's absolute home."""

    def build(self, archive_path: str, target_home: str, manifest_path: str | None = None) -> dict[str, Any]:
        """Choose a destination and validate every write against the managed home."""

        with tarfile.open(archive_path, "r:*") as archive:
            names = {PurePosixPath(member.name) for member in archive.getmembers() if PurePosixPath(member.name).parts}
        prefix = PurePosixPath(".")
        if manifest_path is not None:
            prefix = self._manifest_prefix(names, Path(manifest_path).read_text(encoding="utf-8"))
        else:
            # Without a sidecar, only the two default single-source
            # layouts are recognized; general archives stay relative to home.
            for source, parent in (("dev-projects", "Documents"), ("workstation-manager", ".config")):
                if names and all(name.is_relative_to(source) for name in names):
                    prefix = PurePosixPath(parent)
                    break
        destination = str(Path(target_home).joinpath(*prefix.parts))
        return {
            "members": validate_archive(archive_path, target_home, extraction_directory=destination),
            "destination": destination,
            "destination_exists": Path(destination).is_dir(),
        }

    @staticmethod
    def _manifest_prefix(names: set[PurePosixPath], manifest: str) -> PurePosixPath:
        """Use recorded sources to recognize a shortened common-parent archive."""

        sources: list[PurePosixPath] = []
        homes: set[PurePosixPath] = set()
        defaults = {
            "dev-projects": ("Documents", "dev-projects"),
            "workstation-manager-user-config": (".config", "workstation-manager"),
        }
        for line in manifest.splitlines():
            fields = line.split("\t", 2)
            if len(fields) != 3 or fields[0] not in {"include", "missing"}:
                continue
            status, label, raw_path = fields
            path = PurePosixPath(posixpath.normpath(raw_path))
            if not path.is_absolute():
                raise ValueError("Backup manifest source paths must be absolute.")
            if label in defaults and path.parts[-2:] == defaults[label]:
                homes.add(path.parent.parent)
            if status == "include":
                sources.append(path)
        if len(homes) > 1:
            raise ValueError("Backup manifest records inconsistent source homes.")
        if not homes or not sources:
            return PurePosixPath(".")
        home = homes.pop()
        root = PurePosixPath(posixpath.commonpath([str(source.parent) for source in sources]))
        if not root.is_relative_to(home):
            return PurePosixPath(".")
        source_roots = {source.relative_to(root) for source in sources}
        if source_roots.issubset(names) and all(
            any(name.is_relative_to(source) for source in source_roots) for name in names
        ):
            return root.relative_to(home)
        return PurePosixPath(".")
