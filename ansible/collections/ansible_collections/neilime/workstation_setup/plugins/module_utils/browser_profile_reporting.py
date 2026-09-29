"""Turn safe Brave inspection metadata into grouped recovery instructions."""

from __future__ import annotations

import textwrap

_ACTIONS = {
    "missing_sync_seed": (
        "Connect profiles to their Sync chains.",
        "Open brave://settings/braveSync and join each profile's chain using its Bitwarden recovery note.",
    ),
    "sync_not_requested": (
        "Turn Sync on.",
        "Open brave://settings/braveSync in these profiles and enable Sync.",
    ),
    "sync_everything_not_enabled": (
        "Enable Sync everything.",
        "Open brave://settings/braveSync in each listed profile and select Sync everything.",
    ),
    "sync_setup_incomplete": (
        "Finish Sync setup.",
        "Open brave://settings/braveSync and finish connecting these profiles to their stored Sync chains.",
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
        "Close Brave and run workstation.sh setup, then join their stored Sync chains. Keep their Bitwarden records.",
    ),
    "renamed": (
        "Match profile names with Bitwarden.",
        "Rename the profile in Brave, or update its Bitwarden note name if the local rename is intentional.",
    ),
    "theme_color": (
        "Reconcile profile colors.",
        "Close Brave and run workstation.sh setup to apply stored colors, or update theme_colors in Bitwarden.",
    ),
    "missing_avatar_file": (
        "Restore missing profile logos.",
        "Close Brave and run workstation.sh setup to restore the logos from Bitwarden.",
    ),
    "avatar_content_changed": (
        "Reconcile changed profile logos.",
        "Close Brave and run workstation.sh setup, or replace avatar.png in Bitwarden to keep the local logo.",
    ),
    "avatar_disabled": (
        "Select the stored profile logos.",
        "Close Brave and run workstation.sh setup to select the logos from Bitwarden.",
    ),
    "unregistered": (
        "Register profiles in Brave's profile picker.",
        "Close Brave and run workstation.sh setup to register these existing profiles.",
    ),
    "missing_preferences": (
        "Restore missing profile settings.",
        "Close Brave and run workstation.sh setup, then open and close these profiles to save their settings.",
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


def browser_recovery_report(inspection: dict) -> str:
    """Group known diagnostics by action, never displaying notes, images, or seeds."""

    if not isinstance(inspection, dict):
        raise ValueError("Browser recovery inspection must be an object")
    profiles = {_text(profile.get("directory")): profile for profile in _records(inspection, "profiles")}
    groups: dict[str, list[str]] = {}
    sync_issues = _records(inspection, "sync_issues")
    for record in sync_issues:
        for issue in _issues(record, _SYNC_ISSUES):
            groups.setdefault(issue, []).append(_profile(record, profiles))
    for record in _records(inspection, "drift"):
        kind, description = _profile_drift(record, profiles)
        groups.setdefault(kind, []).append(description)
    if not groups:
        if not profiles:
            return "No browser profiles to check."
        noun = "profile" if len(profiles) == 1 else "profiles"
        return f"Saved browser settings match for {len(profiles)} {noun}. Live Sync is not verified."
    lines = [
        "Fix this browser recovery issue:" if len(groups) == 1 else f"Fix these {len(groups)} browser recovery issues:"
    ]
    for number, key in enumerate((key for key in _ACTIONS if key in groups), start=1):
        title, action = _ACTIONS[key]
        lines.extend(("", f"{number}. {title}"))
        affected = "; ".join(dict.fromkeys(groups[key]))
        lines.extend(textwrap.wrap("Profiles: " + affected, width=88, initial_indent="   ", subsequent_indent="   "))
        lines.extend(textwrap.wrap(action, width=88, initial_indent="   ", subsequent_indent="   "))
    if sync_issues:
        lines.extend(("", "After changing Sync settings, close Brave to save them before retrying."))
    return "\n".join(lines)
