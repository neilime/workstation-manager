"""Unit tests for desktop desired state normalization."""

from __future__ import annotations

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state import (
    DesiredStateConfigNormalizer,
)


def test_normalize_returns_default_flatpak_desktop_configuration() -> None:
    """Missing desktop data should keep the documented Flatpak defaults."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    raw_config: dict[str, object] = {}
    environment = {"USER": "emilien"}

    # Act
    normalized = normalizer.normalize(raw_config, environment)

    # Assert
    assert normalized["desktop"]["flatpak"] == {
        "remote": "flathub",
        "packages": [],
    }
    assert normalized["desktop"]["browser"] == "brave"


def test_normalize_preserves_declared_flatpak_apps_separately_from_browser() -> None:
    """Flatpak application data should stay separate from browser profile data."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    raw_config: dict[str, object] = {
        "desktop": {
            "flatpak": {
                "remote": "flathub",
                "packages": ["com.bitwarden.desktop", "com.slack.Slack"],
            },
            "browser": "brave",
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
    assert normalized["desktop"]["browser"] == "brave"


@pytest.mark.parametrize(
    "selector",
    [
        {},
        {"adapter": "brave"},
        {"settings": {"profiles": []}},
        {"package": "brave-browser"},
        [],
        None,
        True,
        12,
        "",
        " brave",
        "Brave",
        "brave-browser",
        "../brave",
        "/usr/bin/brave",
        "brave/browser",
        "brave\n",
    ],
)
def test_browser_selector_rejects_invalid_identifiers(selector: object) -> None:
    """Adapter selection must not accept mappings, empty values, or paths."""

    with pytest.raises(ValueError, match="desktop.browser must be a browser identifier"):
        DesiredStateConfigNormalizer().normalize({"desktop": {"browser": selector}})


def test_browser_selector_accepts_future_adapter_identifiers() -> None:
    """Available adapters are resolved outside this browser-neutral normalizer."""

    normalized = DesiredStateConfigNormalizer().normalize({"desktop": {"browser": "example_browser2"}})
    assert normalized["desktop"]["browser"] == "example_browser2"
