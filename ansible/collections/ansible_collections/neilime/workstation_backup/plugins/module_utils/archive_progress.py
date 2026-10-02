"""Display archive growth while Ansible creates the local backup."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from time import monotonic

from ansible_collections.neilime.workstation_backup.plugins.module_utils.terminal import (
    terminal_prompt,
)


def _archive_snapshot(path: Path) -> tuple[int, int, int] | None:
    """Distinguish newly written data from an archive that already existed."""

    try:
        metadata = path.stat()
    except FileNotFoundError:
        return None
    return metadata.st_ino, metadata.st_mtime_ns, metadata.st_size


def _progress_message(size: int | None, elapsed: float) -> str:
    """Describe compressed bytes and elapsed time without estimating completion."""

    minutes, seconds = divmod(int(elapsed), 60)
    progress = "preparing files" if size is None else f"{size / (1024 * 1024):.1f} MiB written"
    return terminal_prompt(f"Creating backup archive: {progress}, elapsed {minutes:02d}:{seconds:02d}")


@contextmanager
def archive_progress(destination: str, display: Callable[[str], None], interval: float = 5.0) -> Iterator[None]:
    """Report live size while the calling thread runs Ansible's archive module."""

    path = Path(destination)
    initial_snapshot = _archive_snapshot(path)
    started_at = monotonic()
    stopped = Event()

    def update() -> None:
        snapshot = _archive_snapshot(path)
        size = snapshot[2] if snapshot is not None and snapshot != initial_snapshot else None
        display(_progress_message(size, monotonic() - started_at))

    def monitor() -> None:
        while not stopped.wait(interval):
            update()

    display(_progress_message(None, 0))
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(monitor)
        try:
            yield
        finally:
            stopped.set()
        pending.result()
    update()
