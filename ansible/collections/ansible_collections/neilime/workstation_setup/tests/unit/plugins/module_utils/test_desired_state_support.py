"""Validate shared schema contracts independently of their configuration consumers."""

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state_support import (
    DesiredStateValueResolver,
)


@pytest.mark.parametrize("version", [None, "", " ", "latest", "lts", "1.2.3-rc.1", "../../tmp", 24, True, [], {}])
def test_release_version_rejects_unresolved_unstable_and_invalid_values(version: object) -> None:
    """Required release pins reject selectors, prereleases, unsafe paths, and invalid types."""
    with pytest.raises(
        ValueError, match=r"^fixture\.version must be a stable release number supplied by configuration$"
    ):
        DesiredStateValueResolver.release_version(version, "fixture.version")


@pytest.mark.parametrize("version", ["0.0.0", "1.20.300"])
def test_release_version_preserves_configured_stable_numbers(version: str) -> None:
    """Release pins are returned unchanged without coupling tests to current tool releases."""
    assert DesiredStateValueResolver.release_version(version, "fixture.version") == version
