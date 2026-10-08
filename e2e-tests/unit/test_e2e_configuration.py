"""Resolve assertion expectations against the VM account rather than controller paths."""

import json
from unittest import mock

import pytest


@pytest.fixture(name="host", scope="module")
def vm_host():
    """Provide a VM account whose home differs from the controller's default layout."""
    host = mock.Mock()
    host.user.return_value.name = "fixture"
    host.user.return_value.home = "/srv/fixture.guest"
    host.file.return_value.exists = True
    host.file.return_value.content_string = json.dumps(
        {
            "user": {"name": "controller", "home": "/home/controller"},
            "development": {"github": {"account": "fixture"}},
        }
    )
    return host


def test_vm_configuration_uses_the_managed_account_home(workstation_config) -> None:
    """A nonstandard guest home takes precedence over configured controller identity."""
    assert workstation_config["user"]["name"] == "fixture"
    assert workstation_config["user"]["home"] == "/srv/fixture.guest"
    assert workstation_config["user"]["projects_directory"] == "/srv/fixture.guest/Documents/dev-projects"
    assert workstation_config["user"]["state_dir"].startswith("/srv/fixture.guest/.local/state/")
