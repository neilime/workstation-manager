"""Keep browser scenario measurements visible without exposing private diagnostics."""

from __future__ import annotations

from types import SimpleNamespace

import browser_sync_smoke as smoke
import pytest


@pytest.mark.parametrize("fails", [False, True])
def test_scenario_timing_preserves_failures_without_logging_the_exception(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fails: bool
) -> None:
    """Both outcomes include elapsed time; exceptions propagate without entering timing output."""
    ticks = iter((10.0, 12.5))
    monkeypatch.setattr(smoke, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    error = ValueError("synthetic-private-browser-data")
    try:
        with smoke.timed_scenario("native-api"):
            if fails:
                raise error
    except ValueError as raised:
        assert fails and raised is error
    else:
        assert not fails
    output = capsys.readouterr().out
    status = "failed" if fails else "passed"
    assert output == f"E2E browser timing: scenario=native-api elapsed=2.50s status={status}\n"
    assert list(smoke.timing_lines(output)) == [output.strip()]


def test_scenario_timing_rejects_private_labels(capsys: pytest.CaptureFixture[str]) -> None:
    """Unknown labels fail before timing begins and cannot appear in emitted diagnostics."""
    with (
        pytest.raises(ValueError, match="^Unsupported browser smoke timing scenario$"),
        smoke.timed_scenario("synthetic-private-label"),
    ):
        pytest.fail("An unsupported timing scenario started")
    assert not capsys.readouterr().out


def test_timing_output_filters_private_and_malformed_diagnostics() -> None:
    """Only complete validated records can bypass pytest's normal output capture."""
    valid = "E2E browser timing: scenario=window-restoration elapsed=4.25s status=passed"
    output = "\n".join(
        [
            "synthetic-private-browser-data",
            valid,
            valid.replace("window-restoration", "private-label"),
            valid.replace("4.25", "private-value"),
            valid.replace("passed", "private-status"),
            valid + " private-suffix",
        ]
    )
    assert list(smoke.timing_lines(output)) == [valid]
