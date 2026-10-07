"""Validate development tool ownership and configuration without release snapshots."""

from copy import deepcopy

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state import (
    DesiredStateConfigNormalizer,
)


def test_baseline_requirements_are_validated_without_changing_input(with_tool_versions):
    """Standard tools consume direct declarations and package deduplication preserves caller data."""
    config = with_tool_versions(
        {
            "development": {
                "packages": ["git", "make", "git"],
                "mise": {"tools": {"aqua:example/tool": "1.2.3"}},
                "github": {"account": " fixture ", "extensions": {"example/gh-tool": "1.2.3"}},
                "npm_packages": {"@example/agent": {"version": "1.2.3", "command": "agent"}},
            }
        }
    )
    original = deepcopy(config)
    result = DesiredStateConfigNormalizer().normalize(config)["development"]
    assert result["packages"] == ["git", "make"]
    assert result["mise"]["tools"] == config["development"]["mise"]["tools"]
    assert result["github"]["extensions"] == {"example/gh-tool": "v1.2.3"}
    assert result["github"]["account"] == "fixture"
    assert result["npm_packages"] == config["development"]["npm_packages"]
    assert config == original


def test_github_account_is_required_before_setup(with_tool_versions):
    """Missing or unusable identities cannot silently accept whichever account is active."""
    config = with_tool_versions({})
    del config["development"]["github"]["account"]
    with pytest.raises(ValueError, match=r"development\.github\.account.*private\.override\.yml"):
        DesiredStateConfigNormalizer().normalize(config)
    for value in (None, "", " \t", False, 42, []):
        config["development"]["github"]["account"] = value
        with pytest.raises(ValueError, match=r"development\.github\.account.*private\.override\.yml"):
            DesiredStateConfigNormalizer().normalize(config)


@pytest.mark.parametrize("package", ["@openai/codex", "@github/copilot"])
def test_standard_agent_pins_are_required_and_consumed_from_configuration(with_tool_versions, package):
    """The baseline CLIs cannot be omitted or resolve versions outside configuration."""
    config = with_tool_versions({"development": {"npm_packages": {package: {"version": "9.8.7"}}}})
    result = DesiredStateConfigNormalizer().normalize(config)["development"]
    assert result["npm_packages"] == config["development"]["npm_packages"]
    del config["development"]["npm_packages"][package]["version"]
    with pytest.raises(ValueError, match="stable release"):
        DesiredStateConfigNormalizer().normalize(config)
    del config["development"]["npm_packages"][package]
    with pytest.raises(ValueError, match="requires standard workstation tools: " + package):
        DesiredStateConfigNormalizer().normalize(config)


@pytest.mark.parametrize("package", ["", " ", 42, {}])
def test_invalid_apt_package_names_fail_before_installation(with_tool_versions, package):
    """Package declarations require valid nonempty names."""
    config = with_tool_versions({"development": {"packages": [package]}})
    with pytest.raises(ValueError, match="nonempty APT package names"):
        DesiredStateConfigNormalizer().normalize(config)


@pytest.mark.parametrize(
    "selection",
    [
        {"npm_packages": {"@example/agent": {"command": "agent"}}},
        {"mise": {"tools": {"aqua:example/tool": "latest"}}},
    ],
)
def test_selected_downloads_require_pins(selection, with_tool_versions):
    """Applications and CLIs cannot silently resolve an unreviewed latest release."""
    with pytest.raises(ValueError, match="stable release"):
        DesiredStateConfigNormalizer().normalize(with_tool_versions({"development": selection}))


def test_unsupported_tool_ownership_is_rejected(with_tool_versions):
    """Unsupported tool owners must fail before installation."""
    for selection, message in (
        ({"mise": {"tools": {"php": "1.2.3"}}}, "PHP"),
        ({"mise": {"tools": {"vfox:mise-plugins/vfox-php": "1.2.3"}}}, "PHP"),
        ({"mise": {"tools": {"composer": "1.2.3"}}}, "Composer"),
    ):
        with pytest.raises(ValueError, match=message):
            DesiredStateConfigNormalizer().normalize(with_tool_versions({"development": selection}))


@pytest.mark.parametrize("tool", ["vfox:jdx/vfox-php", "github:composer/composer"])
def test_mandatory_mise_pins_update_only_from_configuration(with_tool_versions, tool):
    """The fixed mise backend cannot be omitted or fall back to an implementation version."""
    config = with_tool_versions({"development": {"mise": {"tools": {tool: "9.8.7"}}}})
    result = DesiredStateConfigNormalizer().normalize(config)["development"]
    assert result["mise"]["tools"] == config["development"]["mise"]["tools"]
    del config["development"]["mise"]["tools"][tool]
    with pytest.raises(ValueError, match=tool + " must be a stable release"):
        DesiredStateConfigNormalizer().normalize(config)
