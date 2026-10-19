"""Validate a reviewed GNOME Shell extension archive before installation."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath


# pylint: disable=too-few-public-methods
class GnomeExtensionArchive:
    """Verify artifact identity, supported Shell versions, and extraction safety."""

    @staticmethod
    def validate(
        path: str,
        checksum: str,
        version: str,
        shell_version: str,
        identity: tuple[str, str],
    ) -> dict[str, object]:
        """Return metadata only for the exact pinned, compatible archive.

        ``identity`` is the ``(uuid, label)`` pair for the managed extension.
        """
        uuid, label = identity
        source = Path(path)
        if hashlib.sha256(source.read_bytes()).hexdigest() != checksum:
            raise ValueError(f"{label} archive checksum does not match the configured pin")
        with zipfile.ZipFile(source) as archive:
            for entry in archive.infolist():
                name = PurePosixPath(entry.filename)
                mode = entry.external_attr >> 16
                if name.is_absolute() or ".." in name.parts or "\\" in entry.filename or stat.S_ISLNK(mode):
                    raise ValueError(f"{label} archive contains an unsafe path or link")
            metadata = json.loads(archive.read("metadata.json"))
        if not isinstance(metadata, dict) or metadata.get("uuid") != uuid:
            raise ValueError(f"{label} archive has an unexpected identity")
        if str(metadata.get("version")) != version:
            raise ValueError(f"{label} archive version does not match the configured pin")
        match = re.fullmatch(r"GNOME Shell ([0-9]+)(?:\.[0-9A-Za-z.-]+)?\s*", shell_version)
        if not match or match[1] not in metadata.get("shell-version", []):
            raise ValueError(f"{label} does not support this GNOME Shell; configure a compatible reviewed archive")
        return metadata
