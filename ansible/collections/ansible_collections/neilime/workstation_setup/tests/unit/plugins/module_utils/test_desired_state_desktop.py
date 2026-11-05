"""Unit tests for desktop desired state normalization."""

from __future__ import annotations

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state import (
    DesiredStateConfigNormalizer,
)


def test_normalize_returns_default_flatpak_desktop_configuration(with_tool_versions) -> None:
    """Missing desktop data should keep the documented Flatpak defaults."""

    # Arrange
    normalizer = DesiredStateConfigNormalizer()
    raw_config: dict[str, object] = {}
    environment = {"USER": "emilien"}

    # Act
    normalized = normalizer.normalize(with_tool_versions(raw_config), environment)

    # Assert
    assert normalized["desktop"]["flatpak"] == {
        "remote": "flathub",
        "packages": [],
    }
    assert normalized["desktop"]["browser"] == "brave"


def test_normalize_preserves_declared_flatpak_apps_separately_from_browser(with_tool_versions) -> None:
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
    normalized = normalizer.normalize(with_tool_versions(raw_config), environment)

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
def test_browser_selector_rejects_invalid_identifiers(with_tool_versions, selector: object) -> None:
    """Adapter selection must not accept mappings, empty values, or paths."""

    with pytest.raises(ValueError, match="desktop.browser must be a browser identifier"):
        DesiredStateConfigNormalizer().normalize(with_tool_versions({"desktop": {"browser": selector}}))


def test_browser_selector_accepts_future_adapter_identifiers(with_tool_versions) -> None:
    """Available adapters are resolved outside this browser-neutral normalizer."""

    normalized = DesiredStateConfigNormalizer().normalize(
        with_tool_versions({"desktop": {"browser": "example_browser2"}})
    )
    assert normalized["desktop"]["browser"] == "example_browser2"


@pytest.mark.parametrize("extension", ["clipboard_indicator", "system_monitor"])
@pytest.mark.parametrize("field", ["version", "sha256"])
def test_managed_gnome_extension_requires_pins(with_tool_versions, extension, field):
    """A managed GNOME extension cannot install an unpinned artifact."""
    config = with_tool_versions({})
    del config["desktop"][extension][field]
    normalizer = DesiredStateConfigNormalizer()
    with pytest.raises(ValueError, match="explicit valid pin"):
        normalizer.normalize(config)


@pytest.mark.parametrize("extension", ["clipboard_indicator", "system_monitor"])
def test_managed_gnome_extension_rejects_placeholder_digest(with_tool_versions, extension):
    """An all-zero digest must fail during configuration validation before any workstation changes."""
    config = with_tool_versions({"desktop": {extension: {"sha256": "0" * 64}}})
    with pytest.raises(ValueError, match=rf"desktop\.{extension}\.sha256.*all-zero placeholder"):
        DesiredStateConfigNormalizer().normalize(config)


def test_duplicate_flatpak_scanner_is_rejected(with_tool_versions):
    """Simple Scan uses APT; a second delivery in the Flatpak selection is invalid."""
    with pytest.raises(ValueError, match="Simple Scan is installed through APT"):
        DesiredStateConfigNormalizer().normalize(
            with_tool_versions(
                {
                    "desktop": {"flatpak": {"packages": ["org.gnome.SimpleScan"]}},
                }
            )
        )


def test_memory_alert_defaults_match_public_configuration(with_tool_versions, public_defaults):
    """Fallback normalization and setup must agree on the alert thresholds."""
    resolved = DesiredStateConfigNormalizer().normalize(with_tool_versions({}))
    assert resolved["desktop"]["memory_alerts"] == public_defaults["desktop"]["memory_alerts"]


def test_memory_alert_override_preserves_other_defaults(with_tool_versions, public_defaults):
    """A partial personal override must retain the other validated thresholds."""
    override = {"available_warning_percent": 35}
    resolved = DesiredStateConfigNormalizer().normalize(with_tool_versions({"desktop": {"memory_alerts": override}}))
    assert resolved["desktop"]["memory_alerts"] == {**public_defaults["desktop"]["memory_alerts"], **override}


@pytest.mark.parametrize(
    "override",
    [
        {"available_warning_percent": True},
        {"available_critical_percent": "10"},
        {"available_critical_percent": 0},
        {"pressure_warning_percent": float("nan")},
        {"pressure_critical_percent": 101},
        {"available_critical_percent": 50},
        {"pressure_warning_percent": 50},
        {"kill_processes": True},
    ],
)
def test_memory_alert_invalid_thresholds_fail_before_setup(with_tool_versions, override):
    """Reject malformed values, crossed thresholds, and unsupported behavior."""
    with pytest.raises(ValueError, match="memory_alerts"):
        DesiredStateConfigNormalizer().normalize(with_tool_versions({"desktop": {"memory_alerts": override}}))
