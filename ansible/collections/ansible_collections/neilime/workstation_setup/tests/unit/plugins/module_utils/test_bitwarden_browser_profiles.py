"""Validate collection-driven browser metadata without exposing recovery words."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.bitwarden_browser_profiles import (
    bitwarden_browser_profiles,
)

_ITEM_ID = "11111111-1111-4111-8111-111111111111"
_SECRET = "synthetic recovery words must never enter a public result"


def profile_item(**overrides):
    """Return one valid synthetic secure note."""

    return {
        "id": _ITEM_ID,
        "type": 2,
        "name": "Personal",
        "notes": _SECRET,
        "fields": [{"name": "id", "value": "personal"}, {"name": "directory", "value": "Default"}],
        **overrides,
    }


def test_parser_returns_only_profile_identity_metadata_without_mutating_records():
    """Public profile metadata excludes recovery words and preserves the source record."""

    item = profile_item()
    original = deepcopy(item)
    result = bitwarden_browser_profiles([item])
    assert result == [{"id": "personal", "label": "Personal", "directory": "Default", "item_id": _ITEM_ID}]
    assert _SECRET not in json.dumps(result)
    assert item == original


@pytest.mark.parametrize("items", [None, {}, "secret value", []])
def test_missing_or_inaccessible_collection_never_becomes_an_empty_profile_list(items):
    """An unavailable collection must fail instead of appearing successfully empty."""

    with pytest.raises(ValueError, match="at least one accessible secure note"):
        bitwarden_browser_profiles(items)


@pytest.mark.parametrize(
    "overrides",
    [
        {"type": 1},
        {"deletedDate": "2026-01-01"},
        {"id": "not-a-uuid"},
        {"id": "1" * 32},
        {"id": None},
        {"name": ""},
        {"name": "bad\nname"},
        {"notes": " "},
        {"notes": None},
        {"notes": {}},
        {"fields": None},
        {"fields": {}},
        {"fields": [None]},
        {"fields": [{"name": "id", "value": "personal"}]},
        {"fields": [{"name": None, "value": _SECRET}]},
        {"fields": [{"name": "id", "value": "personal"}, {"name": "id", "value": "work"}]},
    ],
)
def test_invalid_secure_notes_fail_without_disclosing_contents(overrides):
    """Invalid records identify their position without exposing their contents."""

    with pytest.raises(ValueError) as error:
        bitwarden_browser_profiles([profile_item(**overrides)])
    assert "collection item 1:" in str(error.value)
    assert _SECRET not in str(error.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "../escape"),
        ("id", "Personal"),
        ("id", []),
        ("id", ""),
        ("directory", "../escape"),
        ("directory", "/tmp/outside"),
        ("directory", "bad/name"),
        ("directory", "System Profile"),
        ("directory", "Guest Profile"),
        ("directory", None),
    ],
)
def test_profile_paths_must_be_safe_and_explicit(field, value):
    """Profile identifiers and directories reject unsafe or ambiguous values."""

    item = profile_item()
    next(entry for entry in item["fields"] if entry["name"] == field)["value"] = value
    with pytest.raises(ValueError):
        bitwarden_browser_profiles([item])


@pytest.mark.parametrize("duplicate", ["item_id", "id", "directory"])
def test_duplicate_record_or_profile_identities_are_rejected(duplicate):
    """Each record must map to a unique vault item, profile identifier, and directory."""

    second = profile_item(
        id="22222222-2222-4222-8222-222222222222",
        name="Work",
        fields=[{"name": "id", "value": "work"}, {"name": "directory", "value": "Profile 1"}],
    )
    if duplicate == "item_id":
        second["id"] = _ITEM_ID
    else:
        next(field for field in second["fields"] if field["name"] == duplicate)["value"] = (
            "personal" if duplicate == "id" else "Default"
        )
    with pytest.raises(ValueError, match="must be unique"):
        bitwarden_browser_profiles([profile_item(), second])


def test_collection_order_does_not_change_profile_order_and_extra_fields_are_not_returned():
    """Sorted profile metadata remains deterministic and excludes unrelated fields."""

    work = profile_item(
        id="22222222-2222-4222-8222-222222222222",
        name="Work",
        fields=[
            {"name": "id", "value": "work"},
            {"name": "directory", "value": "Profile 1"},
            {"name": "extra_secret", "value": _SECRET},
        ],
    )
    result = bitwarden_browser_profiles([work, profile_item()])
    assert [profile["id"] for profile in result] == ["personal", "work"]
    assert result[1]["directory"] == "Profile 1"
    assert _SECRET not in json.dumps(result)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("#0079b3", ["#0079B3"]),
        (" #1c3144, #ecb807 ", ["#1C3144", "#ECB807"]),
        ("#0079B3, #E4844A, #002C59", ["#0079B3", "#E4844A", "#002C59"]),
    ],
)
def test_optional_theme_colors_preserve_order_and_normalize_hex_without_mutating_records(value, expected):
    """Palette normalization preserves priority and leaves vault records untouched."""

    item = profile_item()
    item["fields"].append({"name": "theme_colors", "value": value})
    original = deepcopy(item)
    result = bitwarden_browser_profiles([item])
    assert result[0]["theme_colors"] == expected
    assert _SECRET not in json.dumps(result)
    assert item == original


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        123,
        "",
        "   ",
        "#123",
        "112233",
        "#11223344",
        "#GG2233",
        "#112233,",
        ",#112233",
        "#112233,,#445566",
        "#112233;#445566",
        "#112233,#445566,#778899,#AABBCC",
        _SECRET,
    ],
)
def test_invalid_theme_colors_fail_without_disclosing_the_field_value(value):
    """Palette errors explain the invalid field without returning its contents."""

    item = profile_item()
    item["fields"].append({"name": "theme_colors", "value": value})
    with pytest.raises(ValueError) as error:
        bitwarden_browser_profiles([item])
    message = str(error.value)
    assert "collection item 1:" in message
    assert "custom field 'theme_colors'" in message
    assert _SECRET not in message
    if isinstance(value, str) and value.strip():
        assert value not in message


def test_duplicate_theme_color_fields_are_rejected_without_disclosing_values():
    """Duplicate palette declarations fail without exposing either value."""

    item = profile_item()
    item["fields"].extend(
        [
            {"name": "theme_colors", "value": "#112233"},
            {"name": "theme_colors", "value": _SECRET},
        ]
    )
    with pytest.raises(ValueError, match="custom field 'theme_colors' must occur exactly once") as error:
        bitwarden_browser_profiles([item])
    assert _SECRET not in str(error.value)
    assert "#112233" not in str(error.value)


@pytest.mark.parametrize("attachments", [None, [], [{"fileName": "other.png", "id": "../ignored"}]])
def test_profiles_without_avatar_attachment_leave_existing_browser_avatar_unmanaged(attachments):
    """An absent managed attachment leaves the local avatar outside desired state."""

    result = bitwarden_browser_profiles([profile_item(attachments=attachments)])
    assert "avatar_attachment_id" not in result[0]


@pytest.mark.parametrize("attachment_id", ["f0a9", "a1b2-3C4D", "11111111-1111-4111-8111-111111111111"])
def test_avatar_attachment_returns_only_safe_identity_without_mutating_records(attachment_id):
    """Attachment metadata exports its identifier without URLs, keys, or mutation."""

    item = profile_item(
        attachments=[
            {
                "id": attachment_id,
                "fileName": "avatar.png",
                "url": _SECRET,
                "key": _SECRET,
            }
        ]
    )
    original = deepcopy(item)
    result = bitwarden_browser_profiles([item])
    assert result[0]["avatar_attachment_id"] == attachment_id
    assert _SECRET not in json.dumps(result)
    assert item == original


@pytest.mark.parametrize("attachments", ["private data", {}, [None], ["private data"]])
def test_malformed_attachment_list_fails_without_disclosing_values(attachments):
    """Invalid attachment containers fail without echoing their contents."""

    with pytest.raises(ValueError, match="collection item 1: attachments must be a list of records"):
        bitwarden_browser_profiles([profile_item(attachments=attachments)])


@pytest.mark.parametrize("attachment_id", [None, "", " ", "../escape", "--output", "a_b", "é", "a\n", 3, _SECRET])
def test_avatar_attachment_identity_must_be_safe_without_disclosing_the_value(attachment_id):
    """Attachment identifiers must be safe command arguments and remain private on error."""

    with pytest.raises(ValueError, match="attachment 'avatar.png' must have a safe nonempty ID") as error:
        bitwarden_browser_profiles([profile_item(attachments=[{"fileName": "avatar.png", "id": attachment_id}])])
    assert _SECRET not in str(error.value)


def test_duplicate_avatar_attachments_fail_even_if_their_ids_match():
    """Multiple named avatars are ambiguous even when their identifiers match."""

    avatar = {"fileName": "avatar.png", "id": "a1b2"}
    with pytest.raises(ValueError, match="attachment 'avatar.png' must occur at most once"):
        bitwarden_browser_profiles([profile_item(attachments=[avatar, avatar])])
