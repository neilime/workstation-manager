"""Regression coverage for preserving browser-owned profiles during setup."""

from __future__ import annotations

import base64
import json
import struct
import zlib
from pathlib import Path

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    browser_profile_seed,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_seed import (
    seed_browser_profiles,
)


@pytest.fixture(autouse=True)
def isolate_brave_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Synthetic profile tests must not depend on the developer's running browser."""

    detector = browser_profile_seed._brave_running  # pylint: disable=protected-access
    monkeypatch.setattr(
        browser_profile_seed, "_brave_running", lambda proc_root=None: detector(proc_root) if proc_root else False
    )


def test_new_profiles_are_registered_and_seeded_privately(tmp_path: Path) -> None:
    """New profiles must be visible to Brave and receive their initial names."""

    root = tmp_path / "Brave-Browser"
    profiles = [
        {"id": "personal", "label": "Personal"},
        {"id": "work", "label": "Work", "directory": "Profile 1"},
    ]
    assert seed_browser_profiles(str(root), profiles)
    state = json.loads((root / "Local State").read_text())
    assert set(state["profile"]["info_cache"]) == {"managed-personal", "Profile 1"}
    assert state["profile"]["last_used"] == "managed-personal"
    assert state["profile"]["info_cache"]["Profile 1"]["name"] == "Work"
    preferences = root / "managed-personal" / "Preferences"
    assert json.loads(preferences.read_text())["profile"]["name"] == "Personal"
    assert preferences.stat().st_mode & 0o777 == 0o600
    assert preferences.parent.stat().st_mode & 0o777 == 0o700
    assert not seed_browser_profiles(str(root), profiles)


def test_padded_id_sets_normalized_default_name_without_mutating_declaration(tmp_path: Path) -> None:
    """An omitted label uses the trimmed identifier in both native profile records."""

    declaration = {"id": " personal "}
    assert seed_browser_profiles(str(tmp_path), [declaration])
    state = json.loads((tmp_path / "Local State").read_text())
    assert set(state["profile"]["info_cache"]) == {"managed-personal"}
    assert state["profile"]["info_cache"]["managed-personal"]["name"] == "personal"
    preferences = json.loads((tmp_path / "managed-personal" / "Preferences").read_text())
    assert preferences["profile"]["name"] == "personal"
    assert declaration == {"id": " personal "}


def test_setup_preserves_renames_pins_extensions_and_sync(tmp_path: Path) -> None:
    """Repeated setup must not reset user preferences, account state, or synced data."""

    root = tmp_path / "Brave-Browser"
    profiles = [{"id": "personal", "label": "Original"}]
    seed_browser_profiles(str(root), profiles)
    prefs_path = root / "managed-personal" / "Preferences"
    preferences = {
        "profile": {"name": "Renamed"},
        "pinned_tabs": [{"url": "https://existing.example/"}],
        "extensions": {"settings": {"example": {"state": 1}}},
        "brave": {"sync_v2": {"seed": "do-not-overwrite"}},
    }
    original_bytes = json.dumps(preferences, indent=2).encode()
    prefs_path.write_bytes(original_bytes)
    state_path = root / "Local State"
    state = json.loads(state_path.read_text())
    state["profile"]["info_cache"]["managed-personal"]["name"] = "Renamed"
    state["unrelated"] = {"setting": True}
    state_path.write_text(json.dumps(state))
    state_bytes = state_path.read_bytes()
    assert not seed_browser_profiles(str(root), profiles)
    assert prefs_path.read_bytes() == original_bytes
    assert state_path.read_bytes() == state_bytes


def test_registers_existing_native_profile_without_changing_preferences(tmp_path: Path) -> None:
    """Registration preserves native directory names and existing profile preferences."""

    profile = tmp_path / "Default"
    profile.mkdir()
    path = profile / "Preferences"
    path.write_text('{"profile":{"name":"Existing"},"pinned_tabs":[]}')
    original = path.read_bytes()
    assert seed_browser_profiles(str(tmp_path), [{"id": "personal", "directory": "Default", "label": "New"}])
    assert path.read_bytes() == original
    state = json.loads((tmp_path / "Local State").read_text())
    assert state["profile"]["info_cache"]["Default"]["name"] == "Existing"


def test_check_mode_does_not_create_files(tmp_path: Path) -> None:
    """Check mode reports pending initialization without leaving empty profiles."""

    root = tmp_path / "missing"
    assert seed_browser_profiles(str(root), [{"id": "personal"}], check_mode=True)
    assert not root.exists()
    assert not seed_browser_profiles(str(root), [])
    assert not root.exists()


def test_running_browser_blocks_changes_but_allows_noop(tmp_path: Path) -> None:
    """Even broken process lock symlinks must prevent writes to browser settings."""

    seed_browser_profiles(str(tmp_path), [{"id": "personal"}])
    (tmp_path / "SingletonLock").symlink_to("host-12345")
    assert not seed_browser_profiles(str(tmp_path), [{"id": "personal"}])
    with pytest.raises(ValueError, match="Close Brave completely"):
        seed_browser_profiles(str(tmp_path), [{"id": "work"}])
    assert not (tmp_path / "managed-work").exists()


@pytest.mark.parametrize(
    "declarations",
    [
        [{"id": "personal"}, {"id": "personal"}],
        [{"id": "personal", "directory": "Default"}, {"id": "work", "directory": "Default"}],
        [{"id": "personal"}, {"id": "../outside"}],
        [{"id": "personal", "directory": "../outside"}],
    ],
)
def test_invalid_configuration_does_not_partially_create_profiles(tmp_path: Path, declarations: list) -> None:
    """Validate every profile before writing any configuration to disk."""

    with pytest.raises(ValueError):
        seed_browser_profiles(str(tmp_path), declarations)
    assert not list(tmp_path.iterdir())


def test_invalid_json_is_never_overwritten(tmp_path: Path) -> None:
    """Corrupt existing state should fail with its original bytes untouched."""

    state = tmp_path / "Local State"
    state.write_text("incomplete browser write")
    with pytest.raises(ValueError):
        seed_browser_profiles(str(tmp_path), [{"id": "personal"}])
    assert state.read_text() == "incomplete browser write"
    assert not (tmp_path / "managed-personal").exists()


def test_symlinked_preferences_are_never_overwritten(tmp_path: Path) -> None:
    """A profile must not make setup follow a link outside its settings directory."""

    target = tmp_path / "target.json"
    target.write_text("{}")
    profile = tmp_path / "managed-personal"
    profile.mkdir()
    (profile / "Preferences").symlink_to(target)
    with pytest.raises(ValueError, match="symlinked browser settings"):
        seed_browser_profiles(str(tmp_path), [{"id": "personal"}])
    assert target.read_text() == "{}"
    assert not (tmp_path / "Local State").exists()


def test_running_process_blocks_changes_without_a_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Do not assume a missing SingletonLock means the browser is closed."""

    monkeypatch.setattr(browser_profile_seed, "_brave_running", lambda: True)
    with pytest.raises(ValueError, match="Close Brave completely"):
        seed_browser_profiles(str(tmp_path), [{"id": "personal"}])
    assert not list(tmp_path.iterdir())


def test_brave_process_detection_recognizes_native_binary(tmp_path: Path) -> None:
    """Native launchers resolve to an executable named brave in proc command lines."""

    process = tmp_path / "12345"
    process.mkdir()
    (process / "cmdline").write_bytes(b"/opt/brave.com/brave/brave\0--profile-directory=Default\0")
    assert browser_profile_seed._brave_running(tmp_path)  # pylint: disable=protected-access
    (process / "cmdline").write_bytes(b"/opt/brave.com/brave/brave --profile-directory=Profile 2\0")
    assert browser_profile_seed._brave_running(tmp_path)  # pylint: disable=protected-access
    (process / "cmdline").write_bytes(b"/usr/bin/python3\0script.py\0")
    assert not browser_profile_seed._brave_running(tmp_path)  # pylint: disable=protected-access


def test_bitwarden_item_reference_is_not_written_to_browser_settings(tmp_path: Path) -> None:
    """Profile metadata may refer to Bitwarden without attempting native sync enrollment."""

    item_id = "1659d058-b43c-4b59-8c84-cba19c437223"
    assert seed_browser_profiles(str(tmp_path), [{"id": "personal", "item_id": item_id}])
    for path in (tmp_path / "Local State", tmp_path / "managed-personal" / "Preferences"):
        assert "item_id" not in path.read_text()
        assert item_id not in path.read_text()


@pytest.mark.parametrize(
    "color, expected",
    [
        ("#1c3144", -14929596),
        ("#FFFFFF", -1),
        ("#000000", -16777216),
    ],
)
def test_new_profile_uses_native_main_color(tmp_path: Path, color: str, expected: int) -> None:
    """Brave receives one opaque main color; the full palette stays in the vault."""

    declaration = {"id": "work", "theme_colors": [color, "#ecb807", "#002C59"]}
    assert seed_browser_profiles(str(tmp_path), [declaration])
    preferences = json.loads((tmp_path / "managed-work" / "Preferences").read_text())
    assert preferences["browser"]["theme"] == {
        "user_color2": expected,
        "color_variant2": 1,
    }
    assert preferences["extensions"]["theme"] == {"id": "user_color_theme_id"}
    assert "theme_colors" not in json.dumps(preferences)
    assert not seed_browser_profiles(str(tmp_path), [declaration])


def test_declared_color_changes_only_native_theme_preferences(tmp_path: Path) -> None:
    """Restoring a color preserves the profile's data, names, light/dark choice, and Sync state."""

    declaration = {"id": "work", "theme_colors": ["#0079B3", "#E4844A"]}
    seed_browser_profiles(str(tmp_path), [{"id": "work"}, {"id": "personal"}])
    path = tmp_path / "managed-work" / "Preferences"
    preferences = {
        "profile": {"name": "Manual name"},
        "pinned_tabs": [{"url": "https://existing.example/"}],
        "brave_sync_v2": {"seed": "keep-this-synthetic-seed"},
        "sync": {"keep_everything_synced": True},
        "syncing_theme_prefs_migrated_to_non_syncing": True,
        "should_read_incoming_syncing_theme_prefs": False,
        "browser": {
            "show_home_button": True,
            "theme": {
                "user_color2": -1,
                "color_variant2": 2,
                "is_grayscale2": True,
                "color_scheme2": 2,
                "saved_local_theme": "saved-theme",
                "user_color": -1,
                "color_variant": 2,
            },
        },
        "extensions": {
            "settings": {"example": {"state": 1}},
            "theme": {
                "id": "",
                "system_theme": 1,
            },
        },
    }
    path.write_text(json.dumps(preferences))
    bookmarks = path.parent / "Bookmarks"
    bookmarks.write_text('{"bookmark_bar": "untouched"}')
    personal = tmp_path / "managed-personal" / "Preferences"
    original_personal = personal.read_bytes()
    assert seed_browser_profiles(str(tmp_path), [declaration, {"id": "personal"}])
    expected = json.loads(json.dumps(preferences))
    expected["browser"]["theme"].update(user_color2=-16746061, color_variant2=1, is_grayscale2=False)
    expected["extensions"]["theme"].update(id="user_color_theme_id", system_theme=0)
    assert json.loads(path.read_text()) == expected
    assert personal.read_bytes() == original_personal
    assert bookmarks.read_text() == '{"bookmark_bar": "untouched"}'
    assert not seed_browser_profiles(str(tmp_path), [declaration])


def test_theme_check_mode_and_running_browser_never_write(tmp_path: Path) -> None:
    """Existing colors can be previewed safely, and running Brave prevents an actual change."""

    declaration = {"id": "work", "theme_colors": ["#1C3144"]}
    seed_browser_profiles(str(tmp_path), [{"id": "work"}])
    path = tmp_path / "managed-work" / "Preferences"
    original = path.read_bytes()
    assert seed_browser_profiles(str(tmp_path), [declaration], check_mode=True)
    assert path.read_bytes() == original
    (tmp_path / "SingletonLock").symlink_to("host-12345")
    with pytest.raises(ValueError, match="Close Brave completely"):
        seed_browser_profiles(str(tmp_path), [declaration])
    assert path.read_bytes() == original


@pytest.mark.parametrize("colors", [[], "#112233", ["red"], ["#123"], [123], ["#112233", "bad"], ["#112233"] * 4])
def test_invalid_palette_prevents_all_writes(tmp_path: Path, colors: object) -> None:
    """Invalid metadata on a later profile cannot leave earlier profile changes behind."""

    with pytest.raises(ValueError, match="theme_colors"):
        seed_browser_profiles(
            str(tmp_path),
            [
                {"id": "valid", "theme_colors": ["#1C3144"]},
                {"id": "invalid", "theme_colors": colors},
            ],
        )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "preferences",
    [
        {"browser": []},
        {"browser": {"theme": []}},
        {"extensions": []},
        {"extensions": {"theme": []}},
    ],
)
def test_malformed_theme_settings_are_not_replaced(tmp_path: Path, preferences: dict) -> None:
    """Unexpected existing structures must fail before any profile is modified."""

    profile = tmp_path / "managed-work"
    profile.mkdir()
    path = profile / "Preferences"
    path.write_text(json.dumps(preferences))
    original = path.read_bytes()
    with pytest.raises(ValueError, match="Expected a JSON object"):
        seed_browser_profiles(str(tmp_path), [{"id": "work", "theme_colors": ["#1C3144"]}])
    assert path.read_bytes() == original
    assert not (tmp_path / "Local State").exists()


def test_theme_restore_requires_initialized_brave_preferences(tmp_path: Path) -> None:
    """Uninitialized theme state blocks restoration before any profile can be modified."""

    profile = tmp_path / "managed-work"
    profile.mkdir()
    path = profile / "Preferences"
    path.write_text('{"browser":{"theme":{"user_color":-1}}}')
    original = path.read_bytes()
    with pytest.raises(ValueError, match="Open Brave once"):
        seed_browser_profiles(
            str(tmp_path),
            [
                {"id": "fresh", "theme_colors": ["#0079B3"]},
                {"id": "work", "theme_colors": ["#1C3144"]},
            ],
        )
    assert path.read_bytes() == original
    assert not (tmp_path / "managed-fresh").exists()
    assert not (tmp_path / "Local State").exists()


def test_custom_extension_theme_requires_browser_reset(tmp_path: Path) -> None:
    """An enabled theme extension could otherwise silently reapply itself on startup."""

    profile = tmp_path / "managed-work"
    profile.mkdir()
    path = profile / "Preferences"
    path.write_text('{"extensions":{"theme":{"id":"abcdefghijklmnopabcdefghijklmnop"}}}')
    original = path.read_bytes()
    with pytest.raises(ValueError, match="Reset the custom theme in Brave"):
        seed_browser_profiles(str(tmp_path), [{"id": "work", "theme_colors": ["#1C3144"]}])
    assert path.read_bytes() == original
    assert not (tmp_path / "Local State").exists()


def test_native_api_default_elision_is_already_restored(tmp_path: Path) -> None:
    """Brave clears default theme fields; repeating setup must remain a no-op."""

    declaration = {"id": "work", "theme_colors": ["#1C3144"]}
    seed_browser_profiles(str(tmp_path), [declaration])
    path = tmp_path / "managed-work" / "Preferences"
    preferences = json.loads(path.read_text())
    preferences["browser"]["theme"].pop("is_grayscale2", None)
    preferences["extensions"]["theme"].pop("system_theme", None)
    path.write_text(json.dumps(preferences, indent=2))
    original = path.read_bytes()
    assert not seed_browser_profiles(str(tmp_path), [declaration])
    assert path.read_bytes() == original


@pytest.fixture(name="avatar_png")
def avatar_png_fixture() -> str:
    """A synthetic one-pixel PNG, unrelated to any browser's existing data."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(b"\0\xff\0\xff\xff")) + chunk(b"IEND", b"")
    return base64.b64encode(png).decode()


def test_avatar_restoration_preserves_profile_data_and_is_idempotent(tmp_path: Path, avatar_png: str) -> None:
    """A managed logo changes only its own native fields and leaves colors and Sync intact."""

    declaration = {"id": "work", "directory": "Default", "avatar_png": avatar_png}
    seed_browser_profiles(str(tmp_path), [{"id": "work", "directory": "Default"}])
    preferences_path = tmp_path / "Default" / "Preferences"
    preferences: dict = {
        "profile": {"name": "Manual name", "avatar_index": 56},
        "browser": {"theme": {"user_color2": -14929596}},
        "brave_sync_v2": {"seed": "synthetic-preserved-value"},
        "pinned_tabs": [{"url": "https://example.invalid/"}],
    }
    preferences_path.write_text(json.dumps(preferences))
    state_path = tmp_path / "Local State"
    state = json.loads(state_path.read_text())
    entry = state["profile"]["info_cache"]["Default"]
    entry.update(name="Manual name", avatar_icon="chrome://theme/IDR_PROFILE_AVATAR_56", gaia_id="unchanged")
    state_path.write_text(json.dumps(state))
    assert seed_browser_profiles(str(tmp_path), [declaration])
    preferences["profile"]["using_gaia_avatar"] = True
    assert json.loads(preferences_path.read_text()) == preferences
    entry.update(gaia_picture_file_name="workstation-avatar.png", use_gaia_picture=True, is_using_default_avatar=False)
    assert json.loads(state_path.read_text()) == state
    avatar = preferences_path.parent / "workstation-avatar.png"
    assert avatar.read_bytes() == base64.b64decode(avatar_png)
    assert avatar.stat().st_mode & 0o777 == 0o600
    assert not seed_browser_profiles(str(tmp_path), [declaration])
    assert not seed_browser_profiles(str(tmp_path), [{"id": "work", "directory": "Default"}])
    assert avatar.read_bytes() == base64.b64decode(avatar_png)


def test_avatar_file_drift_is_restored_without_rewriting_preferences(tmp_path: Path, avatar_png: str) -> None:
    """Replacing damaged avatar bytes preserves unrelated preference contents."""

    declaration = {"id": "work", "avatar_png": avatar_png}
    seed_browser_profiles(str(tmp_path), [declaration])
    profile = tmp_path / "managed-work"
    preferences = profile / "Preferences"
    original_preferences = preferences.read_bytes()
    avatar = profile / "workstation-avatar.png"
    avatar.write_bytes(b"changed or corrupted")
    assert seed_browser_profiles(str(tmp_path), [declaration])
    assert preferences.read_bytes() == original_preferences
    assert avatar.read_bytes() != b"changed or corrupted"
    assert not seed_browser_profiles(str(tmp_path), [declaration])


def test_avatar_check_mode_and_running_browser_never_write(tmp_path: Path, avatar_png: str) -> None:
    """Preview mode and the running-browser guard prevent all avatar writes."""

    declaration = {"id": "work", "avatar_png": avatar_png}
    assert seed_browser_profiles(str(tmp_path), [declaration], check_mode=True)
    assert not list(tmp_path.iterdir())
    (tmp_path / "SingletonLock").symlink_to("host-12345")
    with pytest.raises(ValueError, match="Close Brave completely"):
        seed_browser_profiles(str(tmp_path), [declaration])
    assert not (tmp_path / "managed-work").exists()


def test_avatar_symlink_prevents_all_profile_changes(tmp_path: Path, avatar_png: str) -> None:
    """An unsafe avatar path aborts the entire plan before writing any profile."""

    profile = tmp_path / "managed-work"
    profile.mkdir()
    target = tmp_path / "unrelated.png"
    target.write_bytes(b"unrelated file")
    (profile / "workstation-avatar.png").symlink_to(target)
    with pytest.raises(ValueError, match="symlinked browser avatar"):
        seed_browser_profiles(
            str(tmp_path),
            [
                {"id": "first", "avatar_png": avatar_png},
                {"id": "work", "avatar_png": avatar_png},
            ],
        )
    assert target.read_bytes() == b"unrelated file"
    assert not (tmp_path / "managed-first").exists()
    assert not (profile / "Preferences").exists()
    assert not (tmp_path / "Local State").exists()


def test_invalid_avatar_prevents_all_profile_changes(tmp_path: Path, avatar_png: str) -> None:
    """Validate every attachment before creating or changing any profile."""

    with pytest.raises(ValueError, match="avatar_png"):
        seed_browser_profiles(
            str(tmp_path),
            [
                {"id": "first", "avatar_png": avatar_png},
                {"id": "later", "avatar_png": "not base64"},
            ],
        )
    assert not list(tmp_path.iterdir())


def test_invalid_avatar_registry_entry_is_never_replaced(tmp_path: Path, avatar_png: str) -> None:
    """Malformed registry entries remain intact when avatar validation fails."""

    state = tmp_path / "Local State"
    state.write_text('{"profile":{"info_cache":{"Default":[]}}}')
    original = state.read_bytes()
    with pytest.raises(ValueError, match="Expected a JSON object"):
        seed_browser_profiles(str(tmp_path), [{"id": "work", "directory": "Default", "avatar_png": avatar_png}])
    assert state.read_bytes() == original
    assert not (tmp_path / "Default").exists()
