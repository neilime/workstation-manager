"""Protect per-profile preference recovery without assuming successful native Sync."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_cdp import (
    BrowserProtocolError,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_native_sync import (
    NativeSync,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_inspection import (
    inspect_browser_profiles,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_preferences import (
    bookmark_bar_mode,
    close_tabs_confirmation,
    native_profile_preferences,
    saved_bookmark_bar,
    saved_close_tabs_confirmation,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_seed import (
    seed_browser_profiles,
)

PROFILE = {"id": "fixture", "label": "Fixture", "directory": "Default", "item_id": "fixture-id"}


@pytest.mark.parametrize("enabled", [False, True])
def test_close_tabs_confirmation_is_optional_per_profile_and_preview_is_read_only(
    tmp_path: Path, enabled: bool
) -> None:
    """Restore exact choices without touching other profiles or unrelated Brave settings."""

    profiles: list[dict] = [
        {**PROFILE, "confirm_close_tabs": enabled},
        {**PROFILE, "id": "other", "directory": "Profile 2"},
    ]
    seed_browser_profiles(str(tmp_path), [PROFILE])
    path = tmp_path / "Default/Preferences"
    preferences = json.loads(path.read_text())
    preferences["brave"] = {"enable_closing_last_tab": False}
    path.write_text(json.dumps(preferences))
    before = path.read_bytes()
    assert seed_browser_profiles(str(tmp_path), profiles, check_mode=True)
    assert path.read_bytes() == before
    assert seed_browser_profiles(str(tmp_path), profiles)
    saved = json.loads(path.read_text())
    assert saved["brave"] == {"enable_closing_last_tab": False, "enable_window_closing_confirm": enabled}
    assert saved_close_tabs_confirmation(saved) is enabled
    assert saved_close_tabs_confirmation(json.loads((tmp_path / "Profile 2/Preferences").read_text())) is None
    assert not seed_browser_profiles(str(tmp_path), profiles)
    assert not inspect_browser_profiles(str(tmp_path), profiles)["drift"]
    unmanaged = [PROFILE, profiles[1]]
    assert not inspect_browser_profiles(str(tmp_path), unmanaged)["drift"]
    drift = inspect_browser_profiles(str(tmp_path), unmanaged, include_unsaved_preferences=True)["drift"]
    assert drift == [
        {
            "kind": "confirm_close_tabs",
            "directory": "Default",
            "id": "fixture",
            "configured_value": None,
            "observed_value": enabled,
        }
    ]


@pytest.mark.parametrize("value", [None, "false", 0, 1, []])
def test_close_tabs_confirmation_rejects_non_boolean_local_settings(value: object) -> None:
    """Malformed local values cannot be mistaken for disabled or omitted settings."""

    with pytest.raises(ValueError, match="confirm_close_tabs must be a boolean"):
        close_tabs_confirmation(value)
    with pytest.raises(ValueError, match="confirm_close_tabs must be a boolean"):
        saved_close_tabs_confirmation({"brave": {"enable_window_closing_confirm": value}})


def test_unset_confirmation_uses_native_default_for_drift_without_capturing_it(tmp_path: Path) -> None:
    """Default-enabled confirmation is not an explicit choice, and differs from a saved disabled choice."""

    seed_browser_profiles(str(tmp_path), [PROFILE])
    assert not inspect_browser_profiles(str(tmp_path), [PROFILE], include_unsaved_preferences=True)["drift"]
    assert not inspect_browser_profiles(str(tmp_path), [{**PROFILE, "confirm_close_tabs": True}])["drift"]
    drift = inspect_browser_profiles(str(tmp_path), [{**PROFILE, "confirm_close_tabs": False}])["drift"]
    assert drift[0]["configured_value"] is False and drift[0]["observed_value"] is True
    assert native_profile_preferences({"confirm_close_tabs": False}) == {"brave.enable_window_closing_confirm": False}


@pytest.mark.parametrize("mode", ["always", "new_tab", "never"])
def test_seed_preserves_each_profiles_visibility_and_unrelated_data(tmp_path: Path, mode: str) -> None:
    """Restoring one profile's choice is idempotent and does not force it onto other profiles."""

    path = tmp_path / "Default/Preferences"
    path.parent.mkdir()
    path.write_text(json.dumps({"pinned_tabs": [{"url": "https://example.invalid"}]}))
    other = {**PROFILE, "id": "other", "directory": "Profile 2"}
    profiles = [{**PROFILE, "bookmark_bar": mode}, other]
    assert seed_browser_profiles(str(tmp_path), profiles, check_mode=True)
    assert "bookmark_bar" not in json.loads(path.read_text())
    assert not (tmp_path / "Profile 2").exists()
    assert seed_browser_profiles(str(tmp_path), profiles)
    saved = json.loads(path.read_text())
    assert saved_bookmark_bar(saved) == mode
    assert saved["bookmark_bar"]["show_on_all_tabs"] is (mode == "always")
    assert saved["brave"]["always_show_bookmark_bar_on_ntp"] is (mode == "new_tab")
    assert saved["pinned_tabs"] == [{"url": "https://example.invalid"}]
    assert saved_bookmark_bar(json.loads((tmp_path / "Profile 2/Preferences").read_text())) is None
    assert not seed_browser_profiles(str(tmp_path), profiles)
    assert not inspect_browser_profiles(str(tmp_path), profiles)["drift"]


@pytest.mark.parametrize(
    "preferences,expected",
    [
        ({}, None),
        ({"bookmark_bar": {"show_on_all_tabs": True}}, "always"),
        ({"bookmark_bar": {"show_on_all_tabs": False}}, "new_tab"),
        ({"brave": {"always_show_bookmark_bar_on_ntp": False}}, "never"),
        ({"bookmark_bar": {"visibility_state": 2}}, "never"),
    ],
)
def test_reads_native_visibility_without_treating_an_unset_choice_as_saved(preferences: dict, expected: str) -> None:
    """An absent preference must not create a managed setting during backup."""

    assert saved_bookmark_bar(preferences) == expected


@pytest.mark.parametrize("value", [None, True, [], "Always", "unknown-private-value"])
def test_invalid_modes_are_rejected_without_disclosing_input(value: object) -> None:
    """Only documented metadata values can control native preferences."""

    with pytest.raises(ValueError, match="must be always, new_tab, or never"):
        bookmark_bar_mode(value)


@pytest.mark.parametrize("value", [True, "0", -1, 3])
def test_malformed_native_visibility_is_not_silently_saved(value: object) -> None:
    """Unexpected browser state blocks a misleading backup."""

    with pytest.raises(ValueError, match="visibility state"):
        saved_bookmark_bar({"bookmark_bar": {"visibility_state": value}})


def test_backup_discovers_unsaved_choice_without_turning_setup_into_a_vault_write(tmp_path: Path) -> None:
    """An explicit local choice is offered for save while setup leaves undeclared choices alone."""

    seed_browser_profiles(str(tmp_path), [{**PROFILE, "bookmark_bar": "always"}])
    assert not inspect_browser_profiles(str(tmp_path), [PROFILE])["drift"]
    result = inspect_browser_profiles(str(tmp_path), [PROFILE], include_unsaved_preferences=True)
    assert result["drift"] == [
        {
            "kind": "bookmark_bar",
            "directory": "Default",
            "id": "fixture",
            "configured_value": None,
            "observed_value": "always",
        }
    ]
    result = inspect_browser_profiles(str(tmp_path), [{**PROFILE, "bookmark_bar": "never"}])
    assert result["drift"][0]["observed_value"] == "always"
    assert result["drift"][0]["configured_value"] == "never"


@pytest.mark.parametrize("failure", [None, "unsupported", "mismatch", "pending", "changed-again"])
def test_native_restore_requires_readback_and_sync_evidence(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    """Native writes cannot be reported as recovered until upload and a second read agree."""

    pipe = Mock()
    pipe.evaluate.side_effect = [
        True,
        {"issued": True, "value": True},
        {"issued": True, "value": {"available": True, "decryptionFailed": False}},
    ]
    native = NativeSync(pipe, "/fixture/Default")
    good = {"supported": True, "matches": True, "changed": False}
    pipe.evaluate.side_effect = [
        {
            "issued": True,
            "value": (
                None if failure == "unsupported" else {**good, "matches": failure != "mismatch", "changed": True}
            ),
        },
        {"issued": True, "value": {**good, "matches": failure != "changed-again"}},
    ]
    wait = Mock(return_value=failure != "pending")
    monkeypatch.setattr(native, "wait", wait)
    if failure:
        with pytest.raises(BrowserProtocolError, match="profile preferences"):
            native.profile_preferences({"bookmark_bar": "always"}, restore=True)
    else:
        native.profile_preferences({"bookmark_bar": "always"}, restore=True)
        wait.assert_called_once()
        assert pipe.evaluate.call_count == 5


def test_native_backup_verifies_without_changing_preferences(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backup cannot silently restore a different saved choice onto the local browser."""

    pipe = Mock()
    pipe.evaluate.side_effect = [
        True,
        {"issued": True, "value": True},
        {"issued": True, "value": {"available": True, "decryptionFailed": False}},
    ]
    native = NativeSync(pipe, "/fixture/Default")
    pipe.evaluate.side_effect = [{"issued": True, "value": {"supported": True, "matches": False, "changed": False}}]
    wait = Mock()
    monkeypatch.setattr(native, "wait", wait)
    with pytest.raises(BrowserProtocolError, match="differ from Bitwarden"):
        native.profile_preferences({"bookmark_bar": "always"}, restore=False)
    wait.assert_not_called()
