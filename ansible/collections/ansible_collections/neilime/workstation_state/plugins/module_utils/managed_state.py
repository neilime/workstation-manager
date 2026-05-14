"""Helpers for building workstation managed state documents."""

from __future__ import annotations

import json


class ManagedStateContentBuilder:
    """Build serialized state markers for the workstation flows."""

    def __init__(self, project: str = "workstation-manager") -> None:
        self._project = project

    def build_system_content(
        self,
        branch: str,
        baseline: dict[str, object] | None = None,
    ) -> str:
        """Return the serialized system state payload for the selected branch."""

        if not branch:
            raise ValueError("branch must not be empty")

        payload = {
            "project": self._project,
            "branch": branch,
            "managed": True,
        }

        if baseline is not None:
            payload["baseline"] = self._normalize_system_baseline(baseline)

        return self._serialize(payload)

    def build_user_content(self, user: str) -> str:
        """Return the serialized user state payload for the selected user."""

        if not user:
            raise ValueError("user must not be empty")

        return self._serialize(
            {
                "project": self._project,
                "user": user,
                "managed": True,
            }
        )

    @staticmethod
    def _serialize(payload: dict[str, object]) -> str:
        """Serialize a managed state payload with stable formatting."""

        return json.dumps(payload, indent=2) + "\n"

    def _normalize_system_baseline(
        self,
        baseline: dict[str, object],
    ) -> dict[str, list[str]]:
        """Return the serialized cleanup baseline captured after setup."""

        if not isinstance(baseline, dict):
            raise ValueError("baseline must be a mapping")

        return {
            "manual_apt_packages": self._normalize_string_list(
                baseline.get("manual_apt_packages"),
                "baseline.manual_apt_packages",
            ),
            "flatpak_packages": self._normalize_string_list(
                baseline.get("flatpak_packages"),
                "baseline.flatpak_packages",
            ),
        }

    @staticmethod
    def _normalize_string_list(value: object, name: str) -> list[str]:
        """Return a stable sorted list of non-empty strings."""

        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError(f"{name} must be a list")

        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(f"{name} must contain only strings")

            candidate = item.strip()
            if candidate:
                normalized.append(candidate)

        return sorted(set(normalized))
