"""Check that public defaults and required personal configuration satisfy the schema."""

import re

from ansible.utils.vars import merge_hash
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state import (
    DesiredStateConfigNormalizer,
)


def test_public_defaults_preserve_configured_versions_and_desktop_preferences(public_defaults) -> None:
    """Normalization consumes maintained configuration without copying its values into tests."""
    config = merge_hash(public_defaults, {"development": {"github": {"account": "fixture"}}})
    resolved = DesiredStateConfigNormalizer().normalize(config, {"USER": "fixture"})
    for section, tool in (
        ("development", "node"),
        ("development", "mise"),
        ("home_environment", "chezmoi"),
        ("desktop", "clipboard_indicator"),
    ):
        assert resolved[section][tool]["version"] == public_defaults[section][tool]["version"]
    assert resolved["development"]["mise"]["tools"] == public_defaults["development"]["mise"]["tools"]
    assert resolved["development"]["npm_packages"] == public_defaults["development"]["npm_packages"]
    for repository, revision in public_defaults["development"]["github"]["extensions"].items():
        # The default extensions publish binaries; gh requires release tags for them.
        assert re.fullmatch(r"v?\d+\.\d+\.\d+", revision), repository
        expected = "v" + revision.removeprefix("v")
        assert resolved["development"]["github"]["extensions"][repository] == expected
    assert resolved["desktop"]["browser"] == public_defaults["desktop"]["browser"]
    assert resolved["desktop"]["gnome"] == public_defaults["desktop"]["gnome"]
