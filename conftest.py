"""Shared plugin discovery and configuration fixtures for local and VM tests."""

from pathlib import Path

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import init_plugin_loader
from ansible.utils.vars import merge_hash


def pytest_configure() -> None:
    """Make local collections available before tests load templating plugins."""
    init_plugin_loader(prefix_collections_path=[str(Path(__file__).parent / "ansible/collections")])


@pytest.fixture(name="public_defaults", scope="session")
def load_public_defaults():
    """Use the same public configuration as bootstrap, without copied release pins."""
    path = Path(__file__).parent / "ansible/group_vars/all.yml"
    return DataLoader().load_from_file(str(path))["workstation_manager"]


@pytest.fixture(scope="module")
def workstation_config(host, public_defaults):
    """Compare VM state with public defaults and its tracked private overrides."""
    # Collection imports must follow pytest_configure's Ansible namespace registration.
    # pylint: disable=import-outside-toplevel
    from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state import (
        DesiredStateConfigNormalizer,
    )

    path = f"{host.user().home}/.local/share/chezmoi/ansible/private.override.yml"
    override_file = host.file(path)
    overrides = (DataLoader().load(override_file.content_string) or {}) if override_file.exists else {}
    merged = merge_hash(public_defaults, overrides, list_merge="replace")
    return DesiredStateConfigNormalizer().normalize(merged, {"USER": host.user().name})
