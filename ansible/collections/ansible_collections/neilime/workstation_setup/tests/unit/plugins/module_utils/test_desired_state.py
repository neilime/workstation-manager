"""Unit tests for desired state schema normalization."""

from __future__ import annotations

from typing import Any

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state import (
    DesiredStateConfigNormalizer,
)

BROWSER_PROFILES_COLLECTION_ID = "1659d058-b43c-4b59-8c84-cba19c437223"

DECLARED_DOCKER_CLI_PLUGINS = [
    {
        "command": "docker-compose",
        "tool": "aqua:docker/compose",
    }
]

DEFAULT_HOME_ENVIRONMENT_ITEMS = (
    ("version", "2.70.4"),
    ("source", "https://github.com/neilime/workstation-config.git"),
    ("apply", True),
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


def test_normalize_returns_complete_shape_with_defaults() -> None:
    """An empty configuration should resolve the documented defaults."""

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
    assert normalized["development"]["settings"]["sysctl"] == {"fs.inotify.max_user_watches": "524288"}
    assert normalized["desktop"]["flatpak"]["remote"] == "flathub"
    assert normalized["desktop"]["browser"] == "brave"
    assert normalized["desktop"]["gnome"]["show_trash"] is True
    assert normalized["desktop"]["gnome"]["autostart"] == []
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
    assert normalized["secrets"]["bitwarden"]["browser_profiles_collection_id"] == ""


def test_normalize_preserves_declared_values_and_env_overrides() -> None:
    """Declared values should survive normalization unless env overrides apply."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    github_cli_source = (
        "deb [signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main"
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
            "deb [signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable"
        ),
        "keyring": {
            "url": "https://download.docker.com/linux/ubuntu/gpg",
            "path": "/etc/apt/keyrings/docker.asc",
        },
    }
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
            "repositories": {"apt": [github_cli_repository]},
            "directories": [{"path": "/var/lib/workstation-manager/cache", "mode": "0750"}],
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
            "browser": "brave",
            "gnome": {
                "dark_mode": False,
                "show_trash": False,
                "autostart": [
                    {
                        "desktop_file": "com.github.hluk.copyq.desktop",
                        "name": "CopyQ",
                        "command": "flatpak run com.github.hluk.copyq --start-server hide",
                    }
                ],
                "favorites": ["org.gnome.Terminal.desktop"],
            },
        },
        "development": {
            "packages": ["git", "make", "jq", "fonts-firacode"],
            "repositories": {"apt": [github_cli_repository, docker_repository]},
            "editor_packages": ["com.visualstudio.code"],
            "mise": {
                "tools": {"node": "latest", "php": "8.4"},
                "gh_extensions": ["nektos/gh-act", "github/gh-stack"],
                "docker_cli_plugins": DECLARED_DOCKER_CLI_PLUGINS,
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
    assert normalized["system"]["directories"] == [{"path": "/var/lib/workstation-manager/cache", "mode": "0750"}]
    assert normalized["system"]["services"]["enabled"] == ["systemd-timesyncd"]
    assert normalized["system"]["services"]["disabled"] == ["apache2"]
    assert normalized["system"]["settings"]["sysctl"] == {}
    assert normalized["development"]["settings"]["sysctl"] == {"fs.inotify.max_user_watches": "524288"}
    assert normalized["desktop"]["flatpak"]["remote"] == "custom"
    assert normalized["desktop"]["flatpak"]["packages"] == ["com.brave.Browser"]
    assert normalized["desktop"]["browser"] == "brave"
    assert normalized["desktop"]["gnome"]["dark_mode"] is False
    assert normalized["desktop"]["gnome"]["show_trash"] is False
    assert normalized["desktop"]["gnome"]["autostart"] == [
        {
            "desktop_file": "com.github.hluk.copyq.desktop",
            "name": "CopyQ",
            "command": "flatpak run com.github.hluk.copyq --start-server hide",
        }
    ]
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
        "gh_extensions": ["nektos/gh-act", "github/gh-stack"],
        "docker_cli_plugins": DECLARED_DOCKER_CLI_PLUGINS,
    }
    assert normalized["development"]["settings"]["sysctl"] == {"fs.inotify.max_user_watches": "524288"}
    assert normalized["home_environment"] == DECLARED_HOME_ENVIRONMENT
    assert normalized["secrets"]["bitwarden"]["server"] == "https://vault.example.test"
    assert normalized["secrets"]["bitwarden"]["ssh_collection_id"] == "11111111-1111-1111-1111-111111111111"
    assert normalized["secrets"]["bitwarden"]["gpg_collection_id"] == "22222222-2222-2222-2222-222222222222"


def test_normalize_rejects_invalid_section_types() -> None:
    """Wrong section types should fail with a clear validation error."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    invalid_config: dict[str, object] = {"desktop": []}
    environment = {"USER": "emilien"}

    # Act / Assert
    with pytest.raises(ValueError, match="workstation_manager.desktop must be a mapping"):
        normalizer.normalize(invalid_config, environment)


def test_normalize_preserves_explicit_empty_system_lists() -> None:
    """Explicit empty system lists should not fall back to non-empty defaults."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    raw_config: dict[str, object] = {
        "home_environment": build_home_environment(),
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


def test_normalize_rejects_bitwarden_collections_without_server() -> None:
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
        normalizer.normalize(raw_config, {"USER": "emilien"})


def test_normalize_rejects_invalid_package_cache_policy() -> None:
    """Non-integer package cache policies should fail with a clear error."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    raw_config: dict[str, object] = {"system": {"packages": {"cache_valid_time": "daily"}}}
    environment = {"USER": "emilien"}

    # Act / Assert
    with pytest.raises(ValueError, match="non-negative integer value expected"):
        normalizer.normalize(raw_config, environment)


def test_normalize_rejects_invalid_bitwarden_collection_id() -> None:
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
        normalizer.normalize(raw_config, {"USER": "emilien"})


@pytest.mark.parametrize(
    "source, expected",
    [
        ("https://git.example.test/team/dotfiles.git", "https://git.example.test/team/dotfiles.git"),
        ("git@example.test:team/dotfiles.git", "git@example.test:team/dotfiles.git"),
        ("/srv/dotfiles", "/srv/dotfiles"),
        ("  https://git.example.test/team/dotfiles.git  ", "https://git.example.test/team/dotfiles.git"),
    ],
)
def test_normalize_preserves_configured_chezmoi_source(source: str, expected: str) -> None:
    """The configured repository or local path must reach Chezmoi without being replaced by the default."""

    normalized = DesiredStateConfigNormalizer().normalize({"home_environment": {"chezmoi": {"source": source}}})
    assert normalized["home_environment"]["chezmoi"]["source"] == expected


def test_normalize_defaults_null_chezmoi_source() -> None:
    """A null placeholder uses the documented source just like an omitted value."""

    normalized = DesiredStateConfigNormalizer().normalize({"home_environment": {"chezmoi": {"source": None}}})
    assert normalized["home_environment"]["chezmoi"]["source"] == "https://github.com/neilime/workstation-config.git"


@pytest.mark.parametrize("source", ["", " ", "\t\n"])
def test_normalize_rejects_blank_chezmoi_source(source: str) -> None:
    """An explicitly blank source must not silently initialize the default repository."""

    with pytest.raises(ValueError, match="chezmoi.source must be a non-empty string"):
        DesiredStateConfigNormalizer().normalize({"home_environment": {"chezmoi": {"source": source}}})


@pytest.mark.parametrize("source", [12, True, [], {}])
def test_normalize_rejects_non_string_chezmoi_source(source: object) -> None:
    """Source values must be strings before they are passed to the Chezmoi command."""

    with pytest.raises(ValueError, match="chezmoi.source must be a string"):
        DesiredStateConfigNormalizer().normalize({"home_environment": {"chezmoi": {"source": source}}})


def test_browser_recovery_collection_selector():
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
        normalizer.normalize(config, {"USER": "test"})["secrets"]["bitwarden"]["browser_profiles_collection_id"]
        == BROWSER_PROFILES_COLLECTION_ID
    )
    config["secrets"]["bitwarden"]["browser_profiles_collection_id"] = "invalid"
    with pytest.raises(ValueError, match="browser_profiles_collection_id must be a UUID"):
        normalizer.normalize(config, {"USER": "test"})


def test_browser_profile_collection_requires_server():
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
        DesiredStateConfigNormalizer().normalize(config)


def test_obsolete_browser_collection_selector_is_rejected():
    """Do not silently treat the old recovery-only selector as an unconfigured browser."""

    config = {"secrets": {"bitwarden": {"browser_collection_id": BROWSER_PROFILES_COLLECTION_ID}}}
    with pytest.raises(ValueError, match="use browser_profiles_collection_id with complete profile notes"):
        DesiredStateConfigNormalizer().normalize(config)


def test_normalize_does_not_expose_oh_my_zsh_configuration() -> None:
    """Private configuration cannot choose the setup-owned framework revision."""
    normalized = DesiredStateConfigNormalizer().normalize(
        {"home_environment": {"oh_my_zsh": {"version": "unmanaged-revision"}}}
    )
    assert normalized["home_environment"] == build_home_environment()
