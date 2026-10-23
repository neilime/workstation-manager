"""Keep captured browser profiles intact while disposable copies leave Sync."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_lifecycle import (
    browser_processes,
)


@contextmanager
def teardown_profile(root: Path, profile: Path, state_directory: Path) -> Iterator[Path]:
    """Clone one captured, closed profile and its encryption state into a private root."""

    if not root.is_absolute() or profile.parent != root:
        raise ValueError("Teardown requires a captured profile directly inside its browser root")
    local_state = root / "Local State"
    if any(path.is_symlink() for path in (root, profile, profile / "Preferences", local_state, state_directory)):
        raise ValueError("Refusing linked browser fixture data")
    for source in profile.rglob("*"):
        if source.is_symlink() and (
            source.readlink().is_absolute() or not source.resolve().is_relative_to(profile.resolve())
        ):
            raise ValueError("Refusing a browser profile link outside its captured profile")
    copied_root = Path(tempfile.mkdtemp(prefix="browser-teardown-", dir=state_directory))
    try:
        if local_state.exists():
            shutil.copy2(local_state, copied_root / local_state.name)
        copied_profile = copied_root / profile.name
        shutil.copytree(profile, copied_profile, symlinks=True)
        yield copied_profile
    finally:
        running = browser_processes(copied_root)
        if not running:
            shutil.rmtree(copied_root)
    if running:
        raise ValueError("The E2E teardown browser is still running; its private copy was retained")


def write_private_json(path: Path, record: dict) -> None:
    """Publish complete private fixture state without truncating the current record."""

    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Refusing linked browser fixture data")
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=f".{path.name}.", dir=path.parent, delete=False
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(record, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
