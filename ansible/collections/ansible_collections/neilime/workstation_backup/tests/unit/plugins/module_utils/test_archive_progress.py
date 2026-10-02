"""Check live archive size reports and monitor cleanup with disposable files."""

from __future__ import annotations

from queue import Empty, Queue
from threading import Event

import pytest
from ansible_collections.neilime.workstation_backup.plugins.module_utils import (
    archive_progress,
)


def test_archive_growth_is_reported_before_creation_finishes(tmp_path, monkeypatch):
    """Periodic updates must observe written bytes while archive creation is active."""

    destination = tmp_path / "backup.tar.gz"
    messages = Queue()
    clock = [10.0]
    monkeypatch.setattr(archive_progress, "monotonic", lambda: clock[0])
    with archive_progress.archive_progress(str(destination), messages.put, interval=0.01):
        assert messages.get(timeout=2) == "\rCreating backup archive: preparing files, elapsed 00:00"
        clock[0] = 90.0
        destination.write_bytes(b"x" * (2 * 1024 * 1024))
        for _attempt in range(20):
            message = messages.get(timeout=2)
            if "2.0 MiB written" in message:
                break
        assert message == "\rCreating backup archive: 2.0 MiB written, elapsed 01:20"
    remaining = []
    while not messages.empty():
        remaining.append(messages.get_nowait())
    assert "2.0 MiB written" in remaining[-1]


def test_existing_archive_is_not_reported_as_newly_written_data(tmp_path):
    """Preparation must not count a previous backup's size as current progress."""

    destination = tmp_path / "backup.tar.gz"
    destination.write_bytes(b"previous archive")
    messages = Queue()
    with archive_progress.archive_progress(str(destination), messages.put, interval=0.01):
        assert "preparing files" in messages.get(timeout=2)
        assert "preparing files" in messages.get(timeout=2)
        destination.write_bytes(b"replacement archive")
    remaining = []
    while not messages.empty():
        remaining.append(messages.get_nowait())
    assert "MiB written" in remaining[-1]


def test_creation_failure_stops_progress_and_preserves_the_failure(tmp_path):
    """The monitor must exit promptly without replacing a failed archive result."""

    messages = Queue()
    with pytest.raises(RuntimeError, match="fixture archive failed"):
        with archive_progress.archive_progress(str(tmp_path / "backup.tar.gz"), messages.put, interval=0.01):
            assert "preparing files" in messages.get(timeout=2)
            raise RuntimeError("fixture archive failed")
    while not messages.empty():
        messages.get_nowait()
    with pytest.raises(Empty):
        messages.get(timeout=0.03)


def test_progress_read_errors_are_reported(tmp_path, monkeypatch):
    """Unexpected inspection failures must not disappear in a background thread."""

    destination = tmp_path / "backup.tar.gz"
    messages = Queue()
    attempted = Event()

    def unreadable_snapshot(path):
        if path.exists():
            attempted.set()
            raise PermissionError("fixture archive became unreadable")

    monkeypatch.setattr(archive_progress, "_archive_snapshot", unreadable_snapshot)
    with pytest.raises(PermissionError, match="fixture archive became unreadable"):
        with archive_progress.archive_progress(str(destination), messages.put, interval=0.01):
            destination.write_bytes(b"fixture")
            assert attempted.wait(timeout=2)
