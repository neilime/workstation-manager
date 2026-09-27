"""Read browser profile declarations from Bitwarden without returning recovery words."""

from __future__ import annotations

import re
from typing import NotRequired, TypedDict
from uuid import UUID

from ansible_collections.neilime.workstation_setup.plugins.module_utils.bitwarden_item_fields import (
    BitwardenItemFieldReader,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_paths import (
    BrowserProfilePathsPlanner,
)


class BrowserProfileMetadata(TypedDict):
    """Sanitized fields returned by the profile collection loader."""

    id: str
    label: str
    directory: str
    item_id: str
    theme_colors: NotRequired[list[str]]
    avatar_attachment_id: NotRequired[str]


def _profile_fields(item: dict, reader: BitwardenItemFieldReader) -> dict[str, str]:
    """Read supported custom fields while ignoring unrelated secret metadata."""

    values = {}
    for field in reader.fields(item.get("fields")):
        name = field.get("name")
        if not isinstance(name, str):
            raise ValueError("custom field names must be strings")
        if name not in {"id", "directory", "theme_colors"}:
            continue
        if name in values:
            raise ValueError(f"custom field '{name}' must occur exactly once")
        values[name] = reader.required_string(field.get("value"), f"custom field '{name}'")
    if "id" not in values or "directory" not in values:
        raise ValueError("required custom fields 'id' and 'directory' must both exist")
    return values


def _avatar_attachment_id(item: dict) -> str | None:
    """Select one named avatar without returning attachment URLs or keys."""

    attachments = item.get("attachments")
    if attachments is None:
        return None
    if not isinstance(attachments, list) or any(not isinstance(attachment, dict) for attachment in attachments):
        raise ValueError("attachments must be a list of records")
    avatars = [attachment for attachment in attachments if attachment.get("fileName") == "avatar.png"]
    if len(avatars) > 1:
        raise ValueError("attachment 'avatar.png' must occur at most once")
    if not avatars:
        return None
    attachment_id = avatars[0].get("id")
    if not isinstance(attachment_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", attachment_id):
        raise ValueError("attachment 'avatar.png' must have a safe nonempty ID")
    return attachment_id


def _profile_metadata(item: object) -> BrowserProfileMetadata:
    """Validate a secure note and retain only the supported profile metadata."""

    if not isinstance(item, dict) or item.get("type") != 2 or item.get("deletedDate"):
        raise ValueError("item must be an active secure note")
    item_id = item.get("id")
    try:
        if not isinstance(item_id, str) or str(UUID(item_id)) != item_id:
            raise ValueError
    except ValueError as error:
        raise ValueError("item ID must be a canonical UUID") from error
    reader = BitwardenItemFieldReader()
    label = reader.required_string(item.get("name"), "item name")
    if not label.isprintable():
        raise ValueError("item name must not contain control characters")
    reader.required_string(item.get("notes"), "recovery words")
    values = _profile_fields(item, reader)
    planner = BrowserProfilePathsPlanner()
    profile_id = planner.validate_profile_id(values["id"])
    directory = planner.validate_profile_directory(values["directory"])
    if directory in {"System Profile", "Guest Profile"}:
        raise ValueError("system and guest profile directories cannot be managed")
    profile: BrowserProfileMetadata = {
        "id": profile_id,
        "label": label,
        "directory": directory,
        "item_id": item_id,
    }
    if "theme_colors" in values:
        colors = [color.strip().upper() for color in values["theme_colors"].split(",")]
        if not 1 <= len(colors) <= 3 or any(not re.fullmatch(r"#[0-9A-F]{6}", color) for color in colors):
            raise ValueError("custom field 'theme_colors' must contain one to three comma-separated #RRGGBB colors")
        profile["theme_colors"] = colors
    attachment_id = _avatar_attachment_id(item)
    if attachment_id is not None:
        profile["avatar_attachment_id"] = attachment_id
    return profile


def bitwarden_browser_profiles(items: object) -> list[BrowserProfileMetadata]:
    """Validate every selected secure note and return only safe profile metadata."""

    if not isinstance(items, list) or not items:
        raise ValueError("Browser profile collection must contain at least one accessible secure note")
    profiles = []
    identities: tuple[set[str], set[str], set[str]] = (set(), set(), set())
    for index, item in enumerate(items):
        try:
            profile = _profile_metadata(item)
            profile_identity = (profile["item_id"], profile["id"], profile["directory"])
            if any(value in known for value, known in zip(profile_identity, identities)):
                raise ValueError("item IDs, profile IDs, and directories must be unique within the collection")
            for value, known in zip(profile_identity, identities):
                known.add(value)
            profiles.append(profile)
        except ValueError as error:
            # Positions identify malformed records without echoing secret notes or values.
            raise ValueError(f"Browser profile collection item {index + 1}: {error}") from error
    return sorted(profiles, key=lambda profile: profile["id"])
