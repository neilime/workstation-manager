"""Validate the common recovery prompt without secrets or implicit approvals."""

from __future__ import annotations

import copy

import pytest
from ansible_collections.neilime.workstation_backup.plugins.module_utils.recovery import (
    recovery_decision,
    recovery_decision_id,
)


def _request() -> dict:
    return {
        "scope": "chezmoi",
        "summary": "Source changes:\n M settings\n D removed",
        "actions": {"re-add": "Capture local files.", "apply": "Apply stored files."},
        "skip": "Leave these files unchanged and skip remaining Chezmoi checks.",
        "abort_message": "Backup stopped without changing files.",
    }


def test_explicit_actions_preserve_order_and_add_shared_skip_and_abort() -> None:
    """The visible choices and accepted values must agree, without changing input data."""

    request = _request()
    original = copy.deepcopy(request)
    result = recovery_decision(request)
    assert result["choices"] == ["re-add", "apply", "skip", "abort"]
    assert result["prompt"].endswith("Choose [re-add/apply/skip/abort]")
    assert "Source changes:\n M settings\n D removed" in result["prompt"]
    assert "Recovery stays unverified" in result["prompt"]
    assert "local changes are not added to the archive" in result["prompt"]
    assert result["scope"] == "chezmoi"
    assert request == original


def test_terminal_controls_are_removed_without_losing_line_breaks() -> None:
    """Report data cannot escape its display lines with ANSI or carriage-return controls."""

    request = _request()
    request["summary"] = "File\x1b[2J\rname\n M settings"
    request["actions"]["apply"] = "Apply\x1b[0m stored files."
    result = recovery_decision(request)
    assert "\x1b" not in result["prompt"]
    assert "\r" not in result["prompt"]
    assert "\n M settings" in result["prompt"]


@pytest.mark.parametrize(
    "changes",
    [
        {"scope": "private-unknown"},
        {"scope": []},
        {"actions": {}},
        {"actions": ["apply"]},
        {"actions": {"skip": "Cannot redefine skip"}},
        {"actions": {"abort": "Cannot redefine abort"}},
        {"actions": {"private\ncommand": "Invalid name"}},
        {"actions": {"apply": ""}},
        {"summary": None},
        {"skip": ""},
        {"private_key": "private-material"},
    ],
)
def test_malformed_requests_fail_without_echoing_their_contents(changes: dict) -> None:
    """Invalid contracts must not hide required checks or copy arbitrary records into errors."""

    with pytest.raises(ValueError) as error:
        recovery_decision({**_request(), **changes})
    assert "private-" not in str(error.value)


@pytest.mark.parametrize("value", [None, "", "UPPER", "with spaces", "../other", "other\nfact"])
def test_unsafe_decision_ids_are_rejected(value: object) -> None:
    """Only stable decision identifiers can address the result map."""

    with pytest.raises(ValueError, match="Recovery decision IDs"):
        recovery_decision_id(value)
