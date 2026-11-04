"""Shared plugin discovery and configuration fixtures for Python tests."""

from pathlib import Path

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import init_plugin_loader


def pytest_configure() -> None:
    """Make local collections available before tests load templating plugins."""
    init_plugin_loader(prefix_collections_path=[str(Path(__file__).parent / "ansible/collections")])


@pytest.fixture(name="public_defaults", scope="session")
def load_public_defaults():
    """Use the same public configuration as bootstrap, without copied release pins."""
    path = Path(__file__).parent / "ansible/group_vars/all.yml"
    return DataLoader().load_from_file(str(path))["workstation_manager"]


@pytest.fixture(scope="module")
def private_overrides():
    """Supply synthetic personal settings required alongside the public defaults."""
    return {
        "development": {"github": {"account": "fixture"}},
        "secrets": {
            "bitwarden": {
                "context7-api-key": "22222222-2222-2222-2222-222222222222",
            }
        },
    }
