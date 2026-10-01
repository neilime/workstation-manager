"""Compare native Brave profiles with Bitwarden collection records without changes."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_avatar import (
    AVATAR_FILENAME,
    decode_avatar_png,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_paths import (
    BrowserProfilePathsPlanner,
)

_IGNORED_PROFILES = {"System Profile", "Guest Profile"}
_SYNC_TYPES = ("bookmarks", "passwords", "extensions", "preferences", "tabs")


def _read_settings(path: Path) -> dict:
    """Read settings without following links or including their contents in errors."""

    if path.is_symlink():
        raise ValueError(f"Refusing symlinked browser settings: {path.name}")
    try:
        with path.open(encoding="utf-8") as handle:
            result = json.load(handle)
    except FileNotFoundError:
        return {}
    except (ValueError, UnicodeError) as error:
        raise ValueError(f"Invalid JSON in browser settings: {path.name}") from error
    if not isinstance(result, dict):
        raise ValueError(f"Expected a JSON object in browser settings: {path.name}")
    return result


def _object(settings: dict, key: str) -> dict:
    result = settings.get(key, {})
    if not isinstance(result, dict):
        raise ValueError(f"Expected a browser settings object for {key}")
    return result


def _label(value: object, fallback: str) -> str:
    if value is None or value == "":
        return fallback
    if not isinstance(value, str):
        raise ValueError("Browser profile names must be strings")
    return "".join(character if character.isprintable() else " " for character in value)


def _boolean(settings: dict, key: str, default: bool | None = None) -> bool | None:
    value = settings.get(key, default)
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"Expected a browser Sync boolean for {key}")
    return value


def _inspect_sync(preferences: dict) -> tuple[dict, list[str]]:
    """Return only presence/boolean metadata; disk settings never prove server sync."""

    sync = _object(preferences, "sync")
    seed = _object(preferences, "brave_sync_v2").get("seed", "")
    metadata = {
        "seed_present": isinstance(seed, str) and bool(seed),
        "requested": _boolean(sync, "requested"),
        # Chromium registers this preference as true; Brave keeps that default.
        "keep_everything_synced": _boolean(sync, "keep_everything_synced", default=True),
        "has_setup_completed": _boolean(sync, "has_setup_completed"),
        "managed": _boolean(sync, "managed"),
        "selected_types": {name: _boolean(sync, name) for name in _SYNC_TYPES},
    }
    issues = []
    if not metadata["seed_present"]:
        issues.append("missing_sync_seed")
    if metadata["requested"] is False:
        issues.append("sync_not_requested")
    if metadata["keep_everything_synced"] is not True:
        issues.append("sync_everything_not_enabled")
    if metadata["has_setup_completed"] is False:
        issues.append("sync_setup_incomplete")
    if metadata["managed"] is True:
        issues.append("sync_disabled_by_policy")
    return metadata, issues


def _declarations(profiles: list[dict], planner: BrowserProfilePathsPlanner) -> dict:
    declarations = {}
    ids = set()
    for declaration in profiles:
        profile_id = planner.validate_profile_id(declaration["id"])
        directory = planner.validate_profile_directory(declaration.get("directory") or f"managed-{profile_id}")
        if profile_id in ids or directory in declarations:
            raise ValueError("Browser profile IDs and directories must be unique")
        if directory in _IGNORED_PROFILES:
            raise ValueError("System and guest profiles cannot be declared as browser profiles")
        ids.add(profile_id)
        colors = declaration.get("theme_colors")
        if colors is not None and (
            not isinstance(colors, list)
            or not 1 <= len(colors) <= 3
            or any(not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color) for color in colors)
        ):
            raise ValueError("Browser theme_colors must contain one to three #RRGGBB colors")
        declarations[directory] = {
            "id": profile_id,
            "label": _label(declaration.get("label"), profile_id),
            "item_id": declaration["item_id"],
        }
        if colors is not None:
            declarations[directory]["theme_color"] = colors[0].upper()
        if declaration.get("avatar_png") is not None:
            declarations[directory]["avatar"] = decode_avatar_png(declaration["avatar_png"])
    return declarations


def _theme_color(preferences: dict) -> str | None:
    """Return the active native color seed, without exposing other theme settings."""

    theme = _object(_object(preferences, "browser"), "theme")
    extension_theme = _object(_object(preferences, "extensions"), "theme")
    color = theme.get("user_color2")
    if (
        extension_theme.get("id") != "user_color_theme_id"
        or extension_theme.get("system_theme", 0) != 0
        or theme.get("is_grayscale2", False) is not False
    ):
        return None
    if not isinstance(color, int) or isinstance(color, bool) or not -0x1000000 <= color < 0:
        return None
    return f"#{color & 0xFFFFFF:06X}"


def _inspect_avatar(path: Path, expected: bytes, preferences: dict, entry: dict) -> tuple[dict, list[str]]:
    """Compare the fixed local file and native selection flags without returning images."""

    if path.is_symlink():
        raise ValueError(f"Refusing symlinked browser avatar: {path.parent.name}")
    present = path.is_file()
    matches = False
    if present:
        with path.open("rb") as handle:
            matches = handle.read(len(expected) + 1) == expected
    enabled = (
        entry.get("gaia_picture_file_name") == AVATAR_FILENAME
        and entry.get("use_gaia_picture") is True
        and entry.get("is_using_default_avatar") is False
        and _object(preferences, "profile").get("using_gaia_avatar") is True
    )
    issues = []
    if not present:
        issues.append("missing_avatar_file")
    elif not matches:
        issues.append("avatar_content_changed")
    if not enabled:
        issues.append("avatar_disabled")
    return {"file_present": present, "content_matches": matches, "enabled": enabled}, issues


def _inspect_profile(root: Path, directory: str, declaration: dict, cache: dict) -> tuple[dict, list]:
    preferences_path = root / directory / "Preferences"
    preferences = _read_settings(preferences_path)
    # Local State owns the profile picker name; Preferences can retain a stale
    # placeholder such as "Your Chromium" after the registered name changes.
    label = _label(
        _object(cache, directory).get("name"),
        _label(_object(preferences, "profile").get("name"), directory),
    )
    identity = {"directory": directory, "id": declaration.get("id")}
    sync, issues = _inspect_sync(preferences)
    observed = {
        **identity,
        "label": label,
        "item_id": declaration.get("item_id"),
        "registered": directory in cache,
        "preferences_present": preferences_path.is_file(),
        "sync": sync,
        "sync_issues": issues,
    }
    drift = []
    if not declaration:
        drift.append({"kind": "undeclared", **identity, "observed_label": label})
    elif label != declaration["label"]:
        drift.append(
            {
                "kind": "renamed",
                **identity,
                "configured_label": declaration["label"],
                "observed_label": label,
            }
        )
    if "theme_color" in declaration:
        observed["theme_color"] = _theme_color(preferences)
        if observed["theme_color"] != declaration["theme_color"]:
            drift.append(
                {
                    "kind": "theme_color",
                    **identity,
                    "configured_color": declaration["theme_color"],
                    "observed_color": observed["theme_color"],
                }
            )
    if "avatar" in declaration:
        observed["avatar"], avatar_issues = _inspect_avatar(
            root / directory / AVATAR_FILENAME,
            declaration["avatar"],
            preferences,
            _object(cache, directory),
        )
        if avatar_issues:
            drift.append({"kind": "avatar", **identity, "issues": avatar_issues})
    if not observed["registered"]:
        drift.append({"kind": "unregistered", **identity})
    if not observed["preferences_present"]:
        drift.append({"kind": "missing_preferences", **identity})
    return observed, drift


def inspect_browser_profiles(user_data_dir: str, profiles: list[dict]) -> dict:
    """Compare sanitized collection records with registered and on-disk profiles.

    A registered profile without Preferences is incomplete. An on-disk profile
    without registration is still included so it cannot silently escape backup.
    Neither inspection nor check mode writes files or contacts a Sync server.
    """

    planner = BrowserProfilePathsPlanner()
    root = planner.validate_user_data_dir(user_data_dir)
    declarations = _declarations(profiles, planner)
    cache = _object(_object(_read_settings(root / "Local State"), "profile"), "info_cache")
    directories = set(cache) - _IGNORED_PROFILES
    if root.exists():
        directories.update(
            child.name
            for child in root.iterdir()
            if child.name not in _IGNORED_PROFILES
            and ((child / "Preferences").exists() or (child / "Preferences").is_symlink())
        )
    inventory = []
    drift = []
    for directory in sorted(directories | set(declarations)):
        planner.validate_profile_directory(directory)
        if (root / directory).is_symlink():
            raise ValueError(f"Refusing symlinked browser profile: {directory}")
        if directory not in directories:
            drift.append({"kind": "missing", "directory": directory, "id": declarations[directory]["id"]})
            continue
        observed, profile_drift = _inspect_profile(root, directory, declarations.get(directory, {}), cache)
        inventory.append(observed)
        drift.extend(profile_drift)
    return {
        "profiles": inventory,
        "drift": drift,
        "sync_issues": [
            {"directory": profile["directory"], "issues": profile["sync_issues"]}
            for profile in inventory
            if profile["sync_issues"]
        ],
    }


def sync_everything_drift(inspection: dict) -> set[str]:
    """Select declared profiles whose Sync-everything setting can be restored."""

    managed = {profile["directory"] for profile in inspection.get("profiles", []) if profile.get("id")}
    return {
        record["directory"]
        for record in inspection.get("sync_issues", [])
        if record.get("directory") in managed and "sync_everything_not_enabled" in record.get("issues", [])
    }
