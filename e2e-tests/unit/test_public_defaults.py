"""Checks for tracked public workstation defaults."""

from __future__ import annotations

import pathlib

from ansible.parsing.dataloader import DataLoader

WORKSPACE = pathlib.Path(__file__).parents[2]
DEFAULTS_FILE = WORKSPACE / "ansible" / "group_vars" / "all.yml"


def test_public_defaults_include_bleachbit_in_managed_apt_packages() -> None:
    """BleachBit should stay in the default managed Ubuntu package list."""

    defaults = DataLoader().load_from_file(str(DEFAULTS_FILE))["workstation_manager"]

    assert "bleachbit" in defaults["system"]["packages"]["apt"]
