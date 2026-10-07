"""Unit tests for desired state schema normalization."""

from __future__ import annotations

from typing import Any

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state import (
    DesiredStateConfigNormalizer,
)

BROWSER_PROFILES_COLLECTION_ID = "1659d058-b43c-4b59-8c84-cba19c437223"


DEFAULT_HOME_ENVIRONMENT_ITEMS = (
    ("version", "1.2.3"),
    ("source", "https://github.com/neilime/workstation-config.git"),
    ("bin_path", "/usr/local/bin/chezmoi"),
    ("config_path", ".config/chezmoi/chezmoi.yaml"),
)


def build_home_environment(
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a home_environment payload without repeating the default schema literal."""

    chezmoi = dict(DEFAULT_HOME_ENVIRONMENT_ITEMS)
    if overrides:
        chezmoi.update(overrides)

    return {"chezmoi": chezmoi}


DECLARED_HOME_ENVIRONMENT = build_home_environment(
    overrides={
        "source": "https://git.example.test/team/dotfiles.git",
        "bin_path": "/opt/bin/chezmoi",
        "config_path": ".config/chezmoi/work.yaml",
    },
)


def test_normalize_returns_complete_shape_with_defaults(with_tool_versions) -> None:
    """Configured versions and omitted optional values should resolve a complete document."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    raw_config: dict[str, object] = {}
    environment = {"USER": "emilien"}

    # Act
    normalized = normalizer.normalize(with_tool_versions(raw_config), environment)

    # Assert
    assert normalized["user"] == {
        "name": "emilien",
        "home": "/home/emilien",
        "projects_directory": "/home/emilien/Documents/dev-projects",
        "state_dir": "/home/emilien/.local/state/workstation-manager-v1",
    }
    assert normalized["system"]["state_dir"] == "/etc/workstation-manager-v1"
    assert normalized["system"]["locale"] == "en_US.UTF-8"
    assert normalized["system"]["timezone"] == "Europe/Paris"
    assert normalized["system"]["packages"]["prerequisites"] == ["locales", "tzdata"]
    assert normalized["system"]["packages"]["apt"] == []
    assert normalized["system"]["packages"]["cache_valid_time"] == 86400
    assert normalized["system"]["settings"]["sysctl"] == {}
    assert normalized["development"]["settings"]["sysctl"] == {"fs.inotify.max_user_watches": "524288"}
    assert normalized["desktop"]["flatpak"]["remote"] == "flathub"
    assert normalized["desktop"]["browser"] == "brave"
    assert normalized["desktop"]["gnome"] == {"favorites": None}
    assert normalized["development"]["mise"] == {
        "tools": {"vfox:jdx/vfox-php": "1.2.3", "github:composer/composer": "1.2.3"},
        "version": "1.2.3",
    }
    assert normalized["home_environment"] == build_home_environment()
    assert normalized["secrets"]["bitwarden"]["server"] == ""
    assert normalized["secrets"]["bitwarden"]["ssh_collection_id"] == ""
    assert normalized["secrets"]["bitwarden"]["gpg_collection_id"] == ""
    assert normalized["secrets"]["bitwarden"]["browser_profiles_collection_id"] == ""


@pytest.mark.parametrize(
    "tool", ["node", "aqua:cli/cli", "aqua:docker/cli", "aqua:docker/compose", "aqua:docker/buildx"]
)
def test_rejects_duplicate_native_runtime_ownership(with_tool_versions, tool: str) -> None:
    """Global mise entries cannot shadow setup's native workstation commands."""
    with pytest.raises(ValueError, match="system-owned"):
        DesiredStateConfigNormalizer().normalize(
            with_tool_versions({"development": {"mise": {"tools": {tool: "latest"}}}}), {}
        )


@pytest.mark.parametrize(
    "section,tool", [("development", "node"), ("development", "mise"), ("home_environment", "chezmoi")]
)
@pytest.mark.parametrize("version", [None, "", " ", "latest", "lts", "1.2.3-rc.1", "../../tmp", 24, True, [], {}])
def test_runtime_versions_require_reproducible_stable_releases(
    with_tool_versions, section: str, tool: str, version: object
) -> None:
    """Unresolved selectors and invalid URL components fail before downloading."""
    config = with_tool_versions({section: {tool: {"version": version}}})
    with pytest.raises(
        ValueError, match=rf"{section}\.{tool}\.version must be a stable release number supplied by configuration"
    ):
        DesiredStateConfigNormalizer().normalize(config, {})


@pytest.mark.parametrize(
    "section,tool",
    [
        ("development", "node"),
        ("development", "mise"),
        ("development", "orca"),
        ("home_environment", "chezmoi"),
    ],
)
def test_missing_tool_versions_do_not_fall_back_to_python_defaults(with_tool_versions, section: str, tool: str) -> None:
    """Every release must come from the effective configuration."""
    config = with_tool_versions({})
    del config[section][tool]["version"]
    with pytest.raises(
        ValueError, match=rf"{section}\.{tool}\.version must be a stable release number supplied by configuration"
    ):
        DesiredStateConfigNormalizer().normalize(config, {})


@pytest.mark.parametrize(
    "section,tool",
    [
        ("development", "node"),
        ("development", "mise"),
        ("development", "orca"),
        ("home_environment", "chezmoi"),
    ],
)
def test_tool_version_updates_only_require_configuration_changes(with_tool_versions, section: str, tool: str) -> None:
    """A new configured release reaches consumers without an implementation edit."""
    config = with_tool_versions({section: {tool: {"version": "9.8.7"}}})
    normalized = DesiredStateConfigNormalizer().normalize(config, {})
    assert normalized[section][tool]["version"] == config[section][tool]["version"]


def test_native_tool_preferences_survive_normalization(with_tool_versions) -> None:
    """Explicit native releases and extensions are retained."""
    config: dict[str, Any] = {
        "development": {"node": {"version": "24.0.0"}, "github": {"extensions": {"owner/gh-tool": "1.2.3"}}},
    }
    normalized = DesiredStateConfigNormalizer().normalize(with_tool_versions(config), {})
    assert normalized["development"]["node"] == config["development"]["node"]
    assert normalized["development"]["github"]["extensions"] == {"owner/gh-tool": "v1.2.3"}


def test_normalize_preserves_declared_values_and_env_overrides(with_tool_versions) -> None:
    """Declared values should survive normalization unless env overrides apply."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    raw_config: dict[str, object] = {
        "user": {
            "name": "declared",
            "home": "/srv/declared",
            "projects_directory": "/workspace/projects",
            "state_dir": "/workspace/state",
        },
        "system": {
            "state_dir": "/var/lib/workstation-manager",
            "locale": "fr_FR.UTF-8",
            "timezone": "UTC",
            "packages": {
                "prerequisites": ["locales", "curl"],
                "apt": ["git"],
                "cache_valid_time": 3600,
            },
            "settings": {"sysctl": {}},
        },
        "desktop": {
            "flatpak": {
                "remote": "custom",
                "packages": ["com.brave.Browser"],
            },
            "browser": "brave",
            "gnome": {
                "favorites": ["org.gnome.Terminal.desktop"],
            },
        },
        "development": {
            "packages": ["git", "make", "jq", "fonts-firacode"],
            "editor_packages": ["code"],
            "mise": {
                "tools": {"aqua:helm/helm": "5.6.7"},
            },
            "settings": {"sysctl": {"fs.inotify.max_user_watches": "524288"}},
        },
        "home_environment": DECLARED_HOME_ENVIRONMENT,
        "secrets": {
            "bitwarden": {
                "server": "https://vault.example.test",
                "ssh_collection_id": "11111111-1111-1111-1111-111111111111",
                "gpg_collection_id": "22222222-2222-2222-2222-222222222222",
            },
        },
    }
    environment = {
        "WORKSTATION_MANAGER_USER": "override",
        "WORKSTATION_MANAGER_USER_HOME": "/home/override",
        "WORKSTATION_MANAGER_USER_STATE_DIR": "/state/override",
        "WORKSTATION_MANAGER_SYSTEM_STATE_DIR": "/system/override",
    }

    # Act
    normalized = normalizer.normalize(with_tool_versions(raw_config), environment)

    # Assert
    assert normalized["user"] == {
        "name": "override",
        "home": "/home/override",
        "projects_directory": "/workspace/projects",
        "state_dir": "/state/override",
    }
    assert normalized["system"]["state_dir"] == "/system/override"
    assert normalized["system"]["locale"] == "fr_FR.UTF-8"
    assert normalized["system"]["timezone"] == "UTC"
    assert normalized["system"]["packages"]["prerequisites"] == ["locales", "curl"]
    assert normalized["system"]["packages"]["apt"] == ["git"]
    assert normalized["system"]["packages"]["cache_valid_time"] == 3600
    assert normalized["system"]["settings"]["sysctl"] == {}
    assert normalized["development"]["settings"]["sysctl"] == {"fs.inotify.max_user_watches": "524288"}
    assert normalized["desktop"]["flatpak"]["remote"] == "custom"
    assert normalized["desktop"]["flatpak"]["packages"] == ["com.brave.Browser"]
    assert normalized["desktop"]["browser"] == "brave"
    assert normalized["desktop"]["gnome"]["favorites"] == ["org.gnome.Terminal.desktop"]
    assert normalized["development"]["packages"] == [
        "git",
        "make",
        "jq",
        "fonts-firacode",
    ]
    assert normalized["development"]["editor_packages"] == ["code"]
    assert normalized["development"]["mise"] == {
        "tools": {
            "vfox:jdx/vfox-php": "1.2.3",
            "github:composer/composer": "1.2.3",
            "aqua:helm/helm": "5.6.7",
        },
        "version": "1.2.3",
    }
    assert normalized["development"]["settings"]["sysctl"] == {"fs.inotify.max_user_watches": "524288"}
    assert normalized["home_environment"] == DECLARED_HOME_ENVIRONMENT
    assert normalized["secrets"]["bitwarden"]["server"] == "https://vault.example.test"
    assert normalized["secrets"]["bitwarden"]["ssh_collection_id"] == "11111111-1111-1111-1111-111111111111"
    assert normalized["secrets"]["bitwarden"]["gpg_collection_id"] == "22222222-2222-2222-2222-222222222222"


def test_normalize_rejects_invalid_section_types(with_tool_versions) -> None:
    """Wrong section types should fail with a clear validation error."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    invalid_config: dict[str, object] = {"desktop": []}
    environment = {"USER": "emilien"}

    # Act / Assert
    with pytest.raises(ValueError, match="workstation_manager.desktop must be a mapping"):
        normalizer.normalize(with_tool_versions(invalid_config), environment)


def test_normalize_preserves_explicit_empty_system_lists(with_tool_versions) -> None:
    """Explicit empty system lists should not fall back to non-empty defaults."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    raw_config: dict[str, object] = {
        "home_environment": build_home_environment(),
        "system": {
            "packages": {"prerequisites": [], "apt": []},
            "settings": {"sysctl": {}},
        },
    }
    environment = {"USER": "emilien"}

    # Act
    normalized = normalizer.normalize(with_tool_versions(raw_config), environment)

    # Assert
    assert normalized["system"]["packages"]["prerequisites"] == []
    assert normalized["system"]["packages"]["apt"] == []
    assert normalized["system"]["settings"]["sysctl"] == {}


def test_normalize_rejects_bitwarden_collections_without_server(with_tool_versions) -> None:
    """Declared Bitwarden collections require an explicit Bitwarden server."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    raw_config: dict[str, object] = {
        "home_environment": build_home_environment(),
        "secrets": {
            "bitwarden": {
                "server": "",
                "ssh_collection_id": "11111111-1111-1111-1111-111111111111",
            },
        },
    }

    # Act / Assert
    with pytest.raises(
        ValueError,
        match="workstation_manager.secrets.bitwarden.server must not be empty",
    ):
        normalizer.normalize(with_tool_versions(raw_config), {"USER": "emilien"})


def test_normalize_rejects_invalid_package_cache_policy(with_tool_versions) -> None:
    """Non-integer package cache policies should fail with a clear error."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    raw_config: dict[str, object] = {"system": {"packages": {"cache_valid_time": "daily"}}}
    environment = {"USER": "emilien"}

    # Act / Assert
    with pytest.raises(ValueError, match="non-negative integer value expected"):
        normalizer.normalize(with_tool_versions(raw_config), environment)


def test_normalize_rejects_invalid_bitwarden_collection_id(with_tool_versions) -> None:
    """Bitwarden collection IDs should fail fast when not UUIDs."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    raw_config: dict[str, object] = {
        "home_environment": build_home_environment(),
        "secrets": {
            "bitwarden": {
                "server": "https://vault.example.test",
                "ssh_collection_id": "Escemi/SSH",
            }
        },
    }

    # Act / Assert
    with pytest.raises(
        ValueError,
        match="workstation_manager.secrets.bitwarden.ssh_collection_id must be a UUID string",
    ):
        normalizer.normalize(with_tool_versions(raw_config), {"USER": "emilien"})


@pytest.mark.parametrize(
    "source, expected",
    [
        ("https://git.example.test/team/dotfiles.git", "https://git.example.test/team/dotfiles.git"),
        ("git@example.test:team/dotfiles.git", "git@example.test:team/dotfiles.git"),
        ("/srv/dotfiles", "/srv/dotfiles"),
        ("  https://git.example.test/team/dotfiles.git  ", "https://git.example.test/team/dotfiles.git"),
    ],
)
def test_normalize_preserves_configured_chezmoi_source(with_tool_versions, source: str, expected: str) -> None:
    """The configured repository or local path must reach Chezmoi without being replaced by the default."""

    normalized = DesiredStateConfigNormalizer().normalize(
        with_tool_versions({"home_environment": {"chezmoi": {"source": source}}})
    )
    assert normalized["home_environment"]["chezmoi"]["source"] == expected


def test_normalize_defaults_null_chezmoi_source(with_tool_versions) -> None:
    """A null placeholder uses the documented source just like an omitted value."""

    normalized = DesiredStateConfigNormalizer().normalize(
        with_tool_versions({"home_environment": {"chezmoi": {"source": None}}})
    )
    assert normalized["home_environment"]["chezmoi"]["source"] == "https://github.com/neilime/workstation-config.git"


@pytest.mark.parametrize("source", ["", " ", "\t\n"])
def test_normalize_rejects_blank_chezmoi_source(with_tool_versions, source: str) -> None:
    """An explicitly blank source must not silently initialize the default repository."""

    with pytest.raises(ValueError, match="chezmoi.source must be a non-empty string"):
        DesiredStateConfigNormalizer().normalize(
            with_tool_versions({"home_environment": {"chezmoi": {"source": source}}})
        )


@pytest.mark.parametrize("source", [12, True, [], {}])
def test_normalize_rejects_non_string_chezmoi_source(with_tool_versions, source: object) -> None:
    """Source values must be strings before they are passed to the Chezmoi command."""

    with pytest.raises(ValueError, match="chezmoi.source must be a string"):
        DesiredStateConfigNormalizer().normalize(
            with_tool_versions({"home_environment": {"chezmoi": {"source": source}}})
        )


def test_browser_recovery_collection_selector(with_tool_versions):
    """The optional browser collection is validated like key collections."""
    normalizer = DesiredStateConfigNormalizer()
    config = {
        "secrets": {
            "bitwarden": {
                "server": "https://vault.example.test",
                "browser_profiles_collection_id": BROWSER_PROFILES_COLLECTION_ID,
            }
        }
    }
    assert (
        normalizer.normalize(with_tool_versions(config), {"USER": "test"})["secrets"]["bitwarden"][
            "browser_profiles_collection_id"
        ]
        == BROWSER_PROFILES_COLLECTION_ID
    )
    config["secrets"]["bitwarden"]["browser_profiles_collection_id"] = "invalid"
    with pytest.raises(ValueError, match="browser_profiles_collection_id must be a UUID"):
        normalizer.normalize(with_tool_versions(config), {"USER": "test"})


def test_browser_profile_collection_requires_server(with_tool_versions):
    """A profile collection cannot be fetched without a selected Bitwarden server."""

    config = {
        "secrets": {
            "bitwarden": {
                "server": "",
                "browser_profiles_collection_id": BROWSER_PROFILES_COLLECTION_ID,
            }
        }
    }
    with pytest.raises(ValueError, match="bitwarden.server must not be empty"):
        DesiredStateConfigNormalizer().normalize(with_tool_versions(config))


@pytest.mark.parametrize("section,key", [("secrets", "bitwarden"), ("development", "mise")])
def test_configuration_rejects_unknown_fields_without_exposing_values(with_tool_versions, section, key):
    """Closed configuration mappings validate the current schema and keep values private."""
    config = with_tool_versions({section: {key: {"unexpected_option": "synthetic-secret"}}})
    with pytest.raises(ValueError, match="contains unsupported fields") as error:
        DesiredStateConfigNormalizer().normalize(config)
    assert "synthetic-secret" not in str(error.value)


def test_normalize_does_not_expose_oh_my_zsh_configuration(with_tool_versions) -> None:
    """Private configuration cannot choose the setup-owned framework revision."""
    normalized = DesiredStateConfigNormalizer().normalize(
        with_tool_versions({"home_environment": {"oh_my_zsh": {"version": "unmanaged-revision"}}})
    )
    assert normalized["home_environment"] == build_home_environment()


def test_empty_gnome_favorites_explicitly_clears_the_dock(with_tool_versions) -> None:
    """An empty preference list is distinct from leaving the setting unmanaged."""
    normalized = DesiredStateConfigNormalizer().normalize(
        with_tool_versions({"desktop": {"gnome": {"favorites": []}}}),
        {"USER": "fixture"},
    )
    assert normalized["desktop"]["gnome"] == {"favorites": []}


def test_gnome_favorites_require_a_list(with_tool_versions) -> None:
    """A string must not be interpreted as a list of favorite applications."""
    with pytest.raises(ValueError):
        DesiredStateConfigNormalizer().normalize(
            with_tool_versions({"desktop": {"gnome": {"favorites": "browser"}}}), {"USER": "fixture"}
        )
