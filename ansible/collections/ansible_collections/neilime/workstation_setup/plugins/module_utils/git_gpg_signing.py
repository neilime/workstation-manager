"""Helpers for wiring restored GPG keys into Git signing settings."""

from __future__ import annotations


# pylint: disable=too-few-public-methods
class GitGpgSigningPlanner:
    """Select the Git signing key from restored GPG key plans."""

    def signing_fingerprint(self, restore_plans: object) -> str:
        """Return the single restored fingerprint to use for Git signing."""

        plans = self._restore_plans(restore_plans)
        if len(plans) != 1:
            raise ValueError(
                "Git signing integration requires exactly one restored GPG key"
            )

        return self._fingerprint(plans[0].get("fingerprint"))

    def _restore_plans(self, value: object) -> list[dict[str, object]]:
        """Return normalized restored-key plans."""

        if not isinstance(value, list):
            raise ValueError("restored GPG key plans must be a list")

        normalized_plans: list[dict[str, object]] = []
        for index, plan in enumerate(value):
            if not isinstance(plan, dict):
                raise ValueError(f"restored GPG key plan {index} must be a mapping")
            normalized_plans.append(plan)

        return normalized_plans

    def _fingerprint(self, value: object) -> str:
        """Return a normalized Git-signing fingerprint."""

        if not isinstance(value, str):
            raise ValueError("restored GPG key fingerprint must be a string")

        fingerprint = value.strip().upper()
        if not fingerprint:
            raise ValueError("restored GPG key fingerprint must not be empty")

        return fingerprint
