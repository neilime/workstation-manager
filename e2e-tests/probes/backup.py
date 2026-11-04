#!/usr/bin/env python3
"""Verify relationships between backup recovery artifacts without extracting them."""

from __future__ import annotations

import json
import os
import stat
import tarfile
from pathlib import Path


# A probe exposes one cohesive operation, rather than a general testing API.
# pylint: disable=too-few-public-methods
class BackupProbe:
    """Check the synthetic recovery fixture's manifest, inventory and archive."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def verify(self) -> None:
        """Reject incomplete recovery, exposed artifacts and missing local work."""
        archives = list(self.root.glob("workstation-manager-backup-*.tar.gz"))
        assert len(archives) == 1, "Expected one completed backup archive"
        archive = archives[0]
        base = str(archive).removesuffix(".tar.gz")
        manifest = Path(base + ".manifest.txt")
        inventory = Path(base + ".git-repositories.json")
        restore = Path(base + ".restore-command.txt")
        browser = Path(base + ".browser-profiles.json")
        assert self.root.stat().st_uid == os.getuid(), "Backup directory owner differs"
        for artifact in (archive, manifest, inventory, restore):
            assert artifact.is_file(), "Missing recovery artifact"
            assert artifact.stat().st_uid == os.getuid(), "Recovery artifact owner differs"
        records = manifest.read_text(encoding="utf-8").splitlines()
        for record in (
            f"archive\t{archive}",
            "dry_run\t0",
            f"export\tgit-repositories\t{inventory}",
            f"export\trestore-command\t{restore}",
        ):
            assert record in records, "Manifest and recovery artifacts disagree"
        assert not any("recovery_skipped\t" in record or "recovery_status\tincomplete" in record for record in records)
        command = restore.read_text(encoding="utf-8")
        assert command.startswith("wget -qO- https://raw.githubusercontent.com/")
        assert command.endswith(f"WORKSTATION_MANAGER_RESTORE_ARCHIVE={archive} sh -s -- setup\n")
        for artifact in (archive, restore):
            assert stat.S_IMODE(artifact.stat().st_mode) == 0o600, "Recovery artifact permissions differ"
        assert [line for line in records if line.startswith("export\tbrowser-profiles\t")] == (
            [f"export\tbrowser-profiles\t{browser}"] if browser.exists() else []
        )
        if browser.exists():
            assert browser.is_file()
            assert stat.S_IMODE(browser.stat().st_mode) == 0o600
            assert browser.stat().st_uid == os.getuid()
        self._verify_inventory(inventory)
        self._verify_archive(archive)

    @staticmethod
    def _verify_inventory(inventory: Path) -> None:
        """The fixture must recover its project while excluding ignored dependencies."""
        repositories = json.loads(inventory.read_text(encoding="utf-8"))
        fields = ("relative_path", "primary_remote_name", "primary_remote_url", "branch")
        assert {
            "relative_path": "client-restore",
            "primary_remote_name": "origin",
            "primary_remote_url": "/tmp/workstation-manager-e2e-origin-client-restore.git",
            "branch": "main",
        } in [{key: repository[key] for key in fields} for repository in repositories]
        assert not any(
            repository["relative_path"].startswith("client-restore/tools/vendor/") for repository in repositories
        )

    @staticmethod
    def _verify_archive(archive: Path) -> None:
        """Inspect recovery content without extracting it into the filesystem."""
        with tarfile.open(archive) as content:
            members = content.getnames()
            assert not any("/.git/" in name or name.endswith("/.git") for name in members)
            assert not any("/tools/vendor/" in name or name.endswith(".private") for name in members)
            prefix = "Documents/dev-projects/client-restore/"
            assert prefix + "local-note.txt" in members
            tracked = content.extractfile(prefix + "tracked.txt")
            assert tracked is not None
            assert tracked.read().decode().rstrip("\n") == "remote-base\nlocal-change"


if __name__ == "__main__":
    BackupProbe(Path("/tmp/workstation-manager-e2e-backup")).verify()
