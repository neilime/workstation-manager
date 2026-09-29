"""Coverage for read-only browser inventory, drift, and local Sync diagnostics."""

from __future__ import annotations

import base64
import json
import struct
import zlib
from pathlib import Path

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_avatar import (
    AVATAR_FILENAME,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_inspection import (
    inspect_browser_profiles,
)

_ITEM_ID = "11111111-1111-4111-8111-111111111111"
_DECLARATION = {"id": "personal", "label": "Personal", "directory": "Default", "item_id": _ITEM_ID}


def _profile(root: Path, directory: str, name: str, sync: dict | None = None) -> Path:
    path = root / directory / "Preferences"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "profile": {"name": name},
                "brave_sync_v2": {"seed": "encrypted-secret-must-not-appear"},
                "sync": sync if sync is not None else {"keep_everything_synced": True, "has_setup_completed": True},
                "other_secret": "unrelated-secret-must-not-appear",
            }
        )
    )
    return path


def _state(root: Path, profiles: dict) -> Path:
    path = root / "Local State"
    path.write_text(json.dumps({"profile": {"info_cache": profiles}}))
    return path


def test_inventory_preserves_bytes_and_exposes_only_safe_sync_metadata(tmp_path: Path) -> None:
    """An inspection must not expose seed material or claim completed server sync."""

    preferences = _profile(tmp_path, "Default", "Personal")
    state = _state(tmp_path, {"Default": {"name": "Personal"}})
    before = {path: path.read_bytes() for path in (preferences, state)}
    result = inspect_browser_profiles(str(tmp_path), [_DECLARATION])
    assert result["drift"] == []
    assert result["sync_issues"] == []
    assert result["profiles"][0]["sync"]["seed_present"] is True
    assert result["profiles"][0]["sync"]["requested"] is None
    assert result["profiles"][0]["item_id"] == _ITEM_ID
    assert "secret-must-not-appear" not in json.dumps(result)
    assert "completed" not in result
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("cached_name", ["Personal", "Renamed"])
def test_registered_name_takes_precedence_over_stale_profile_preferences(tmp_path: Path, cached_name: str) -> None:
    """Brave's profile picker name must win over a stale Preferences placeholder."""

    preferences = _profile(tmp_path, "Default", "Your Chromium")
    state = _state(tmp_path, {"Default": {"name": cached_name}})
    before = {path: path.read_bytes() for path in (preferences, state)}
    result = inspect_browser_profiles(str(tmp_path), [_DECLARATION])
    assert result["profiles"][0]["label"] == cached_name
    assert result["drift"] == (
        []
        if cached_name == "Personal"
        else [
            {
                "kind": "renamed",
                "directory": "Default",
                "id": "personal",
                "configured_label": "Personal",
                "observed_label": "Renamed",
            }
        ]
    )
    assert {path: path.read_bytes() for path in before} == before
    assert "secret-must-not-appear" not in json.dumps(result)


@pytest.mark.parametrize("entry", [{}, {"name": None}, {"name": ""}])
def test_missing_registered_name_falls_back_to_profile_preferences(tmp_path: Path, entry: dict) -> None:
    """An incomplete registry can still use the saved per-profile name."""

    _profile(tmp_path, "Default", "Personal")
    _state(tmp_path, {"Default": entry})
    result = inspect_browser_profiles(str(tmp_path), [_DECLARATION])
    assert result["profiles"][0]["label"] == "Personal"
    assert result["drift"] == []


def test_discovers_unregistered_profiles_and_detects_renames_and_missing_profiles(tmp_path: Path) -> None:
    """Immediate Preferences directories count even if Local State is incomplete."""

    _profile(tmp_path, "Default", "Personal")
    _profile(tmp_path, "Profile 2", "New profile")
    _state(tmp_path, {"Default": {"name": "Renamed"}})
    missing = {"id": "work", "item_id": _ITEM_ID}
    result = inspect_browser_profiles(str(tmp_path), [_DECLARATION, missing])
    assert [(entry["kind"], entry["directory"]) for entry in result["drift"]] == [
        ("renamed", "Default"),
        ("undeclared", "Profile 2"),
        ("unregistered", "Profile 2"),
        ("missing", "managed-work"),
    ]
    assert result["drift"][0]["configured_label"] == "Personal"
    assert result["drift"][0]["observed_label"] == "Renamed"
    assert result["profiles"][1]["id"] is None
    assert result["profiles"][1]["item_id"] is None


def test_registered_missing_preferences_are_incomplete_and_system_profiles_are_ignored(tmp_path: Path) -> None:
    """Stale native registrations require attention while transient profiles do not."""

    _state(tmp_path, {"Default": {"name": "Personal"}, "System Profile": {}, "Guest Profile": {}})
    _profile(tmp_path, "System Profile", "System")
    _profile(tmp_path, "Guest Profile", "Guest")
    result = inspect_browser_profiles(str(tmp_path), [_DECLARATION])
    assert len(result["profiles"]) == 1
    assert result["profiles"][0]["preferences_present"] is False
    assert result["drift"] == [{"kind": "missing_preferences", "directory": "Default", "id": "personal"}]
    assert result["sync_issues"][0]["issues"] == ["missing_sync_seed"]


def test_collection_only_profiles_remain_in_vault_without_creating_local_files(tmp_path: Path) -> None:
    """Collection records absent from a machine remain recoverable and are only reported."""

    root = tmp_path / "missing"
    result = inspect_browser_profiles(str(root), [_DECLARATION])
    assert result["profiles"] == []
    assert result["drift"] == [{"kind": "missing", "directory": "Default", "id": "personal"}]
    assert not root.exists()
    assert _DECLARATION["item_id"] == _ITEM_ID


def test_sync_issues_include_explicit_disabled_and_incomplete_settings(tmp_path: Path) -> None:
    """An encrypted seed alone is insufficient local evidence of configured sync."""

    _profile(
        tmp_path,
        "Default",
        "Personal",
        {
            "requested": False,
            "keep_everything_synced": False,
            "has_setup_completed": False,
            "managed": True,
            "bookmarks": True,
        },
    )
    _state(tmp_path, {"Default": {"name": "Personal"}})
    result = inspect_browser_profiles(str(tmp_path), [_DECLARATION])
    assert result["sync_issues"][0]["issues"] == [
        "sync_not_requested",
        "sync_everything_not_enabled",
        "sync_setup_incomplete",
        "sync_disabled_by_policy",
    ]
    assert result["profiles"][0]["sync"]["selected_types"]["bookmarks"] is True
    assert result["profiles"][0]["sync"]["selected_types"]["passwords"] is None


@pytest.mark.parametrize("settings", ["not valid JSON with sensitive contents", "[]", '{"profile": []}'])
def test_invalid_json_and_structures_fail_without_echoing_contents(tmp_path: Path, settings: str) -> None:
    """Malformed browser state must block a misleading successful inspection."""

    (tmp_path / "Local State").write_text(settings)
    with pytest.raises(ValueError) as error:
        inspect_browser_profiles(str(tmp_path), [])
    assert "sensitive contents" not in str(error.value)
    assert (tmp_path / "Local State").read_text() == settings


@pytest.mark.parametrize("target", ["root", "state", "profile", "preferences"])
def test_symlinks_are_refused(tmp_path: Path, target: str) -> None:
    """Inspection cannot follow a declared or discovered profile outside its root."""

    root = tmp_path / "browser"
    root.mkdir()
    preferences = _profile(root, "Default", "Personal")
    state = _state(root, {"Default": {"name": "Personal"}})
    original = {"root": root, "state": state, "profile": preferences.parent, "preferences": preferences}[target]
    moved = tmp_path / "moved"
    original.rename(moved)
    original.symlink_to(moved)
    with pytest.raises(ValueError, match="symlink"):
        inspect_browser_profiles(str(root), [_DECLARATION])


@pytest.mark.parametrize(
    "declarations",
    [
        [{**_DECLARATION, "directory": "../outside"}],
        [{**_DECLARATION, "directory": "Guest Profile"}],
        [_DECLARATION, _DECLARATION],
    ],
)
def test_invalid_declarations_are_rejected(tmp_path: Path, declarations: list) -> None:
    """Invalid directory mappings must not look synchronized."""

    with pytest.raises(ValueError):
        inspect_browser_profiles(str(tmp_path), declarations)


def test_unsafe_cache_path_is_rejected(tmp_path: Path) -> None:
    """Browser-owned metadata cannot redirect profile inspection outside its root."""

    _state(tmp_path, {"../elsewhere": {}})
    with pytest.raises(ValueError, match="safe single directory"):
        inspect_browser_profiles(str(tmp_path), [])


@pytest.mark.parametrize("registered", [True, False])
def test_labels_are_safe_for_terminal_diagnostics(tmp_path: Path, registered: bool) -> None:
    """Preserve useful Unicode labels without forwarding terminal control characters."""

    label = "Perso é\n\x1b[0m"
    _profile(tmp_path, "Default", "Your Chromium" if registered else label)
    if registered:
        _state(tmp_path, {"Default": {"name": label}})
    result = inspect_browser_profiles(str(tmp_path), [_DECLARATION])
    assert result["profiles"][0]["label"] == "Perso é  [0m"


def test_non_boolean_sync_flag_is_not_treated_as_success(tmp_path: Path) -> None:
    """String values such as false must not become truthy confirmation."""

    _profile(tmp_path, "Default", "Personal", {"keep_everything_synced": "false"})
    with pytest.raises(ValueError, match="Sync boolean"):
        inspect_browser_profiles(str(tmp_path), [_DECLARATION])


@pytest.mark.parametrize(
    "mode,observed",
    [
        ("matching", "#1C3144"),
        ("different", "#123456"),
        ("extension", None),
        ("grayscale", None),
        ("system", None),
        ("invalid", None),
    ],
)
def test_declared_main_color_checks_active_native_theme_without_writes(
    tmp_path: Path, mode: str, observed: str | None
) -> None:
    """A stale seed behind an extension or system theme must not hide color drift."""

    preferences = _profile(tmp_path, "Default", "Personal")
    state = _state(tmp_path, {"Default": {"name": "Personal"}})
    settings = json.loads(preferences.read_text())
    theme: dict[str, object] = {"user_color2": int("1C3144", 16) - (1 << 24), "is_grayscale2": False}
    extension_theme = {"id": "user_color_theme_id", "system_theme": 0}
    if mode == "different":
        theme["user_color2"] = int("123456", 16) - (1 << 24)
    elif mode == "extension":
        extension_theme["id"] = "a-local-theme-extension"
    elif mode == "grayscale":
        theme["is_grayscale2"] = True
    elif mode == "system":
        extension_theme["system_theme"] = 1
    elif mode == "invalid":
        theme["user_color2"] = "secret-must-not-appear"
    settings["browser"] = {"theme": theme}
    settings["extensions"] = {"theme": extension_theme}
    preferences.write_text(json.dumps(settings))
    before = {path: path.read_bytes() for path in (preferences, state)}
    declaration = {**_DECLARATION, "theme_colors": ["#1c3144", "#ECB807", "#FFFFFF"]}
    result = inspect_browser_profiles(str(tmp_path), [declaration])
    assert result["profiles"][0]["theme_color"] == observed
    assert result["drift"] == (
        []
        if mode == "matching"
        else [
            {
                "kind": "theme_color",
                "directory": "Default",
                "id": "personal",
                "configured_color": "#1C3144",
                "observed_color": observed,
            }
        ]
    )
    assert {path: path.read_bytes() for path in before} == before
    assert "secret-must-not-appear" not in json.dumps(result)


def test_unconfigured_palette_does_not_report_or_manage_theme_drift(tmp_path: Path) -> None:
    """An absent palette leaves personal theme choices outside desired state."""

    _profile(tmp_path, "Default", "Personal")
    _state(tmp_path, {"Default": {"name": "Personal"}})
    result = inspect_browser_profiles(str(tmp_path), [_DECLARATION])
    assert result["drift"] == []
    assert "theme_color" not in result["profiles"][0]


def test_invalid_palette_cannot_silently_disable_theme_inspection(tmp_path: Path) -> None:
    """Malformed desired colors must fail instead of hiding theme drift."""

    with pytest.raises(ValueError, match="theme_colors"):
        inspect_browser_profiles(str(tmp_path), [{**_DECLARATION, "theme_colors": []}])


@pytest.fixture(name="avatar_png")
def avatar_png_fixture() -> str:
    """A synthetic one-pixel PNG with no local browser data."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(b"\0\xff\0\xff\xff")) + chunk(b"IEND", b"")
    return base64.b64encode(png).decode()


@pytest.mark.parametrize(
    "mode,issues",
    [
        ("matching", []),
        ("missing", ["missing_avatar_file"]),
        ("different", ["avatar_content_changed"]),
        ("filename", ["avatar_disabled"]),
        ("use_gaia_picture", ["avatar_disabled"]),
        ("is_using_default_avatar", ["avatar_disabled"]),
        ("using_gaia_avatar", ["avatar_disabled"]),
        ("invalid_flag", ["avatar_disabled"]),
    ],
)
def test_avatar_inspection_checks_bytes_and_all_selection_flags_without_writes_or_image_output(
    tmp_path: Path,
    avatar_png: str,
    mode: str,
    issues: list[str],
) -> None:
    """Avatar diagnostics report content and selection drift without disclosing image data."""

    preferences_path = _profile(tmp_path, "Default", "Personal")
    preferences = json.loads(preferences_path.read_text())
    preferences["profile"]["using_gaia_avatar"] = mode != "using_gaia_avatar"
    preferences_path.write_text(json.dumps(preferences))
    entry = {
        "name": "Personal",
        "gaia_picture_file_name": AVATAR_FILENAME,
        "use_gaia_picture": True,
        "is_using_default_avatar": False,
    }
    if mode == "filename":
        entry["gaia_picture_file_name"] = "../../secret-must-not-appear"
    elif mode in {"use_gaia_picture", "is_using_default_avatar"}:
        entry[mode] = not entry[mode]
    elif mode == "invalid_flag":
        entry["use_gaia_picture"] = "true"
    state = _state(tmp_path, {"Default": entry})
    avatar = preferences_path.parent / AVATAR_FILENAME
    if mode != "missing":
        avatar.write_bytes(base64.b64decode(avatar_png) if mode != "different" else b"secret-must-not-appear")
    before = {path: path.read_bytes() for path in (preferences_path, state, avatar) if path.exists()}
    result = inspect_browser_profiles(str(tmp_path), [{**_DECLARATION, "avatar_png": avatar_png}])
    assert result["profiles"][0]["avatar"] == {
        "file_present": mode != "missing",
        "content_matches": mode not in {"missing", "different"},
        "enabled": mode in {"matching", "missing", "different"},
    }
    assert result["drift"] == (
        [{"kind": "avatar", "directory": "Default", "id": "personal", "issues": issues}] if issues else []
    )
    assert {path: path.read_bytes() for path in before} == before
    assert avatar.exists() == (mode != "missing")
    assert avatar_png not in json.dumps(result)
    assert "secret-must-not-appear" not in json.dumps(result)


@pytest.mark.parametrize("target_exists", [True, False])
def test_avatar_symlinks_are_refused_without_reading_the_target(
    tmp_path: Path, avatar_png: str, target_exists: bool
) -> None:
    """Unsafe avatar paths fail without reading or revealing the symlink target."""

    preferences = _profile(tmp_path, "Default", "Personal")
    _state(tmp_path, {"Default": {"name": "Personal"}})
    target = tmp_path / "private-target-name"
    if target_exists:
        target.write_bytes(b"private contents")
    (preferences.parent / AVATAR_FILENAME).symlink_to(target)
    with pytest.raises(ValueError, match="Refusing symlinked browser avatar") as error:
        inspect_browser_profiles(str(tmp_path), [{**_DECLARATION, "avatar_png": avatar_png}])
    assert "private-target-name" not in str(error.value)
    assert "private contents" not in str(error.value)


def test_absent_avatar_attachment_leaves_local_avatar_uninspected(tmp_path: Path) -> None:
    """Profiles without a managed avatar retain their existing local choice."""

    preferences = _profile(tmp_path, "Default", "Personal")
    _state(tmp_path, {"Default": {"name": "Personal"}})
    (preferences.parent / AVATAR_FILENAME).symlink_to(tmp_path / "unmanaged-avatar")
    result = inspect_browser_profiles(str(tmp_path), [_DECLARATION])
    assert result["drift"] == []
    assert "avatar" not in result["profiles"][0]
    assert (preferences.parent / AVATAR_FILENAME).is_symlink()


def test_invalid_avatar_attachment_cannot_silently_disable_inspection(tmp_path: Path) -> None:
    """Malformed attachments must fail without disclosing their encoded contents."""

    with pytest.raises(ValueError, match="avatar_png") as error:
        inspect_browser_profiles(str(tmp_path), [{**_DECLARATION, "avatar_png": "secret-must-not-appear"}])
    assert "secret-must-not-appear" not in str(error.value)


def test_omitted_sync_everything_uses_the_native_enabled_default(tmp_path: Path) -> None:
    """Absence in Preferences is not evidence that the browser disabled Sync everything."""

    preferences = _profile(tmp_path, "Default", "Personal", {"bookmarks": False})
    _state(tmp_path, {"Default": {"name": "Personal"}})
    before = preferences.read_bytes()
    result = inspect_browser_profiles(str(tmp_path), [_DECLARATION])
    assert result["sync_issues"] == []
    assert result["profiles"][0]["sync"]["keep_everything_synced"] is True
    assert result["profiles"][0]["sync"]["selected_types"]["bookmarks"] is False
    assert preferences.read_bytes() == before
