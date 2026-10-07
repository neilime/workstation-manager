"""Run the BleachBit preset clean when at least one cleaner is enabled."""

from __future__ import annotations

import configparser
import os
import subprocess
from pathlib import Path


def resolve_config_path() -> Path:
    """Return the managed user's BleachBit configuration path."""

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / "bleachbit" / "bleachbit.ini"
    return Path.home() / ".config" / "bleachbit" / "bleachbit.ini"


def has_enabled_preset(config_path: Path) -> bool:
    """Return whether the BleachBit preset selects any cleaner option."""

    if not config_path.is_file():
        return False

    config = configparser.ConfigParser()
    config.read(config_path, encoding="utf-8-sig")
    if not config.has_section("tree"):
        return False

    for value in config["tree"].values():
        normalized = value.strip().lower()
        if (
            normalized in configparser.ConfigParser.BOOLEAN_STATES
            and configparser.ConfigParser.BOOLEAN_STATES[normalized]
        ):
            return True
    return False


def main() -> int:
    """Run BleachBit with the saved preset when one is configured."""

    if not has_enabled_preset(resolve_config_path()):
        return 0
    return subprocess.run(["bleachbit", "--clean", "--preset"], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
