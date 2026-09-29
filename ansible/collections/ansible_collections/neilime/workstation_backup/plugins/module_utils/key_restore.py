"""Restore one explicitly approved vault key without changing unrelated keys."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path

from ansible_collections.neilime.workstation_backup.plugins.module_utils.key_sync import (
    normalize_ownertrust,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.bitwarden_gpg_keys import (
    BitwardenGpgKeyRestorePlanner,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.bitwarden_ssh_keys import (
    BitwardenSshKeyRestorePlanner,
)


def _directory(path: Path) -> None:
    if not path.is_absolute() or path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValueError("Key directories must be absolute directories, not symbolic links")


def _write_key(path: Path, content: bytes, mode: int) -> None:
    with tempfile.NamedTemporaryFile(prefix=".workstation-key-", dir=path.parent, delete=False) as handle:
        try:
            os.fchmod(handle.fileno(), mode)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            os.replace(handle.name, path)
        finally:
            Path(handle.name).unlink(missing_ok=True)


def _restore_ssh(home: Path, item: dict, identity: str, check: bool) -> bool:
    plan = BitwardenSshKeyRestorePlanner().build_plan(item, str(home))
    if plan["name"] != identity:
        raise ValueError("The remote SSH key identity changed; inspect the collection and retry")
    directory = home / ".ssh"
    _directory(directory)
    pending = []
    for entry in (plan["private"], plan["public"]):
        path = Path(entry["dest"])
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("Refusing a linked or non-regular SSH key destination")
        content, mode = entry["content"].encode(), int(entry["mode"], 8)
        if not path.exists() or path.read_bytes() != content or path.stat().st_mode & 0o777 != mode:
            pending.append((path, content, mode))
    if pending and not check:
        directory.mkdir(mode=0o700, exist_ok=True)
        for path, content, mode in pending:
            _write_key(path, content, mode)
        for entry in (plan["private"], plan["public"]):
            path = Path(entry["dest"])
            if path.read_bytes() != entry["content"].encode() or path.stat().st_mode & 0o777 != int(entry["mode"], 8):
                raise ValueError("Restored SSH key verification failed; backup stopped")
    return bool(pending)


class _GpgKeyring:
    """Use Ansible's command runner for binary key material and private diagnostics."""

    def __init__(self, home: Path, run_command: Callable[..., tuple[int, bytes, bytes]]) -> None:
        self.home = home
        self.run_command = run_command

    def run(self, *arguments: str, data: bytes | None = None) -> bytes:
        """Keep raw exports in memory without rendering command errors."""

        return_code, stdout, _stderr = self.run_command(
            ["gpg", "--homedir", str(self.home), "--batch", "--pinentry-mode", "error", *arguments],
            data=data,
            binary_data=True,
            encoding=None,
        )
        if return_code:
            raise ValueError("GPG restore or verification failed; unlock protected keys and retry")
        return stdout

    def material(self, fingerprint: str) -> tuple[bytes, bytes, bytes]:
        """Compare canonical exports and the selected key's normalized trust."""

        trust = next(
            (
                line.decode()
                for line in self.run("--export-ownertrust").splitlines()
                if line.startswith(fingerprint.encode() + b":")
            ),
            None,
        )
        return (
            self.run("--export-secret-keys", fingerprint),
            self.run("--export", fingerprint),
            (normalize_ownertrust(trust) or "").encode(),
        )


def _primary_fingerprints(listing: bytes) -> list[str]:
    fingerprints = []
    primary = False
    for line in listing.decode().splitlines():
        fields = line.split(":")
        if fields[0] in {"sec", "pub"}:
            primary = True
        elif fields[0] in {"ssb", "sub"}:
            primary = False
        elif fields[0] == "fpr" and primary:  # codespell:ignore fpr
            fingerprints.append(fields[9])
            primary = False
    return fingerprints


def _restore_gpg(
    home: Path, item: dict, identity: str, check: bool, run_command: Callable[..., tuple[int, bytes, bytes]]
) -> bool:
    plan = BitwardenGpgKeyRestorePlanner().build_plan(item)
    fingerprint = plan["fingerprint"]
    if fingerprint != identity:
        raise ValueError("The remote GPG key fingerprint changed; inspect the collection and retry")
    trust = plan["ownertrust"]
    if trust is not None and re.fullmatch(re.escape(fingerprint) + r":[2-6]:\s*", trust) is None:
        raise ValueError("GPG ownertrust must contain only the selected key's trust entry")
    local = _GpgKeyring(home / ".gnupg", run_command)
    _directory(local.home)
    with tempfile.TemporaryDirectory(prefix="workstation-gpg-") as temporary:
        staged = _GpgKeyring(Path(temporary), run_command)
        try:
            for material in (plan["private_key"].encode(), plan["public_key"].encode()):
                listing = staged.run("--with-colons", "--import-options", "show-only", "--import", data=material)
                if set(_primary_fingerprints(listing)) != {fingerprint}:
                    raise ValueError("GPG key material does not match the selected fingerprint")
                staged.run("--import", data=material)
            staged.run("--import-ownertrust", data=(trust or f"{fingerprint}:2:\n").encode())
            expected = staged.material(fingerprint)
            if not expected[0] or not expected[1]:
                raise ValueError("The remote GPG key must include matching private and public material")
            # Missing keyrings are never created by a preview.
            changed = (local.material(fingerprint) if local.home.exists() else (b"", b"", b"")) != expected
            if changed and not check:
                local.home.mkdir(mode=0o700, exist_ok=True)
                local.run("--import", data=plan["private_key"].encode())
                local.run("--import", data=plan["public_key"].encode())
                local.run("--import-ownertrust", data=(trust or f"{fingerprint}:2:\n").encode())
                if local.material(fingerprint) != expected:
                    raise ValueError(
                        "GPG still differs after import. Local-only key packets were preserved; "
                        "reconcile manually or choose save. Backup stopped."
                    )
            return changed
        finally:
            run_command(["gpgconf", "--homedir", temporary, "--kill", "all"], encoding=None)


# Keep the validated module inputs explicit alongside its command runner and check mode.
# pylint: disable-next=too-many-arguments
def restore_key(
    kind: str,
    user_home: str,
    key_item: dict,
    identity: str,
    *,
    run_command: Callable[..., tuple[int, bytes, bytes]],
    check_mode: bool = False,
) -> bool:
    """Restore selected values, preserve unrelated keys, and verify before returning."""

    home = Path(user_home)
    _directory(home)
    if kind == "ssh":
        return _restore_ssh(home, key_item, identity, check_mode)
    if kind == "gpg":
        return _restore_gpg(home, key_item, identity, check_mode, run_command)
    raise ValueError("Unsupported key kind")
