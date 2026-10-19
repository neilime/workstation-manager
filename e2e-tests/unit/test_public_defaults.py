"""Check that public defaults and required personal configuration satisfy the schema."""

import re

from ansible.utils.vars import merge_hash
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state import (
    DesiredStateConfigNormalizer,
)


def test_public_defaults_preserve_configured_versions_and_desktop_preferences(
    public_defaults, private_overrides
) -> None:
    """Normalization consumes maintained configuration without copying its values into tests."""
    config = merge_hash(public_defaults, private_overrides)
    resolved = DesiredStateConfigNormalizer().normalize(config, {"USER": "fixture"})
    for section, tool in (
        ("development", "node"),
        ("development", "mise"),
        ("home_environment", "chezmoi"),
        ("desktop", "clipboard_indicator"),
        ("desktop", "system_monitor"),
    ):
        assert resolved[section][tool]["version"] == public_defaults[section][tool]["version"]
    assert resolved["development"]["mise"]["tools"] == public_defaults["development"]["mise"]["tools"]
    assert resolved["development"]["ai_tools"]["providers"] == public_defaults["development"]["ai_tools"]["providers"]
    assert resolved["development"]["ai_tools"]["orca"] == public_defaults["development"]["ai_tools"]["orca"]
    for repository, revision in public_defaults["development"]["github"]["extensions"].items():
        # The default extensions publish binaries; gh requires release tags for them.
        assert re.fullmatch(r"v?\d+\.\d+\.\d+", revision), repository
        expected = "v" + revision.removeprefix("v")
        assert resolved["development"]["github"]["extensions"][repository] == expected
    assert resolved["desktop"]["browser"] == public_defaults["desktop"]["browser"]
    assert (
        resolved["desktop"]["browser_sync_disposable_device_names"]
        == public_defaults["desktop"]["browser_sync_disposable_device_names"]
        == []
    )
    assert resolved["desktop"]["gnome"] == public_defaults["desktop"]["gnome"]


def test_public_context7_uses_the_required_private_key_selector(public_defaults, private_overrides):
    """The default MCP declaration resolves the required item password from private configuration."""
    config = merge_hash(public_defaults, private_overrides)
    resolved = DesiredStateConfigNormalizer().normalize(config, {"USER": "fixture"})
    context7 = next(
        server for server in resolved["development"]["ai_tools"]["mcp_servers"] if server["name"] == "context7"
    )
    assert context7["env"]["CONTEXT7_API_KEY"] == {
        "bitwarden_item_id": private_overrides["secrets"]["bitwarden"]["context7-api-key"],
        "field": "login.password",
    }
