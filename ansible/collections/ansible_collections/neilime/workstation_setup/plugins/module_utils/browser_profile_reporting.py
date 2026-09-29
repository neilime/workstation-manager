"""Turn safe Brave inspection metadata into grouped recovery instructions."""

from __future__ import annotations

import textwrap

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_inspection import (
    sync_everything_drift,
)

_ACTIONS = {
    "sync_everything_not_enabled": (
        "Enable Sync everything.",
        "Open brave://settings/braveSync in each listed profile and select Sync everything.",
    ),
    "sync_disabled_by_policy": (
        "Resolve the policy blocking Sync.",
        "Check brave://policy for SyncDisabled and resolve the blocking policy before retrying.",
    ),
    "undeclared": (
        "Add local profiles to Bitwarden.",
        "Create a profile record in the configured browser collection, including its directory and recovery words.",
    ),
    "missing": (
        "Restore missing local profiles.",
        "Choose restore to recreate these profiles. The next Sync check can connect their stored chains.",
    ),
    "renamed": (
        "Match profile names with Bitwarden.",
        "Choose restore for the stored name, or save to keep the local name in Bitwarden.",
    ),
    "theme_color": (
        "Reconcile profile colors.",
        "Choose restore for stored colors, or save to save the local color choice.",
    ),
    "missing_avatar_file": (
        "Restore missing profile logos.",
        "Choose restore to restore the logos from Bitwarden.",
    ),
    "avatar_content_changed": (
        "Reconcile changed profile logos.",
        "Choose restore for stored logos, or save to save the local logo choice.",
    ),
    "avatar_disabled": (
        "Select the stored profile logos.",
        "Choose restore to select stored logos, or save to stop storing the disabled logos.",
    ),
    "unregistered": (
        "Register profiles in Brave's profile picker.",
        "Choose restore to register these existing profiles once their records exist.",
    ),
    "missing_preferences": (
        "Restore missing profile settings.",
        "Choose restore to recreate saved profile settings automatically.",
    ),
}
_SYNC_ISSUES = frozenset(
    (
        "missing_sync_seed",
        "sync_not_requested",
        "sync_everything_not_enabled",
        "sync_setup_incomplete",
        "sync_disabled_by_policy",
    )
)
_AVATAR_ISSUES = ("missing_avatar_file", "avatar_content_changed", "avatar_disabled")
_PROFILE_KINDS = frozenset(
    ("undeclared", "missing", "renamed", "theme_color", "avatar", "unregistered", "missing_preferences")
)


def _text(value: object) -> str:
    """Keep metadata on one printable line without interpreting terminal controls."""

    if not isinstance(value, str):
        raise ValueError("Browser recovery display metadata must be text")
    return "".join(character if character.isprintable() else " " for character in value).strip()


def _records(inspection: dict, key: str) -> list[dict]:
    records = inspection.get(key)
    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        raise ValueError(f"Browser recovery {key} must be a list of records")
    return records


def _issues(record: dict, supported: frozenset[str] | tuple[str, ...]) -> list[str]:
    issues = record.get("issues")
    if (
        not isinstance(issues, list)
        or not issues
        or any(not isinstance(issue, str) or issue not in supported for issue in issues)
    ):
        raise ValueError("Unsupported browser recovery issue")
    return issues


def _profile(record: dict, profiles: dict) -> str:
    directory = _text(record.get("directory"))
    observed = profiles.get(record["directory"], {})
    label = _text(observed.get("label") or record.get("observed_label") or record.get("id") or directory)
    return f"{label} ({directory})" if label != directory else directory


def _profile_drift(record: dict, profiles: dict) -> tuple[str, str]:
    """Select one remedy and retain the details needed to reconcile a profile."""

    kind = record.get("kind")
    if not isinstance(kind, str) or kind not in _PROFILE_KINDS:
        raise ValueError("Unsupported browser profile drift category")
    description = _profile(record, profiles)
    if kind == "avatar":
        issues = _issues(record, _AVATAR_ISSUES)
        # Restoring a missing or changed logo also selects it. Avoid asking
        # for two fixes for the same file when avatar_disabled accompanies it.
        kind = next(issue for issue in _AVATAR_ISSUES if issue in issues)
    elif kind == "renamed":
        description += (
            f': named "{_text(record.get("observed_label"))}", expected "{_text(record.get("configured_label"))}"'
        )
    elif kind == "theme_color":
        description += (
            f": color {_text(record.get('observed_color') or 'unset')}, "
            f"expected {_text(record.get('configured_color'))}"
        )
    return kind, description


def browser_recovery_inspection(inspection: dict) -> dict:
    """Leave chain enrollment to live automation; retain metadata and policy blockers."""

    records = []
    for record in _records(inspection, "sync_issues"):
        issues = [issue for issue in _issues(record, _SYNC_ISSUES) if issue in _ACTIONS]
        if issues:
            records.append({**record, "issues": issues})
    return {**inspection, "sync_issues": records}


def browser_recovery_report(inspection: dict) -> str:
    """Group known diagnostics by action, never displaying notes, images, or seeds."""

    if not isinstance(inspection, dict):
        raise ValueError("Browser recovery inspection must be an object")
    profiles = {_text(profile.get("directory")): profile for profile in _records(inspection, "profiles")}
    groups: dict[str, list[str]] = {}
    sync_issues = browser_recovery_inspection(inspection)["sync_issues"]
    for record in sync_issues:
        for issue in _issues(record, _SYNC_ISSUES):
            groups.setdefault(issue, []).append(_profile(record, profiles))
    for record in _records(inspection, "drift"):
        kind, description = _profile_drift(record, profiles)
        groups.setdefault(kind, []).append(description)
    if not groups:
        if not profiles:
            return "No browser profiles to check."
        return (
            f"Saved browser settings match for {len(profiles)} {'profile' if len(profiles) == 1 else 'profiles'}. "
            "Live Sync is not verified."
        )
    lines = [
        "Fix this browser recovery issue:" if len(groups) == 1 else f"Fix these {len(groups)} browser recovery issues:"
    ]
    restorable_sync = sync_everything_drift(inspection)
    for number, key in enumerate((key for key in _ACTIONS if key in groups), start=1):
        title, action = _ACTIONS[key]
        if key == "sync_everything_not_enabled" and all(
            record["directory"] in restorable_sync for record in sync_issues if key in record["issues"]
        ):
            action = "Choose restore to enable Sync everything automatically."
        lines.extend(("", f"{number}. {title}"))
        affected = "; ".join(dict.fromkeys(groups[key]))
        lines.extend(textwrap.wrap("Profiles: " + affected, width=88, initial_indent="   ", subsequent_indent="   "))
        lines.extend(textwrap.wrap(action, width=88, initial_indent="   ", subsequent_indent="   "))
    if any(
        record["directory"] not in restorable_sync or record["issues"] != ["sync_everything_not_enabled"]
        for record in sync_issues
    ):
        lines.extend(("", "After changing Sync settings, close Brave to save them before retrying."))
    return "\n".join(lines)


def browser_sync_report(inspection: dict) -> str:
    """Describe automatic verification without asking users to inspect secrets."""

    if not isinstance(inspection, dict):
        raise ValueError("Browser recovery inspection must be an object")
    profiles = {_text(profile.get("directory")): profile for profile in _records(inspection, "profiles")}
    if not profiles:
        return "No browser profiles to check."
    lines = ["Synchronize and verify browser recovery.", "Profiles:"]
    for profile in profiles.values():
        lines.extend(
            textwrap.wrap(_profile(profile, profiles), width=88, initial_indent="  - ", subsequent_indent="    ")
        )
    lines.extend(
        (
            "",
            "The script will run Sync and compare recovery codes with Bitwarden automatically.",
            "Brave will close safely during this operation and reopen if it was running.",
        )
    )
    return "\n".join(lines)
