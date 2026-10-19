"""Execute approved live browser recovery actions, returning only safe summaries."""

from __future__ import annotations

import copy
import json
import textwrap
from pathlib import Path

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_cdp import (
    BrowserPipe,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_lifecycle import (
    BrowserLifecycleBlocked,
    automation_arguments,
    closed_browser,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_native_sync import (
    NativeSync,
    recovery_words,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_inspection import (
    inspect_browser_profiles,
    sync_everything_drift,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_preferences import (
    PROFILE_PREFERENCE_DEFAULTS,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_reporting import (
    _DEVICE_CLEANUP_NOTICE,
    _text,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_sync import (
    BrowserVault,
    sync_browser_profiles,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_sync_devices import (
    disposable_device_names,
)

_MESSAGES = {
    "check": "Synchronize and verify browser recovery.",
    "code_mismatch": "Brave and Bitwarden have different recovery codes.",
    "invalid_note": "Bitwarden does not contain a usable Brave recovery code.",
    "not_connected": "Brave is not connected to the saved recovery chain.",
    "pending": "Sync has not finished successfully; the server may be unavailable or changes are still pending.",
}


def live_sync_report(profiles: list[dict], issues: list[dict]) -> dict:
    """Keep prompts short: choose an operation, never inspect pages or compare words."""

    groups: dict[str, list[str]] = {}
    for profile in issues or profiles:
        status = profile["status"] if issues else "check"
        groups.setdefault(status, []).append(f"{_text(profile['label'])} ({_text(profile['directory'])})")
    sections = []
    for status, labels in groups.items():
        affected = textwrap.wrap(
            "Profiles: " + "; ".join(labels), width=88, initial_indent="  ", subsequent_indent="  "
        )
        sections.append(_MESSAGES[status] + "\n" + "\n".join(affected))
    summary = "\n\n".join(sections)
    summary += "\nBrave will close safely during this operation and reopen if it was running."
    summary += "\n" + _DEVICE_CLEANUP_NOTICE
    if not issues:
        return {
            "summary": summary,
            "actions": {"sync": "Run Sync and check every recovery code against Bitwarden automatically."},
        }

    actions = {"retry": "Re-run Sync and verify recovery after you reconcile Brave or Bitwarden manually."}
    save_candidates = [issue for issue in issues if issue["status"] in {"code_mismatch", "invalid_note"}]
    restore_candidates = [issue for issue in issues if issue["status"] in {"code_mismatch", "not_connected"}]
    if save_candidates:
        actions["save"] = "Save the current Brave recovery codes to their Bitwarden notes, then verify Sync."
    if restore_candidates:
        actions["restore"] = "Connect affected profiles to their Bitwarden recovery chains, then verify Sync."
    return {"summary": summary, "actions": actions}


def _save_code(vault: BrowserVault, declaration: dict, item: dict, code: str) -> None:
    current = vault.selected_item(declaration)
    if current != item:
        raise ValueError("A browser recovery record changed during synchronization; retry backup")
    payload = copy.deepcopy(item)
    payload["notes"] = code
    encoded = vault.run("encode", data=json.dumps(payload).encode())
    vault.run("edit", "item", item["id"], data=encoded)
    vault.run("sync")
    saved = vault.selected_item(declaration)
    if any(
        saved.get(key) != payload.get(key) for key in ("id", "name", "notes", "fields", "collectionIds", "attachments")
    ):
        raise ValueError("Saved browser recovery code verification failed; backup stopped")


def _verify_profile(native: NativeSync, declaration: dict, action: str, vault: BrowserVault, state: dict) -> str | None:
    """Reconcile one selected chain and verify both the upload and the recovery note."""

    item = vault.selected_item(declaration)
    # A saved seed still identifies a chain when startup or incomplete setup has
    # left stale transport flags. Compare it before considering enrollment;
    # rejoining a matching chain can replace its device identity.
    connected = state["seed_present"]
    if not connected and action != "restore":
        return "not_connected"
    local = native.code() if connected else None
    try:
        remote = recovery_words(item["notes"])
    except ValueError:
        if action == "save" and local is not None:
            _save_code(vault, declaration, item, local)
            remote = local
        else:
            return "invalid_note"
    if local != remote:
        if action == "save" and local is not None:
            _save_code(vault, declaration, item, local)
        elif action == "restore":
            native.restore(remote, reset=connected)
        else:
            return "code_mismatch"
    if not native.wait():
        if action != "sync":
            raise ValueError(
                "Brave did not finish Sync after the approved recovery change; "
                f"incomplete checks: {native.pending_reason}"
            )
        return "pending"
    vault.run("sync")
    if native.code() != recovery_words(vault.selected_item(declaration)["notes"]):
        raise ValueError("Browser recovery code changed during verification; backup stopped")
    native.prune_devices()
    choices = {key: declaration[key] for key in PROFILE_PREFERENCE_DEFAULTS if declaration.get(key) is not None}
    if choices:
        native.profile_preferences(choices, restore=action == "restore")
    return None


def _declared_profiles(profiles: list[dict], inspection: dict) -> list[dict]:
    """Use the inspector's validated defaults for optional labels and directories."""

    declarations = {profile["id"].strip(): profile for profile in profiles}
    return [
        {**declarations[profile["id"]], **{key: profile[key] for key in ("id", "label", "directory")}}
        for profile in inspection["profiles"]
    ]


def _verify_saved_profiles(user_data_dir: str, profiles: list[dict], vault: BrowserVault) -> None:
    """Check flushed native settings before accepting recovery or repairing profile metadata."""

    inspection = inspect_browser_profiles(user_data_dir, profiles)
    if any(issue["kind"] in PROFILE_PREFERENCE_DEFAULTS for issue in inspection["drift"]):
        raise ValueError("Brave did not retain the verified profile preferences; retry browser recovery")
    if inspection["drift"] or sync_everything_drift(inspection):
        sync_browser_profiles(user_data_dir, profiles, "restore", vault)
        inspection = inspect_browser_profiles(user_data_dir, profiles)
    if inspection["drift"] or sync_everything_drift(inspection):
        raise ValueError("Sync changed saved profile settings; rerun backup to reconcile the new drift")


# Keep module inputs explicit; preview and cleanup controls are keyword-only.
# pylint: disable-next=too-many-arguments
def sync_browser_recovery(
    user_data_dir: str,
    profiles: list[dict],
    action: str,
    vault: BrowserVault,
    *,
    check_mode: bool = False,
    disposable_names: list[str] | None = None,
) -> dict:
    """Synchronize actual profiles and compare codes in memory, never exporting secrets."""

    disposable_names = disposable_device_names([] if disposable_names is None else disposable_names)
    if action == "retry":
        action = "sync"
    if action not in {"sync", "save", "restore"}:
        raise ValueError("Unsupported live browser recovery action")
    inspection = inspect_browser_profiles(user_data_dir, profiles)
    if inspection["drift"]:
        raise ValueError("Browser metadata changed; reconcile profiles before live synchronization")
    profiles = _declared_profiles(profiles, inspection)
    if not profiles:
        raise ValueError("No declared browser profiles to synchronize")
    if check_mode:
        return {"changed": False, "verified": False, "issues": [], **live_sync_report(profiles, [])}
    issues = []
    vault.run("sync")
    with closed_browser(user_data_dir) as (executable, environment):
        if not (environment.get("DISPLAY") or environment.get("WAYLAND_DISPLAY")):
            raise BrowserLifecycleBlocked(
                "The desktop session is unavailable; log in to GNOME and retry browser recovery"
            )
        # Re-read preferences after a graceful exit flushes changes to disk.
        inspection = inspect_browser_profiles(user_data_dir, profiles)
        observed = {profile["directory"]: profile for profile in inspection["profiles"]}
        if inspection["drift"]:
            raise ValueError("Browser metadata changed while closing; retry browser recovery")
        for declaration in profiles:
            state = observed[declaration["directory"]]["sync"]
            if state["managed"] is True or state["keep_everything_synced"] is not True:
                raise ValueError(
                    "Browser Sync is blocked by policy or Sync everything is disabled; retry browser recovery"
                )
            # Restore session tabs before creating our diagnostic pages. Closing
            # only those pages preserves the user's session for a normal restart.
            with BrowserPipe(
                automation_arguments(executable, user_data_dir, declaration["directory"]),
                environment,
            ) as pipe:
                status = _verify_profile(
                    NativeSync(
                        pipe, str(Path(user_data_dir) / declaration["directory"]), disposable_names=disposable_names
                    ),
                    declaration,
                    action,
                    vault,
                    state,
                )
                if status:
                    issues.append({**{key: declaration[key] for key in ("id", "directory", "label")}, "status": status})
        _verify_saved_profiles(user_data_dir, profiles, vault)
    return {"changed": True, "verified": not issues, "issues": issues, **live_sync_report(profiles, issues)}
