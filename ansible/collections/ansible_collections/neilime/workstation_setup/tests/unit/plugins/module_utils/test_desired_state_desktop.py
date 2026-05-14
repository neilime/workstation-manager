"""Unit tests for desktop desired state normalization."""

from __future__ import annotations

from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state import (
    DesiredStateConfigNormalizer,
)

DEFAULT_CHEZMOI_SOURCE = "https://github.com/example/dotfiles.git"


def test_normalize_returns_default_flatpak_desktop_configuration() -> None:
    """Missing desktop data should keep the documented Flatpak defaults."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    raw_config: dict[str, object] = {
        "home_environment": {"chezmoi": {"source": DEFAULT_CHEZMOI_SOURCE}}
    }
    environment = {"USER": "emilien"}

    # Act
    normalized = normalizer.normalize(raw_config, environment)

    # Assert
    assert normalized["desktop"]["flatpak"] == {
        "remote": "flathub",
        "packages": [],
    }
    assert normalized["desktop"]["browser"]["package"] == "google-chrome-stable"
    assert normalized["desktop"]["browser"]["repository"]["name"] == "google-chrome"
    assert (
        normalized["desktop"]["browser"]["repository"]["keyring"]["path"]
        == "/usr/share/keyrings/google-linux-signing-key.asc"
    )


def test_normalize_preserves_declared_flatpak_apps_separately_from_browser() -> None:
    """Flatpak application data should stay separate from browser profile data."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    raw_config = {
        "home_environment": {"chezmoi": {"source": DEFAULT_CHEZMOI_SOURCE}},
        "desktop": {
            "flatpak": {
                "remote": "flathub",
                "packages": ["com.bitwarden.desktop", "com.slack.Slack"],
            },
            "browser": {
                "default": True,
                "profiles": [{"id": "personal"}, {"id": "professional"}],
            },
        },
    }
    environment = {"USER": "emilien"}

    # Act
    normalized = normalizer.normalize(raw_config, environment)

    # Assert
    assert normalized["desktop"]["flatpak"] == {
        "remote": "flathub",
        "packages": ["com.bitwarden.desktop", "com.slack.Slack"],
    }
    assert normalized["desktop"]["browser"]["package"] == "google-chrome-stable"
    assert normalized["desktop"]["browser"]["repository"]["name"] == "google-chrome"
    assert normalized["desktop"]["browser"]["profiles"] == [
        {"id": "personal"},
        {"id": "professional"},
    ]
