"""Unit tests for Git GPG signing helpers."""

from __future__ import annotations

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.git_gpg_signing import (
    GitGpgSigningPlanner,
)


def test_signing_fingerprint_returns_the_single_restored_key() -> None:
    """A single restored GPG key should drive Git signing configuration."""

    # Arrange
    planner = GitGpgSigningPlanner()
    restore_plans = [{"fingerprint": "0123 4567 89ab cdef ".replace(" ", "")}]

    # Act
    fingerprint = planner.signing_fingerprint(restore_plans)

    # Assert
    assert fingerprint == "0123456789ABCDEF"


def test_signing_fingerprint_rejects_missing_restored_keys() -> None:
    """Git signing cannot guess a key when nothing was restored."""

    # Arrange
    planner = GitGpgSigningPlanner()

    # Act / Assert
    with pytest.raises(ValueError, match="exactly one restored GPG key"):
        planner.signing_fingerprint([])


def test_signing_fingerprint_rejects_multiple_restored_keys() -> None:
    """Git signing should fail rather than guess between several keys."""

    # Arrange
    planner = GitGpgSigningPlanner()
    restore_plans = [
        {"fingerprint": "0123456789ABCDEF"},
        {"fingerprint": "FEDCBA9876543210"},
    ]

    # Act / Assert
    with pytest.raises(ValueError, match="exactly one restored GPG key"):
        planner.signing_fingerprint(restore_plans)


def test_signing_fingerprint_rejects_missing_fingerprint() -> None:
    """Git signing requires a concrete restored fingerprint."""

    # Arrange
    planner = GitGpgSigningPlanner()

    # Act / Assert
    with pytest.raises(ValueError, match="fingerprint must be a string"):
        planner.signing_fingerprint([{}])
