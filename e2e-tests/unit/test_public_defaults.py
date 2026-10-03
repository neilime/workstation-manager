"""Validate selected public defaults used during workstation bootstrap."""

from __future__ import annotations

import pathlib
import unittest

from ansible.parsing.dataloader import DataLoader

GROUP_VARS_PATH = pathlib.Path(__file__).parents[2] / "ansible/group_vars/all.yml"


class PublicDefaultsTests(unittest.TestCase):
    """Check public defaults that should remain explicitly pinned."""

    def test_deja_is_declared_as_pinned_mise_tool(self) -> None:
        """Déjà should stay in the managed mise defaults with a pinned release."""
        defaults = DataLoader().load_from_file(str(GROUP_VARS_PATH))
        tools = defaults["workstation_manager"]["development"]["mise"]["tools"]
        self.assertRegex(tools["github:Giammarco-Ferranti/deja"], r"^\d+(?:\.\d+)+$")


if __name__ == "__main__":
    unittest.main()
