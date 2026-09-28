#!/usr/bin/env python3
"""Temporarily enable task timings in the E2E guest's Ansible configuration."""

from __future__ import annotations

import argparse
import configparser
import os
import pathlib
import shutil
import tempfile


def prepare(config_path: pathlib.Path) -> pathlib.Path:
    """Enable profiling while retaining the exact original file for restoration."""
    parser = configparser.ConfigParser(interpolation=None)
    if config_path.exists():
        with config_path.open(encoding="utf-8") as config_file:
            parser.read_file(config_file)
    if not parser.has_section("defaults"):
        parser.add_section("defaults")
    callbacks = parser.get("defaults", "callbacks_enabled", fallback="").split(",")
    callbacks = [callback.strip() for callback in callbacks if callback.strip()]
    if "ansible.posix.profile_tasks" not in callbacks:
        callbacks.append("ansible.posix.profile_tasks")
    parser.set("defaults", "callbacks_enabled", ", ".join(callbacks))
    parser.set("defaults", "bin_ansible_callbacks", "True")

    config_path.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = pathlib.Path(tempfile.mkdtemp(prefix=".e2e-profile-", dir=config_path.parent))
    original_path = backup_dir / "original"
    replacement_path = backup_dir / "profile.cfg"
    try:
        with replacement_path.open("w", encoding="utf-8") as config_file:
            parser.write(config_file)
        if config_path.exists():
            original_stat = config_path.stat()
            replacement_path.chmod(original_stat.st_mode & 0o777)
            os.chown(replacement_path, original_stat.st_uid, original_stat.st_gid)
        else:
            # Bootstrap runs ansible-galaxy as the guest user before sudo ansible-pull.
            replacement_path.chmod(0o644)
        if config_path.exists() or config_path.is_symlink():
            config_path.replace(original_path)
        replacement_path.replace(config_path)
    except BaseException:
        if original_path.exists() or original_path.is_symlink():
            original_path.replace(config_path)
        shutil.rmtree(backup_dir)
        raise
    return backup_dir


def restore(config_path: pathlib.Path, backup_dir: pathlib.Path) -> None:
    """Restore the original configuration, or remove the temporary configuration."""
    original_path = backup_dir / "original"
    if original_path.exists() or original_path.is_symlink():
        original_path.replace(config_path)
    else:
        config_path.unlink()
    backup_dir.rmdir()


def main() -> None:
    """Configure task profiling in the disposable guest when requested by the suite."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "restore"))
    parser.add_argument("config", type=pathlib.Path)
    parser.add_argument("backup", type=pathlib.Path, nargs="?")
    args = parser.parse_args()
    if args.action == "prepare":
        if args.backup is not None:
            parser.error("prepare does not accept a backup directory")
        print(prepare(args.config))
    else:
        if args.backup is None:
            parser.error("restore requires the backup directory returned by prepare")
        restore(args.config, args.backup)


if __name__ == "__main__":
    main()
