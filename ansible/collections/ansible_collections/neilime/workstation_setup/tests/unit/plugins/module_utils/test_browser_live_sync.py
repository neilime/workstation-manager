"""Live browser recovery requires machine evidence and preserves explicit directions."""

from __future__ import annotations

import copy
import json
from contextlib import nullcontext
from unittest.mock import MagicMock, Mock

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    browser_live_sync as live,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_native_sync import (
    recovery_words,
)

# Deliberately non-BIP39 synthetic phrases: no real recovery chain exists.
LOCAL = " ".join(["syntheticlocal"] * 24)
REMOTE = " ".join(["syntheticremote"] * 24)
PROFILE = {"id": "fixture", "directory": "Default", "label": "Fixture", "item_id": "fixture-id"}


@pytest.fixture(name="fixture")
def live_fixture(monkeypatch: pytest.MonkeyPatch) -> tuple[Mock, MagicMock, Mock, Mock]:
    """Isolate browser and vault I/O while exercising production reconciliation decisions."""

    vault = Mock()
    item = {"id": "fixture-id", "notes": REMOTE, "name": "Fixture", "fields": [{"name": "unrelated", "value": "keep"}]}
    vault.selected_item.side_effect = lambda _profile: copy.deepcopy(item)
    native = Mock()
    native.code.return_value = REMOTE
    native.wait.return_value = True
    pipe = MagicMock()
    monkeypatch.setattr(live, "BrowserPipe", pipe)
    monkeypatch.setattr(live, "NativeSync", Mock(return_value=native))
    lifecycle = Mock(return_value=nullcontext(("/usr/bin/brave-browser", {"WAYLAND_DISPLAY": "wayland-fixture"})))
    monkeypatch.setattr(live, "closed_browser", lifecycle)
    inspection = Mock(
        return_value={
            "drift": [],
            "sync_issues": [],
            "profiles": [
                {
                    **PROFILE,
                    "sync": {
                        "seed_present": True,
                        "requested": True,
                        "has_setup_completed": True,
                        "managed": False,
                        "keep_everything_synced": True,
                    },
                }
            ],
        }
    )
    monkeypatch.setattr(live, "inspect_browser_profiles", inspection)
    return vault, pipe, native, lifecycle


def test_sync_requires_fresh_machine_evidence_and_matching_codes(fixture: tuple) -> None:
    """A successful operation checks both sides again after waiting, without returning either secret."""

    vault, pipe, native, lifecycle = fixture
    result = live.sync_browser_recovery("/fixture", [PROFILE], "sync", vault)
    assert result["verified"] is True
    assert native.code.call_count == 2
    native.wait.assert_called_once()
    native.restore.assert_not_called()
    lifecycle.assert_called_once_with("/fixture")
    pipe.return_value.__exit__.assert_called_once()
    assert LOCAL not in repr(result) and REMOTE not in repr(result)
    assert "--restore-last-session" in pipe.call_args.args[0]
    assert not any("remote-debugging-port" in argument for argument in pipe.call_args.args[0])


@pytest.mark.parametrize("status", ["mismatch", "pending"])
def test_detected_drift_returns_actions_without_claiming_verification(fixture: tuple, status: str) -> None:
    """A choice to sync cannot count as confirmation while either recovery check fails."""

    vault, _pipe, native, _lifecycle = fixture
    native.code.return_value = LOCAL if status == "mismatch" else REMOTE
    native.wait.return_value = status != "pending"
    result = live.sync_browser_recovery("/fixture", [PROFILE], "sync", vault)
    assert result["verified"] is False
    assert set(result["actions"]) == ({"retry", "save", "restore"} if status == "mismatch" else {"retry"})
    assert all(call.args == ("sync",) for call in vault.run.call_args_list)
    native.restore.assert_not_called()
    assert REMOTE not in repr(result) and LOCAL not in repr(result)


def test_restore_uses_stored_chain_and_verifies_the_result(fixture: tuple) -> None:
    """Only an explicit restore can switch an existing profile to the vault's chain."""

    vault, _pipe, native, _lifecycle = fixture
    native.code.side_effect = [LOCAL, REMOTE]
    result = live.sync_browser_recovery("/fixture", [PROFILE], "restore", vault)
    assert result["verified"] is True
    native.restore.assert_called_once_with(REMOTE, reset=True)
    assert all(call.args == ("sync",) for call in vault.run.call_args_list)


def test_save_replaces_only_notes_and_verifies_remote_readback(fixture: tuple) -> None:
    """Saving the local chain retains unrelated fields and requires a matching vault readback."""

    vault, _pipe, native, _lifecycle = fixture
    native.code.return_value = LOCAL
    before = vault.selected_item(PROFILE)
    after = {**before, "notes": LOCAL}
    vault.selected_item.side_effect = [before, before, after, after]
    result = live.sync_browser_recovery("/fixture", [PROFILE], "save", vault)
    assert result["verified"] is True
    payload = vault.run.call_args_list[1].kwargs["data"]
    assert json.loads(payload) == after
    native.restore.assert_not_called()


@pytest.mark.parametrize("failure", ["changed-note", "pending", "changed-after-sync"])
def test_failed_approved_changes_stop_instead_of_returning_verified(fixture: tuple, failure: str) -> None:
    """Post-write verification failures are fatal and always close the automation browser."""

    vault, pipe, native, _lifecycle = fixture
    native.code.return_value = LOCAL
    before = vault.selected_item(PROFILE)
    after = {**before, "notes": LOCAL}
    vault.selected_item.side_effect = [before, before, before if failure == "changed-note" else after, after]
    native.wait.return_value = failure != "pending"
    if failure == "changed-after-sync":
        native.code.side_effect = [LOCAL, REMOTE]
    with pytest.raises(ValueError, match="verification failed|did not finish|changed during"):
        live.sync_browser_recovery("/fixture", [PROFILE], "save", vault)
    pipe.return_value.__exit__.assert_called_once()


def test_preview_does_not_launch_brave_or_access_the_vault(fixture: tuple) -> None:
    """A dry run never starts native Sync, stores a code, or certifies recovery."""

    vault, pipe, native, lifecycle = fixture
    result = live.sync_browser_recovery("/fixture", [PROFILE], "restore", vault, check_mode=True)
    assert result["verified"] is False and result["changed"] is False
    pipe.assert_not_called()
    native.code.assert_not_called()
    lifecycle.assert_not_called()
    vault.run.assert_not_called()


def test_missing_desktop_stops_before_launching_brave(fixture: tuple) -> None:
    """A fresh profile still needs a desktop; missing access must not look like a pipe crash."""
    vault, pipe, native, lifecycle = fixture
    lifecycle.return_value = nullcontext(("/usr/bin/brave-browser", {}))
    with pytest.raises(ValueError, match="desktop session is unavailable"):
        live.sync_browser_recovery("/fixture", [PROFILE], "restore", vault)
    pipe.assert_not_called()
    native.restore.assert_not_called()


@pytest.mark.parametrize(
    "value",
    [
        None,
        "secret text",
        "word " * 26,
        "1 word " * 12,
        "prefix " + ("word " * 24) + "suffix",
    ],
)
def test_malformed_recovery_notes_fail_without_rendering_input(value: object) -> None:
    """An invalid secure note never escapes through a validation exception."""

    with pytest.raises(ValueError) as error:
        recovery_words(value)
    assert str(error.value) == "The browser recovery note must contain exactly 24 recovery words"


def test_recovery_words_normalize_case_and_trailing_punctuation() -> None:
    """Copied formatting differences should not block a valid stored recovery code."""

    mixed = " ".join(["Word,"] * 23 + ["WORD."])
    assert recovery_words(mixed) == " ".join(["word"] * 24)


def test_recovery_words_accept_numbered_export_format() -> None:
    """A numbered list copied from the browser or vault should normalize to plain words."""

    numbered = "\n".join(f"{index}. Word" for index in range(1, 25))
    assert recovery_words(numbered) == " ".join(["word"] * 24)


def test_recovery_words_accept_numbered_export_with_surrounding_note_text() -> None:
    """A numbered recovery block can be embedded in other note text safely."""

    numbered = "Brave sync code\n\n" + "\n".join(f"{index}. Word" for index in range(1, 25)) + "\n\nKeep private"
    assert recovery_words(numbered) == " ".join(["word"] * 24)


def test_recovery_words_accept_phrase_inside_note_text() -> None:
    """A valid recovery phrase can be embedded in surrounding note text without breaking parsing."""

    note = "Profile recovery words:\n" + " ".join(["Word"] * 24) + "\nKeep private."
    assert recovery_words(note) == " ".join(["word"] * 24)


def test_invalid_note_reports_save_instead_of_failing_sync(fixture: tuple) -> None:
    """An unreadable Bitwarden note should stay recoverable during sync verification."""

    vault, _pipe, native, _lifecycle = fixture
    before = vault.selected_item(PROFILE)
    vault.selected_item.side_effect = lambda _profile: {**copy.deepcopy(before), "notes": "Brave Sync\nnot copied yet"}
    result = live.sync_browser_recovery("/fixture", [PROFILE], "sync", vault)
    assert result["verified"] is False
    assert result["actions"] == {
        "retry": "Re-run Sync and verify recovery after you reconcile Brave or Bitwarden manually.",
        "save": "Save the current Brave recovery codes to their Bitwarden notes, then verify Sync.",
    }
    native.restore.assert_not_called()


def test_invalid_note_can_be_replaced_by_save(fixture: tuple) -> None:
    """A save action should overwrite an unreadable note with the current Brave code."""

    vault, _pipe, native, _lifecycle = fixture
    before = vault.selected_item(PROFILE)
    after = {**before, "notes": LOCAL}
    native.code.return_value = LOCAL
    vault.selected_item.side_effect = [
        {**before, "notes": "Brave Sync\nnot copied yet"},
        {**before, "notes": "Brave Sync\nnot copied yet"},
        after,
        after,
    ]
    result = live.sync_browser_recovery("/fixture", [PROFILE], "save", vault)
    assert result["verified"] is True
    payload = vault.run.call_args_list[1].kwargs["data"]
    assert json.loads(payload) == after


def test_sync_everything_drift_is_repaired_before_reporting_failure(
    fixture: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Sync cycle that clears Sync everything should be repaired inside the same closed-browser window."""

    vault, _pipe, _native, _lifecycle = fixture
    clean = live.inspect_browser_profiles("/fixture", [PROFILE])
    changed = {
        **clean,
        "sync_issues": [{"directory": "Default", "issues": ["sync_everything_not_enabled"]}],
        "profiles": [
            {**clean["profiles"][0], "sync": {**clean["profiles"][0]["sync"], "keep_everything_synced": False}}
        ],
    }
    monkeypatch.setattr(live, "inspect_browser_profiles", Mock(side_effect=[clean, clean, changed, clean]))
    repair = Mock(return_value=True)
    monkeypatch.setattr(live, "sync_browser_profiles", repair)
    result = live.sync_browser_recovery("/fixture", [PROFILE], "sync", vault)
    assert result["verified"] is True
    repair.assert_called_once_with("/fixture", [PROFILE], "restore", vault)


def test_restore_capable_metadata_drift_is_repaired_before_reporting_failure(
    fixture: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A post-sync rename drift should be restored automatically instead of aborting immediately."""

    vault, _pipe, _native, _lifecycle = fixture
    clean = live.inspect_browser_profiles("/fixture", [PROFILE])
    changed = {**clean, "drift": [{"kind": "renamed", "id": "fixture", "directory": "Default"}]}
    monkeypatch.setattr(live, "inspect_browser_profiles", Mock(side_effect=[clean, clean, changed, clean]))
    repair = Mock(return_value=True)
    monkeypatch.setattr(live, "sync_browser_profiles", repair)
    result = live.sync_browser_recovery("/fixture", [PROFILE], "sync", vault)
    assert result["verified"] is True
    repair.assert_called_once_with("/fixture", [PROFILE], "restore", vault)


def test_rotating_pairing_word_in_note_is_ignored(fixture: tuple) -> None:
    """A copied 25-word pairing code should normalize to its stable first 24 words."""

    vault, _pipe, native, _lifecycle = fixture
    before = vault.selected_item(PROFILE)
    vault.selected_item.side_effect = lambda _profile: {**copy.deepcopy(before), "notes": REMOTE.title() + " SUFFIX."}
    result = live.sync_browser_recovery("/fixture", [PROFILE], "sync", vault)
    assert result["verified"] is True
    assert native.code.call_count == 2


def test_optional_profile_fields_use_validated_inspection_defaults(fixture: tuple) -> None:
    """The public profile schema permits labels and directories to be defaulted."""

    vault, _pipe, _native, _lifecycle = fixture
    declaration = {"id": " fixture ", "item_id": PROFILE["item_id"]}
    assert live.sync_browser_recovery("/fixture", [declaration], "sync", vault)["verified"]
    assert vault.selected_item.call_args.args[0] == PROFILE


def test_native_sync_cannot_hide_new_metadata_drift(fixture: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """Downloading browser settings must not invalidate the earlier metadata check unnoticed."""

    vault, pipe, _native, _lifecycle = fixture
    clean = live.inspect_browser_profiles("/fixture", [PROFILE])
    changed = {**clean, "drift": [{"kind": "undeclared", "directory": "Profile 9", "id": None}]}
    monkeypatch.setattr(live, "inspect_browser_profiles", Mock(side_effect=[clean, clean, changed, changed]))
    monkeypatch.setattr(live, "sync_browser_profiles", Mock(return_value=False))
    with pytest.raises(ValueError, match="new drift"):
        live.sync_browser_recovery("/fixture", [PROFILE], "sync", vault)
    pipe.return_value.__exit__.assert_called_once()


def test_repeated_live_issues_are_grouped_into_one_short_instruction() -> None:
    """Six affected profiles must not repeat the same diagnostic paragraph six times."""

    profiles = [{**PROFILE, "id": f"profile-{number}", "directory": f"Profile {number}"} for number in range(6)]
    result = live.live_sync_report(profiles, [{**profile, "status": "code_mismatch"} for profile in profiles])
    assert result["summary"].count("different recovery codes") == 1
    assert all(f"(Profile {number})" in result["summary"] for number in range(6))
    assert all(len(line) <= 88 for line in result["summary"].splitlines())
    assert set(result["actions"]) == {"retry", "save", "restore"}


def test_restore_joins_new_profile_without_writing_recovery_words(
    fixture: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setup can enroll a new profile in its saved chain and verify fresh Sync."""

    vault, _pipe, native, _lifecycle = fixture
    inspection = live.inspect_browser_profiles("/fixture", [PROFILE])
    inspection["profiles"][0]["sync"].update({"seed_present": False, "requested": False, "has_setup_completed": False})
    monkeypatch.setattr(live, "inspect_browser_profiles", Mock(return_value=inspection))

    assert live.sync_browser_recovery("/fixture", [PROFILE], "restore", vault)["verified"]
    native.restore.assert_called_once_with(REMOTE, reset=False)
    native.wait.assert_called_once()
    assert all(call.args == ("sync",) for call in vault.run.call_args_list)
    assert native.code.call_count == 1
