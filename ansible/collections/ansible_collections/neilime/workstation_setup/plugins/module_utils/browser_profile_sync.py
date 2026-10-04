"""Reconcile approved Brave metadata while preserving recovery words and browser data."""

from __future__ import annotations

import base64
import copy
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from ansible_collections.neilime.workstation_setup.plugins.module_utils.bitwarden_browser_profiles import (
    bitwarden_browser_profiles,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_avatar import (
    AVATAR_FILENAME,
    MAX_AVATAR_BYTES,
    decode_avatar_png,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_inspection import (
    _read_settings,
    inspect_browser_profiles,
    sync_everything_drift,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_seed import (
    _brave_running,
    _object,
    _write_file,
    seed_browser_profiles,
)

_REMOTE_KINDS = {"missing", "renamed", "theme_color", "avatar", "unregistered", "missing_preferences"}
_LOCAL_KINDS = {"renamed", "theme_color", "avatar"}


class BrowserSyncBlocked(ValueError):
    """Signal a closed-browser precondition before any local or vault mutation."""


def browser_sync_directions(inspection: dict) -> dict[str, str]:
    """Offer directions for repairable profile settings; the live adapter handles pairing."""

    kinds = {issue["kind"] for issue in inspection["drift"] if issue.get("id")}
    actions = {}
    if kinds & _LOCAL_KINDS:
        actions["save"] = (
            "Replace saved names, colors and logos with local values; Brave closes and reopens automatically. "
            "Absent or disabled customizations are removed from Bitwarden; recovery words stay unchanged."
        )
    repairs = []
    if kinds & _REMOTE_KINDS:
        repairs.append("restore saved profile names, colors and logos locally")
    if sync_everything_drift(inspection):
        repairs.append("enable Sync everything")
    if repairs:
        description = " and ".join(repairs)
        actions["restore"] = f"{description[0].upper()}{description[1:]}. Brave closes and reopens automatically."
        if kinds & {"missing", "missing_preferences"}:
            actions["restore"] += " Missing profiles are recreated; the next check can restore their Sync chains."
    return actions


class BrowserVault:
    """Run the authenticated CLI without leaking sensitive stdout or stderr on failures."""

    def __init__(self, session: str, collection_id: str, run_command: Callable[..., tuple[int, bytes, bytes]]) -> None:
        self.run_command = run_command
        self.collection_id = collection_id
        self.environment = {**os.environ, "BW_SESSION": session, "BW_NOINTERACTION": "true"}

    def run(self, *arguments: str, data: bytes | None = None) -> bytes:
        """Return raw CLI output only to the sensitive synchronization path."""

        return_code, stdout, _stderr = self.run_command(
            ["bw", *arguments],
            data=data,
            binary_data=True,
            encoding=None,
            environ_update=self.environment,
        )
        if return_code:
            operation = "read browser record" if arguments[:2] == ("get", "item") else "synchronize browser recovery"
            raise ValueError(
                f"Bitwarden browser operation {operation} failed (exit status {return_code}); "
                "rerun setup or backup to unlock the vault and check access to the configured collection"
            )
        return stdout

    def item(self, item_id: str) -> dict:
        """Read a selected record without rendering its note or attachments."""

        output = self.run("get", "item", item_id)
        if not output.strip():
            raise ValueError("Bitwarden returned an empty browser record; rerun setup or backup and check vault access")
        try:
            value = json.loads(output)
        except (ValueError, TypeError) as error:
            raise ValueError("Bitwarden returned malformed browser record JSON; check the Bitwarden CLI installation") from error
        if not isinstance(value, dict):
            raise ValueError("Bitwarden returned a browser record with an unexpected JSON type")
        return value

    def selected_item(self, declaration: dict) -> dict:
        """Revalidate the approved identity and collection before reading or writing secrets."""

        item = self.item(declaration["item_id"])
        metadata = bitwarden_browser_profiles([item])[0]
        if self.collection_id not in item.get("collectionIds", []):
            raise ValueError("The selected browser record left its recovery collection; retry backup")
        if any(metadata.get(key) != declaration[key] for key in ("id", "directory", "item_id")):
            raise ValueError("The remote profile identity changed; inspect the collection and retry")
        return item


def _local_avatar(root: Path, observed: dict) -> bytes | None:
    if not observed["avatar"]["enabled"] or not observed["avatar"]["file_present"]:
        return None
    path = root / observed["directory"] / AVATAR_FILENAME
    if path.is_symlink():
        raise ValueError("Refusing a linked browser avatar")
    with path.open("rb") as handle:
        data = handle.read(MAX_AVATAR_BYTES + 1)
    return decode_avatar_png(base64.b64encode(data).decode())


def _replace_avatar(vault: BrowserVault, item: dict, avatar: bytes | None) -> None:
    old = [attachment for attachment in (item.get("attachments") or []) if attachment.get("fileName") == "avatar.png"]
    if avatar is not None:
        # Upload and verify the replacement before removing the previous attachment.
        with tempfile.TemporaryDirectory(prefix="workstation-avatar-") as directory:
            path = Path(directory) / "avatar.png"
            path.write_bytes(avatar)
            path.chmod(0o600)
            vault.run("create", "attachment", "--file", str(path), "--itemid", item["id"])
        updated = vault.item(item["id"])
        old_ids = {entry["id"] for entry in (item.get("attachments") or [])}
        new = [
            entry
            for entry in (updated.get("attachments") or [])
            if entry.get("fileName") == "avatar.png" and entry["id"] not in old_ids
        ]
        if len(new) != 1 or vault.run("get", "attachment", new[0]["id"], "--itemid", item["id"], "--raw") != avatar:
            raise ValueError("Saved browser logo verification failed; the previous attachment was retained")
    for attachment in old:
        vault.run("delete", "attachment", attachment["id"], "--itemid", item["id"])


def _local_patch(item: dict, observed: dict, kinds: set[str]) -> dict:
    result = copy.deepcopy(item)
    if "renamed" in kinds:
        result["name"] = observed["label"]
    if "theme_color" in kinds:
        fields = result.get("fields", [])
        old: dict = next(
            (field for field in fields if field["name"] == "theme_colors"),
            {"name": "theme_colors", "type": 0, "value": ""},
        )
        result["fields"] = [field for field in fields if field["name"] != "theme_colors"]
        if observed["theme_color"] is not None:
            colors = [observed["theme_color"], *old["value"].split(",")[1:]]
            result["fields"].append({**old, "value": ", ".join(color.strip() for color in colors)})
    return result


def _save_local_profile(vault: BrowserVault, root: Path, declaration: dict, observed: dict, kinds: set[str]) -> None:
    item = vault.selected_item(declaration)
    payload = _local_patch(item, observed, kinds)
    if payload != item:
        encoded = vault.run("encode", data=json.dumps(payload).encode())
        vault.run("edit", "item", item["id"], data=encoded)
    if "avatar" in kinds:
        _replace_avatar(vault, item, _local_avatar(root, observed))
    vault.run("sync")
    saved = vault.item(item["id"])
    if any(saved.get(key) != payload.get(key) for key in ("id", "name", "notes", "fields", "collectionIds")):
        raise ValueError("Saved browser metadata verification failed; backup stopped")
    # The normal metadata validator also rejects missing recovery words and duplicate avatars.
    metadata = bitwarden_browser_profiles([saved])[0]
    if "avatar" in kinds:
        avatar = _local_avatar(root, observed)
        attachment = metadata.get("avatar_attachment_id")
        if avatar is None:
            matches = attachment is None
        else:
            matches = (
                attachment is not None
                and vault.run("get", "attachment", attachment, "--itemid", item["id"], "--raw") == avatar
            )
        if not matches:
            raise ValueError("Saved browser logo verification failed; backup stopped")


def _restore_profiles(user_data_dir: str, profiles: list[dict], inspection: dict, check_mode: bool) -> bool:
    """Repair only drifted metadata and the required selection flag, preserving other settings."""

    identities = {issue["id"] for issue in inspection["drift"] if issue.get("id") and issue["kind"] in _REMOTE_KINDS}
    changed = seed_browser_profiles(
        user_data_dir,
        [profile for profile in profiles if profile["id"].strip() in identities],
        check_mode,
        replace_names=True,
    )
    pending = []
    for directory in sorted(sync_everything_drift(inspection)):
        path = Path(user_data_dir) / directory / "Preferences"
        if not path.is_file():
            raise ValueError("Browser profile settings disappeared; retry backup")
        preferences = _read_settings(path)
        _object(preferences, "sync")["keep_everything_synced"] = True
        pending.append((path, preferences))
    if pending and not check_mode:
        if _brave_running() or os.path.lexists(Path(user_data_dir) / "SingletonLock"):
            raise ValueError("Close Brave completely before enabling Sync everything")
        for path, preferences in pending:
            _write_file(path, preferences)
    return changed or bool(pending)


def sync_browser_profiles(
    user_data_dir: str, profiles: list[dict], direction: str, vault: BrowserVault, check_mode: bool = False
) -> bool:
    """Apply the approved direction, then verify the fields this operation owns."""

    if direction not in {"save", "restore"}:
        raise ValueError("Unsupported browser synchronization direction")
    inspection = inspect_browser_profiles(user_data_dir, profiles)
    if direction not in browser_sync_directions(inspection):
        return False
    root = Path(user_data_dir)
    if _brave_running():
        raise BrowserSyncBlocked(
            "Close Brave completely: a Brave process is still running. Use Brave's menu to exit, then retry."
        )
    if os.path.lexists(root / "SingletonLock"):
        raise BrowserSyncBlocked(
            "Close Brave completely: its profile lock is still present. "
            "If Brave is already closed, reopen it and exit normally, then retry."
        )
    if direction == "restore":
        changed = _restore_profiles(user_data_dir, profiles, inspection, check_mode)
        if not check_mode:
            verified = inspect_browser_profiles(user_data_dir, profiles)
            declared_ids = {profile["id"].strip() for profile in profiles}
            if sync_everything_drift(verified) or any(
                issue["kind"] in _REMOTE_KINDS and issue.get("id") in declared_ids for issue in verified["drift"]
            ):
                raise ValueError("Restored browser settings verification failed; backup stopped")
        return changed
    if check_mode:
        return True
    try:
        unlocked = json.loads(vault.run("status")).get("status") == "unlocked"
    except (ValueError, AttributeError) as error:
        raise ValueError("Bitwarden returned an invalid session status") from error
    if not unlocked:
        raise ValueError("Bitwarden session is locked or expired; rerun backup to unlock it")
    vault.run("sync")
    observed = {profile["directory"]: profile for profile in inspection["profiles"]}
    for declaration in profiles:
        kinds = {
            issue["kind"] for issue in inspection["drift"] if issue["directory"] == declaration["directory"]
        } & _LOCAL_KINDS
        if kinds:
            _save_local_profile(vault, root, declaration, observed[declaration["directory"]], kinds)
    return True
