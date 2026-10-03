"""Unit tests for the managed BleachBit preset helper."""

from __future__ import annotations

import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock

HELPER_FILE = (
    pathlib.Path(__file__).parents[2]
    / "ansible/collections/ansible_collections/neilime/workstation_setup"
    / "roles/bleachbit/files/schedule/bleachbit_clean.py"
)
HELPER_SPEC = importlib.util.spec_from_file_location("workstation_manager_bleachbit_clean_helper", HELPER_FILE)
assert HELPER_SPEC is not None
assert HELPER_SPEC.loader is not None
BLEACHBIT_CLEAN_HELPER = importlib.util.module_from_spec(HELPER_SPEC)
HELPER_SPEC.loader.exec_module(BLEACHBIT_CLEAN_HELPER)


class BleachBitCleanHelperTests(unittest.TestCase):
    """Keep the BleachBit helper safe when no preset cleaner is selected."""

    def test_main_skips_clean_when_no_preset_option_is_enabled(self) -> None:
        """The helper should exit without invoking BleachBit when no cleaner is enabled."""

        with tempfile.TemporaryDirectory() as temporary_dir:
            config_path = pathlib.Path(temporary_dir) / "bleachbit.ini"
            config_path.write_text("[tree]\napt.cache = False\n")

            with (
                mock.patch.object(BLEACHBIT_CLEAN_HELPER, "resolve_config_path", return_value=config_path),
                mock.patch.object(BLEACHBIT_CLEAN_HELPER.subprocess, "run") as bleachbit_run,
            ):
                self.assertEqual(BLEACHBIT_CLEAN_HELPER.main(), 0)
                bleachbit_run.assert_not_called()

    def test_main_runs_bleachbit_with_the_saved_preset(self) -> None:
        """The helper should execute BleachBit when the preset enables a cleaner."""

        with tempfile.TemporaryDirectory() as temporary_dir:
            config_path = pathlib.Path(temporary_dir) / "bleachbit.ini"
            config_path.write_text("[tree]\napt.cache = True\n")

            with (
                mock.patch.object(BLEACHBIT_CLEAN_HELPER, "resolve_config_path", return_value=config_path),
                mock.patch.object(BLEACHBIT_CLEAN_HELPER.subprocess, "run") as bleachbit_run,
            ):
                bleachbit_run.return_value.returncode = 0

                self.assertEqual(BLEACHBIT_CLEAN_HELPER.main(), 0)
                bleachbit_run.assert_called_once_with(["bleachbit", "--clean", "--preset"], check=False)


if __name__ == "__main__":
    unittest.main()
