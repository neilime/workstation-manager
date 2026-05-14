"""Unit tests for desired state schema normalization."""

from __future__ import annotations

from typing import Any

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state import (
    DesiredStateConfigNormalizer,
)

DECLARED_DOCKER_CLI_PLUGINS = [
    {
        "command": "docker-compose",
        "tool": "aqua:docker/compose",
    }
]

DEFAULT_HOME_ENVIRONMENT_ITEMS = (
    ("source", "neilime/workstation-config"),
    ("version", "2.70.4"),
    ("apply", True),
    ("bin_path", "/usr/local/bin/chezmoi"),
    ("config_path", ".config/chezmoi/chezmoi.yaml"),
)
DEFAULT_CHEZMOI_SOURCE = "neilime/workstation-config"


def build_home_environment(
    source: str = DEFAULT_CHEZMOI_SOURCE,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a home_environment payload without repeating the default schema literal."""

    chezmoi = dict(DEFAULT_HOME_ENVIRONMENT_ITEMS)
    chezmoi["source"] = source
    if overrides:
        chezmoi.update(overrides)

    return {"chezmoi": chezmoi}


DECLARED_HOME_ENVIRONMENT = build_home_environment(
    overrides={
        "apply": False,
        "bin_path": "/opt/bin/chezmoi",
        "config_path": ".config/chezmoi/work.yaml",
    },
)


def assert_empty_optional_system_collections(normalized: dict[str, Any]) -> None:
    """Assert the normalized system section keeps empty optional collections."""

    assert normalized["system"]["directories"] == []
    assert normalized["system"]["services"]["enabled"] == []
    assert normalized["system"]["services"]["disabled"] == []
    assert normalized["system"]["settings"]["sysctl"] == {}


def test_normalize_returns_complete_shape_with_required_chezmoi_source() -> None:
    """The required Chezmoi source should unlock the remaining documented defaults."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    raw_config: dict[str, object] = {}
    environment = {"USER": "emilien"}

    # Act
    normalized = normalizer.normalize(raw_config, environment)

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
    assert normalized["system"]["repositories"]["apt"] == []
    assert_empty_optional_system_collections(normalized)
    assert normalized["development"]["settings"]["sysctl"] == {
        "fs.inotify.max_user_watches": "524288"
    }
    assert normalized["desktop"]["flatpak"]["remote"] == "flathub"
    assert normalized["desktop"]["browser"]["package"] == "google-chrome-stable"
    assert normalized["desktop"]["browser"]["repository"]["name"] == "google-chrome"
    assert normalized["desktop"]["browser"]["default"] is True
    assert normalized["desktop"]["browser"]["profiles"] == []
    assert normalized["desktop"]["browser"]["policies"] == {}
    assert normalized["development"]["repositories"]["apt"] == []
    assert normalized["development"]["mise"] == {
        "tools": {},
        "gh_extensions": [],
        "docker_cli_plugins": [],
    }
    assert normalized["home_environment"] == build_home_environment()
    assert normalized["secrets"]["bitwarden"]["server"] == ""
    assert normalized["secrets"]["bitwarden"]["ssh_collection_id"] == ""
    assert normalized["secrets"]["bitwarden"]["gpg_collection_id"] == ""


def test_normalize_preserves_declared_values_and_env_overrides() -> None:
    """Declared values should survive normalization unless env overrides apply."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    github_cli_source = (
        "deb [signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] "
        "https://cli.github.com/packages stable main"
    )
    github_cli_repository = {
        "name": "github-cli",
        "source": github_cli_source,
        "keyring": {
            "url": "https://cli.github.com/packages/githubcli-archive-keyring.gpg",
            "path": "/usr/share/keyrings/githubcli-archive-keyring.gpg",
        },
    }
    docker_repository = {
        "name": "docker",
        "source": (
            "deb [signed-by=/etc/apt/keyrings/docker.asc] "
            "https://download.docker.com/linux/ubuntu noble stable"
        ),
        "keyring": {
            "url": "https://download.docker.com/linux/ubuntu/gpg",
            "path": "/etc/apt/keyrings/docker.asc",
        },
    }
    raw_config = {
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
            "repositories": {"apt": [github_cli_repository]},
            "directories": [
                {"path": "/var/lib/workstation-manager/cache", "mode": "0750"}
            ],
            "services": {
                "enabled": ["systemd-timesyncd"],
                "disabled": ["apache2"],
            },
            "settings": {"sysctl": {}},
        },
        "desktop": {
            "flatpak": {
                "remote": "custom",
                "packages": ["com.brave.Browser"],
            },
            "browser": {
                "default": False,
                "profiles": [{"id": "personal"}],
                "policies": {"PasswordManagerEnabled": False},
            },
            "gnome": {
                "dark_mode": False,
                "favorites": ["org.gnome.Terminal.desktop"],
            },
        },
        "development": {
            "packages": ["git", "make", "jq", "fonts-firacode"],
            "repositories": {"apt": [github_cli_repository, docker_repository]},
            "editor_packages": ["com.visualstudio.code"],
            "mise": {
                "tools": {"node": "latest", "php": "8.4"},
                "gh_extensions": ["nektos/gh-act"],
                "docker_cli_plugins": DECLARED_DOCKER_CLI_PLUGINS,
            },
            "settings": {"sysctl": {"fs.inotify.max_user_watches": "524288"}},
            "runtimes": {"node": {"manager": "fnm"}},
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
    normalized = normalizer.normalize(raw_config, environment)

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
    assert normalized["system"]["repositories"]["apt"] == [github_cli_repository]
    assert normalized["system"]["directories"] == [
        {"path": "/var/lib/workstation-manager/cache", "mode": "0750"}
    ]
    assert normalized["system"]["services"]["enabled"] == ["systemd-timesyncd"]
    assert normalized["system"]["services"]["disabled"] == ["apache2"]
    assert normalized["system"]["settings"]["sysctl"] == {}
    assert normalized["development"]["settings"]["sysctl"] == {
        "fs.inotify.max_user_watches": "524288"
    }
    assert normalized["desktop"]["flatpak"]["remote"] == "custom"
    assert normalized["desktop"]["flatpak"]["packages"] == ["com.brave.Browser"]
    assert normalized["desktop"]["browser"]["package"] == "google-chrome-stable"
    assert normalized["desktop"]["browser"]["repository"]["name"] == "google-chrome"
    assert normalized["desktop"]["browser"]["default"] is False
    assert normalized["desktop"]["browser"]["profiles"] == [{"id": "personal"}]
    assert normalized["desktop"]["browser"]["policies"] == {
        "PasswordManagerEnabled": False
    }
    assert normalized["desktop"]["gnome"]["dark_mode"] is False
    assert normalized["desktop"]["gnome"]["favorites"] == ["org.gnome.Terminal.desktop"]
    assert normalized["development"]["packages"] == [
        "git",
        "make",
        "jq",
        "fonts-firacode",
    ]
    assert normalized["development"]["repositories"]["apt"] == [
        github_cli_repository,
        docker_repository,
    ]
    assert normalized["development"]["editor_packages"] == ["com.visualstudio.code"]
    assert normalized["development"]["mise"] == {
        "tools": {"node": "latest", "php": "8.4"},
        "gh_extensions": ["nektos/gh-act"],
        "docker_cli_plugins": DECLARED_DOCKER_CLI_PLUGINS,
    }
    assert normalized["development"]["settings"]["sysctl"] == {
        "fs.inotify.max_user_watches": "524288"
    }
    assert normalized["development"]["runtimes"] == {"node": {"manager": "fnm"}}
    assert normalized["home_environment"] == DECLARED_HOME_ENVIRONMENT
    assert normalized["secrets"]["bitwarden"]["server"] == "https://vault.example.test"
    assert (
        normalized["secrets"]["bitwarden"]["ssh_collection_id"]
        == "11111111-1111-1111-1111-111111111111"
    )
    assert (
        normalized["secrets"]["bitwarden"]["gpg_collection_id"]
        == "22222222-2222-2222-2222-222222222222"
    )


def test_normalize_rejects_invalid_section_types() -> None:
    """Wrong section types should fail with a clear validation error."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    invalid_config: dict[str, object] = {"desktop": []}
    environment = {"USER": "emilien"}

    # Act / Assert
    with pytest.raises(
        ValueError, match="workstation_manager.desktop must be a mapping"
    ):
        normalizer.normalize(invalid_config, environment)


def test_normalize_preserves_explicit_empty_system_lists() -> None:
    """Explicit empty system lists should not fall back to non-empty defaults."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    raw_config = {
        "home_environment": build_home_environment(DEFAULT_CHEZMOI_SOURCE),
        "system": {
            "packages": {"prerequisites": [], "apt": []},
            "directories": [],
            "services": {"enabled": [], "disabled": []},
            "settings": {"sysctl": {}},
        },
    }
    environment = {"USER": "emilien"}

    # Act
    normalized = normalizer.normalize(raw_config, environment)

    # Assert
    assert normalized["system"]["packages"]["prerequisites"] == []
    assert normalized["system"]["packages"]["apt"] == []
    assert_empty_optional_system_collections(normalized)


def test_normalize_uses_default_chezmoi_source_when_omitted() -> None:
    """The tracked Chezmoi source should apply when no override declares one."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    raw_config: dict[str, object] = {}

    # Act
    normalized = normalizer.normalize(raw_config, {"USER": "emilien"})

    # Assert
    assert normalized["home_environment"] == build_home_environment()


def test_normalize_uses_default_chezmoi_source_when_declared_empty() -> None:
    """An empty Chezmoi source override should fall back to the tracked default."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()

    # Act
    normalized = normalizer.normalize(
        {"home_environment": {"chezmoi": {"source": ""}}},
        {"USER": "emilien"},
    )

    # Assert
    assert normalized["home_environment"] == build_home_environment()


def test_normalize_ignores_explicit_chezmoi_source_overrides() -> None:
    """The tracked Chezmoi source should stay fixed even when config declares another one."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()

    # Act
    normalized = normalizer.normalize(
        {"home_environment": {"chezmoi": {"source": "example/workstation-config"}}},
        {"USER": "emilien"},
    )

    # Assert
    assert normalized["home_environment"] == build_home_environment()


def test_normalize_rejects_bitwarden_collections_without_server() -> None:
    """Declared Bitwarden collections require an explicit Bitwarden server."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    raw_config = {
        "home_environment": build_home_environment(DEFAULT_CHEZMOI_SOURCE),
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
        normalizer.normalize(raw_config, {"USER": "emilien"})


def test_normalize_rejects_invalid_package_cache_policy() -> None:
    """Non-integer package cache policies should fail with a clear error."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    raw_config = {"system": {"packages": {"cache_valid_time": "daily"}}}
    environment = {"USER": "emilien"}

    # Act / Assert
    with pytest.raises(ValueError, match="non-negative integer value expected"):
        normalizer.normalize(raw_config, environment)


def test_normalize_rejects_invalid_bitwarden_collection_id() -> None:
    """Bitwarden collection IDs should fail fast when not UUIDs."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    raw_config = {
        "home_environment": build_home_environment(DEFAULT_CHEZMOI_SOURCE),
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
        normalizer.normalize(raw_config, {"USER": "emilien"})
