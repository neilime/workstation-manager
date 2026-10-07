"""Readable browser recovery reports without unrelated advice or sensitive data."""

from __future__ import annotations

import copy
from collections.abc import Callable

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_reporting import (
    browser_recovery_inspection,
    browser_recovery_report,
    browser_sync_report,
)


def _inspection() -> dict:
    return {
        "profiles": [{"directory": "Default", "id": "personal", "label": "Personal"}],
        "drift": [],
        "sync_issues": [],
    }


def test_repeated_sync_and_missing_logos_become_two_action_groups() -> None:
    """A six-profile report must identify affected profiles without twelve raw diagnostics."""

    inspection = _inspection()
    inspection["profiles"] = [
        {"directory": f"Profile {number}", "id": f"profile-{number}", "label": f"Workspace {number}"}
        for number in range(6)
    ]
    inspection["sync_issues"] = [
        {"directory": profile["directory"], "issues": ["sync_everything_not_enabled"]}
        for profile in inspection["profiles"]
    ]
    inspection["drift"] = [
        {"kind": "avatar", "directory": profile["directory"], "issues": ["missing_avatar_file", "avatar_disabled"]}
        for profile in inspection["profiles"][:5]
    ]
    report = browser_recovery_report(inspection)
    assert report.startswith("Fix these 2 browser recovery issues:")
    assert report.count("Enable Sync everything.") == 1
    assert report.count("Restore missing profile logos.") == 1
    assert "Select the stored profile logos." not in report
    assert "restore" in report
    assert "brave://settings/braveSync" not in report
    assert "After changing Sync settings" not in report
    sync, avatars = report.split("2. Restore missing profile logos.")
    for number in range(6):
        assert f"Workspace {number}" in sync
        assert (f"Workspace {number}" in avatars) == (number < 5)
    assert all(len(line) <= 88 for line in report.splitlines())
    for unrelated in (
        "theme_colors",
        "recovery words",
        "profile_drift",
        "avatar_disabled",
        "sync_everything_not_enabled",
    ):
        assert unrelated not in report


@pytest.mark.parametrize(
    "record,advice,detail",
    [
        ({"kind": "undeclared", "observed_label": "Local"}, "Add local profiles to Bitwarden.", "Personal (Default)"),
        (
            {"kind": "missing", "directory": "Profile 2", "id": "work"},
            "Restore missing local profiles.",
            "work (Profile 2)",
        ),
        (
            {"kind": "renamed", "configured_label": "Work", "observed_label": "Office"},
            "Match profile names",
            'named "Office", expected "Work"',
        ),
        (
            {"kind": "theme_color", "configured_color": "#123456", "observed_color": "#FFFFFF"},
            "Reconcile profile colors.",
            "color #FFFFFF, expected #123456",
        ),
        (
            {"kind": "theme_color", "configured_color": "#123456", "observed_color": None},
            "Reconcile profile colors.",
            "color unset, expected #123456",
        ),
        (
            {"kind": "avatar", "issues": ["avatar_content_changed", "avatar_disabled"]},
            "Reconcile changed profile logos.",
            "save",
        ),
        ({"kind": "avatar", "issues": ["avatar_disabled"]}, "Select the stored profile logos.", "restore"),
        ({"kind": "unregistered"}, "Register profiles in Brave's profile picker.", "register these existing profiles"),
        ({"kind": "missing_preferences"}, "Restore missing profile settings.", "recreate saved profile settings"),
    ],
)
def test_profile_drift_has_specific_next_steps(record: dict, advice: str, detail: str) -> None:
    """Every supported inspection category has useful instructions and safe identifying details."""

    inspection = _inspection()
    inspection["drift"] = [{"directory": "Default", **record}]
    report = browser_recovery_report(inspection)
    assert report.startswith("Fix this browser recovery issue:")
    assert advice in report
    assert detail in report.replace("\n   ", " ")
    assert "Enable Sync everything." not in report


@pytest.mark.parametrize(
    "issue,advice",
    [
        ("sync_everything_not_enabled", "Enable Sync everything."),
        ("sync_disabled_by_policy", "Resolve the policy blocking Sync."),
    ],
)
def test_sync_diagnostics_have_specific_next_steps(issue: str, advice: str) -> None:
    """A Sync problem must point to its own remedy without unrelated appearance advice."""

    inspection = _inspection()
    inspection["sync_issues"] = [{"directory": "Default", "issues": [issue]}]
    report = browser_recovery_report(inspection)
    assert advice in report
    assert "Personal (Default)" in report
    if issue == "sync_everything_not_enabled":
        assert "Choose restore" in report
        assert "close Brave to save them" not in report
    else:
        assert "close Brave to save them" in report
    assert "profile logos" not in report
    assert "profile colors" not in report


@pytest.mark.parametrize("with_profile", [True, False])
def test_clean_inspection_does_not_claim_live_sync_is_verified(with_profile: bool) -> None:
    """Clean saved settings still require the later live confirmation."""

    inspection = _inspection()
    if not with_profile:
        inspection["profiles"] = []
    assert browser_recovery_report(inspection) == (
        "Saved browser settings match for 1 profile. Live Sync is not verified."
        if with_profile
        else "No browser profiles to check."
    )


@pytest.mark.parametrize("reporter", [browser_recovery_report, browser_sync_report])
def test_report_ignores_sensitive_fields_and_preserves_its_input(reporter: Callable[[dict], str]) -> None:
    """Only allowlisted metadata reaches the report, with terminal controls removed."""

    inspection = _inspection()
    inspection["profiles"][0].update(
        label="Personal\n\x1b[0m", notes="private-note", avatar_png="private-image", seed="private-seed"
    )
    inspection["drift"] = [
        {"kind": "avatar", "directory": "Default", "issues": ["avatar_disabled"], "notes": "private-drift"}
    ]
    original = copy.deepcopy(inspection)
    report = reporter(inspection)
    assert "Personal  [0m (Default)" in report
    assert "\x1b" not in report
    assert "private-" not in report
    assert inspection == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("profiles", None),
        ("drift", ["raw private-drift"]),
        ("drift", [{"kind": "private-unknown", "directory": "Default"}]),
        ("drift", [{"kind": "avatar", "directory": "Default", "issues": []}]),
        ("drift", [{"kind": "avatar", "directory": "Default", "issues": ["private-unknown"]}]),
        ("sync_issues", [{"directory": "Default", "issues": ["private-unknown"]}]),
        ("sync_issues", [{"directory": "Default", "issues": "private-unknown"}]),
    ],
)
def test_unknown_or_malformed_diagnostics_never_look_successful(field: str, value: object) -> None:
    """Fail closed without copying unknown diagnostic content into an exception."""

    inspection = _inspection()
    inspection[field] = value
    with pytest.raises(ValueError) as error:
        browser_recovery_report(inspection)
    assert "private-" not in str(error.value)


def test_undeclared_profiles_keep_manual_sync_instructions() -> None:
    """An automatic restore must not be advertised for profiles outside recovery management."""

    inspection = _inspection()
    inspection["profiles"][0]["id"] = None
    inspection["sync_issues"] = [{"directory": "Default", "issues": ["sync_everything_not_enabled"]}]
    report = browser_recovery_report(inspection)
    assert "brave://settings/braveSync" in report
    assert "choose restore" not in report


def test_automatic_sync_lists_each_profile_with_readable_wrapping() -> None:
    """The machine action names every inspected profile even when labels are long or duplicated."""

    inspection = _inspection()
    inspection["profiles"] = [
        {"directory": "Default", "label": "Personal", "id": "personal"},
        {"directory": "Profile 2", "label": "Personal", "id": "work"},
        {"directory": "Profile 6", "label": "Long label " * 12, "id": "long"},
    ]
    report = browser_sync_report(inspection)
    assert "  - Personal (Default)" in report
    assert "  - Personal (Profile 2)" in report
    assert "(Profile 6)" in report
    assert len([line for line in report.splitlines() if line.startswith("  - ")]) == 3
    assert all(len(line) <= 88 for line in report.splitlines())
    assert browser_sync_report({"profiles": []}) == "No browser profiles to check."


def test_live_sync_prompt_offers_machine_work_without_manual_checks() -> None:
    """Users select an operation; they do not act as the Sync verification mechanism."""

    report = browser_sync_report(_inspection())
    assert "automatically" in report
    assert "close safely" in report
    assert "reopen" in report
    assert "brave://" not in report
    assert "manual" not in report
    assert "first 24" not in report


def test_chain_enrollment_is_deferred_to_native_actions_without_manual_instructions() -> None:
    """Missing pairing never sends users back to a manual page-by-page recovery flow."""

    inspection = _inspection()
    inspection["sync_issues"] = [
        {"directory": "Default", "issues": ["missing_sync_seed", "sync_not_requested", "sync_setup_incomplete"]}
    ]
    sync_issues = browser_recovery_inspection(inspection)["sync_issues"]
    assert isinstance(sync_issues, list) and not sync_issues
    assert "Live Sync is not verified" in browser_recovery_report(inspection)
    inspection["sync_issues"][0]["issues"].append("sync_disabled_by_policy")
    assert browser_recovery_inspection(inspection)["sync_issues"][0]["issues"] == ["sync_disabled_by_policy"]
