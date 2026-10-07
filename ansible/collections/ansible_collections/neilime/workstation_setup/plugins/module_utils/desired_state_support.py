"""Support classes for desired state normalization."""

from __future__ import annotations

import re
from copy import deepcopy


# pylint: disable=too-few-public-methods
class DesiredStateValueResolver:
    """Validate and clone schema values used by section normalizers."""

    @staticmethod
    def release_version(value: object, name: str) -> str:
        """Require an explicit stable release from the merged configuration."""

        if not isinstance(value, str) or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value) is None:
            raise ValueError(f"{name} must be a stable release number supplied by configuration")
        return value

    @staticmethod
    def bool_value(value: object, default: bool) -> bool:
        """Return a boolean value or the provided default."""

        if value is None:
            return default
        if isinstance(value, bool):
            return value
        raise ValueError("boolean value expected")

    @staticmethod
    def first_non_empty_string(*values: object) -> str:
        """Return the first non-empty string from the provided values."""

        for value in values:
            if value is None:
                continue
            if not isinstance(value, str):
                raise ValueError("string value expected")
            if value:
                return value
        raise ValueError("string value expected")

    @staticmethod
    def list_value(value: object, name: str) -> list[object]:
        """Return a cloned list value or fail with a clear schema error."""

        if value is None:
            return []
        if isinstance(value, list):
            return deepcopy(value)
        raise ValueError(f"{name} must be a list")

    @staticmethod
    def mapping(value: object, name: str, *, allowed_keys: set[str] | None = None) -> dict[str, object]:
        """Return a cloned mapping value or fail with a clear schema error."""

        if value is None:
            return {}
        if isinstance(value, dict):
            if allowed_keys is not None and value.keys() - allowed_keys:
                raise ValueError(
                    f"{name} contains unsupported fields; allowed fields: {', '.join(sorted(allowed_keys))}"
                )
            return deepcopy(value)
        raise ValueError(f"{name} must be a mapping")

    @staticmethod
    def value_or_default(value: object, default: object) -> object:
        """Select an explicit value or its default before type validation and cloning."""

        return default if value is None else value

    @classmethod
    def sysctl_settings(
        cls,
        settings: object,
        default_settings: object,
        name: str,
    ) -> dict[str, object]:
        """Return normalized sysctl settings for a schema section."""

        declared_settings = cls.mapping(settings, name)
        declared_defaults = cls.mapping(default_settings, f"{name}.defaults")

        return {
            "sysctl": cls.mapping(
                cls.value_or_default(
                    declared_settings.get("sysctl"),
                    declared_defaults.get("sysctl"),
                ),
                f"{name}.sysctl",
            )
        }

    @staticmethod
    def int_value(value: object, default: int) -> int:
        """Return a non-negative integer value or the provided default."""

        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("non-negative integer value expected")
        return value


# pylint: disable=too-few-public-methods
class DesiredStateDefaultsSectionNormalizer:
    """Shared scaffolding for section normalizers that depend on defaults."""

    def __init__(self, resolver: DesiredStateValueResolver) -> None:
        self._resolver = resolver


class DesiredStateDefaultsFactory:
    """Build version-independent defaults for a selected state slug."""

    def __init__(self, state_slug: str) -> None:
        self._state_slug = state_slug

    def build(self) -> dict[str, object]:
        """Return optional schema defaults without dependency release pins."""

        return {
            "system": {
                "state_dir": f"/etc/{self._state_slug}",
                "locale": "en_US.UTF-8",
                "timezone": "Europe/Paris",
                "packages": {
                    "prerequisites": ["locales", "tzdata"],
                    "apt": [],
                    "cache_valid_time": 86400,
                },
                "settings": {"sysctl": {}},
            },
            "desktop": {
                "flatpak": {
                    "remote": "flathub",
                    "packages": [],
                },
                "browser": "brave",
                "gnome": {
                    "favorites": None,
                },
            },
            "development": {
                "github": {"extensions": {}},
                "packages": [],
                "editor_packages": [],
                "mise": {
                    "tools": {},
                },
                "settings": {"sysctl": {"fs.inotify.max_user_watches": "524288"}},
            },
            "home_environment": {
                "chezmoi": {
                    "source": "https://github.com/neilime/workstation-config.git",
                    "bin_path": "/usr/local/bin/chezmoi",
                    "config_path": ".config/chezmoi/chezmoi.yaml",
                },
            },
            "secrets": {
                "bitwarden": {
                    "server": "",
                    "ssh_collection_id": "",
                    "gpg_collection_id": "",
                }
            },
        }
