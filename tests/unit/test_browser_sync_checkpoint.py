"""Protect fresh download/application boundaries and isolated fixture cleanup."""

from __future__ import annotations

from pathlib import Path

import browser_sync_checkpoint_experiment as experiment
import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser.sync.checkpoint import (
    DownloadCheckpoint,
)
from browser_sync_checkpoint_experiment import cleanup, fixture


def response(types: list[int], *, remaining: int = 0, success: bool = True) -> dict:
    """Build reduced synthetic protocol evidence, with no entity data or recovery words."""

    return {"kind": "response", "types": types, "remaining": remaining, "success": success}


def test_checkpoint_requires_fresh_request_coverage_for_every_expected_type() -> None:
    """An orphan response or one fresh type cannot certify all requested downloads."""

    checkpoint = DownloadCheckpoint([1, 2])
    checkpoint.observe(response([1, 2]))
    assert not checkpoint.complete
    checkpoint.observe({"kind": "request", "types": [1]})
    checkpoint.observe(response([1]))
    assert not checkpoint.complete
    checkpoint.observe({"kind": "request", "types": [2]})
    checkpoint.observe(response([2]))
    assert not checkpoint.complete
    checkpoint.observe({"kind": "applied", "types": [1, 2]})
    assert checkpoint.complete
    checkpoint.observe({"kind": "request", "types": [3]})
    assert checkpoint.complete, "Unrelated background activity cannot erase completed download evidence"


@pytest.mark.parametrize(
    "incomplete",
    [response([1, 2], remaining=1), response([1]), response([], success=False)],
)
def test_checkpoint_rejects_pagination_missing_markers_and_failed_downloads(incomplete: dict) -> None:
    """Failed or partial evidence invalidates affected types and requires a new complete response."""

    checkpoint = DownloadCheckpoint([1, 2])
    checkpoint.observe({"kind": "request", "types": [1]})
    checkpoint.observe(response([1]))
    checkpoint.observe({"kind": "request", "types": [1, 2]})
    checkpoint.observe(incomplete)
    assert not checkpoint.complete
    assert not checkpoint.completed
    assert not checkpoint.downloaded
    checkpoint.observe({"kind": "request", "types": [1, 2]})
    checkpoint.observe(response([1, 2]))
    checkpoint.observe({"kind": "applied", "types": [1, 2]})
    assert checkpoint.complete


def test_checkpoint_rejects_overlapping_requests_without_a_correlation_id() -> None:
    """Lost or reordered callbacks cannot associate an acknowledgement with a guessed request."""

    checkpoint = DownloadCheckpoint([1])
    checkpoint.observe({"kind": "request", "types": [1]})
    with pytest.raises(ValueError, match="request ordering"):
        checkpoint.observe({"kind": "request", "types": [1]})


def test_replaced_observer_cannot_reuse_previous_download_or_application_evidence() -> None:
    """Navigating diagnostics invalidates evidence even when the replacement has no events."""

    checkpoint = DownloadCheckpoint([1])
    checkpoint.consume(
        {
            "available": True,
            "generation": "00000000-0000-0000-0000-000000000001",
            "events": [{"kind": "request", "types": [1]}, response([1]), {"kind": "applied", "types": [1]}],
        }
    )
    assert checkpoint.complete
    checkpoint.consume(
        {
            "available": True,
            "generation": "00000000-0000-0000-0000-000000000002",
            "events": [],
        }
    )
    assert not checkpoint.complete
    with pytest.raises(ValueError, match="Unmatched"):
        checkpoint.observe({"kind": "applied", "types": [1]})


def test_lost_protocol_events_cannot_certify_recovery() -> None:
    """An overflowed or absent observer requires a fresh attempt instead of partial evidence."""

    checkpoint = DownloadCheckpoint([1])
    with pytest.raises(ValueError, match="observation was lost"):
        checkpoint.consume({"available": False, "events": [], "generation": None})


@pytest.mark.parametrize(
    "event",
    [
        {"kind": "private-event"},
        {"kind": "request", "types": [True]},
        {"kind": "request", "types": [1, 1]},
        {"kind": "request", "types": ["private-type"]},
        {**response([1]), "remaining": None},
        {**response([1]), "success": "private-status"},
        {**response([1]), "private-field": "private-data"},
    ],
)
def test_checkpoint_rejects_unsupported_evidence_without_echoing_payloads(event: dict) -> None:
    """Malformed or newly introduced native fields must not become evidence or leak into errors."""

    checkpoint = DownloadCheckpoint([1])
    with pytest.raises(ValueError) as error:
        checkpoint.observe(event)
    assert "private" not in str(error.value)


def test_experiment_cleanup_preserves_unowned_files(tmp_path: Path) -> None:
    """A cleanup path without fixture ownership must never become a recursive deletion target."""

    sentinel = tmp_path / "unowned"
    sentinel.write_text("preserve")
    with pytest.raises(OSError):
        cleanup(tmp_path)
    assert sentinel.read_text() == "preserve"


def test_experiment_cleanup_retains_recovery_state_without_initialized_identity(tmp_path: Path) -> None:
    """Interrupted enrollment retains its seed and ownership record for diagnosis and teardown."""

    owned = fixture(tmp_path, "source")
    owned.prepare()
    profile = owned.root / "Default"
    profile.mkdir(parents=True)
    preferences = profile / "Preferences"
    data = '{"brave_sync_v2": {"seed": "synthetic-encrypted-value"}}'
    preferences.write_text(data)
    with pytest.raises(ExceptionGroup, match="teardown incomplete"):
        cleanup(tmp_path)
    assert preferences.read_text() == data
    assert owned.load()["phase"] == "prepared"


def test_experiment_cleanup_retains_an_unflushed_live_browser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A shutdown failure must not delete a live profile before it flushes identity metadata."""

    owned = fixture(tmp_path, "source")
    owned.prepare()
    monkeypatch.setattr(experiment, "browser_processes", lambda _root: [123])
    with pytest.raises(ExceptionGroup, match="teardown incomplete"):
        cleanup(tmp_path)
    assert owned.load()["phase"] == "prepared"
