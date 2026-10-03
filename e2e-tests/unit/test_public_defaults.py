"""Validate selected public defaults used during workstation bootstrap."""

from __future__ import annotations

import pathlib
import unittest

from ansible.parsing.dataloader import DataLoader

GROUP_VARS_PATH = pathlib.Path(__file__).parents[2] / "ansible/group_vars/all.yml"


class PublicDefaultsTests(unittest.TestCase):
    """Check public package defaults and pinned development tools."""

    def test_deja_is_declared_as_pinned_mise_tool(self) -> None:
        """Déjà should stay in the managed mise defaults with a pinned release."""
        defaults = DataLoader().load_from_file(str(GROUP_VARS_PATH))
        tools = defaults["workstation_manager"]["development"]["mise"]["tools"]
        self.assertRegex(tools["github:Giammarco-Ferranti/deja"], r"^\d+(?:\.\d+)+$")

    def test_public_defaults_include_bleachbit_in_managed_apt_packages(self) -> None:
        """BleachBit should stay in the default managed Ubuntu package list."""

        defaults = DataLoader().load_from_file(str(GROUP_VARS_PATH))["workstation_manager"]

        self.assertIn("bleachbit", defaults["system"]["packages"]["apt"])


if __name__ == "__main__":
    unittest.main()
