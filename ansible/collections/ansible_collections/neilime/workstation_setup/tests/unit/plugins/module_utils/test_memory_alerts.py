"""Exercise alert decisions and notification failures without allocating memory."""

from __future__ import annotations

import subprocess

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.memory_alerts import (
    AlertPolicy,
    MemoryAlertSettings,
    MemoryMonitor,
    MemorySnapshot,
)


@pytest.fixture(name="settings")
def alert_settings():
    """Use synthetic thresholds independent of the workstation defaults."""
    return MemoryAlertSettings(40, 20, 10, 30)


def snapshot(available=60, pressure=0, total=1000):
    """Express available RAM as a percentage of a synthetic machine's size."""
    return MemorySnapshot(total, int(total * available / 100), 800, 0, pressure)


def test_full_swap_without_memory_pressure_does_not_alert(settings):
    """Cold swapped pages alone must not cause repeated warnings."""
    assert AlertPolicy(settings).due(snapshot(), 100) is None


def test_warning_debounce_resets_after_a_brief_spike(settings):
    """Warn only after ten consecutive seconds in the warning range."""
    policy = AlertPolicy(settings)
    assert policy.due(snapshot(35), 100) is None
    assert policy.due(snapshot(), 105) is None
    assert policy.due(snapshot(35), 110) is None
    assert policy.due(snapshot(35), 115) is None
    assert policy.due(snapshot(35), 120) == 1


@pytest.mark.parametrize("reading", [snapshot(15), snapshot(60, 30)])
def test_urgent_shortage_or_stalls_alert_immediately(settings, reading):
    """Either very low headroom or high full PSI must trigger on the first sample."""
    assert AlertPolicy(settings).due(reading, 100) == 2


def test_pressure_warning_with_available_ram(settings):
    """Pressure must warn even when MemAvailable has not crossed its threshold."""
    policy = AlertPolicy(settings)
    assert policy.due(snapshot(60, 10), 100) is None
    assert policy.due(snapshot(60, 10), 110) == 1


def test_ram_thresholds_scale_with_machine_size(settings):
    """A smaller workstation must not inherit the original laptop's GiB limits."""
    for total in (1000, 8000):
        assert AlertPolicy(settings).due(snapshot(15, total=total), 100) == 2
        assert AlertPolicy(settings).due(snapshot(60, total=total), 100) is None


def test_escalation_bypasses_reminder_cooldown(settings):
    """A warning must never suppress a subsequent urgent alert."""
    policy = AlertPolicy(settings)
    policy.acknowledge(1, 100)
    assert policy.due(snapshot(15), 105) == 2


@pytest.mark.parametrize("level,available,interval", [(1, 35, 600), (2, 15, 120)])
def test_successful_notifications_are_rate_limited(settings, level, available, interval):
    """Reminders repeat at a bounded rate even if the user dismisses an alert."""
    policy = AlertPolicy(settings)
    policy.acknowledge(level, 100)
    assert policy.due(snapshot(available), 100 + interval - 1) is None
    assert policy.due(snapshot(available), 100 + interval) == level


def test_undelivered_notification_is_retried(settings):
    """Failure must not start a cooldown that hides the shortage."""
    policy = AlertPolicy(settings)
    assert policy.due(snapshot(15), 100) == 2
    assert policy.due(snapshot(15), 105) == 2


def test_recovery_requires_hysteresis_and_stability(settings):
    """Small fluctuations must not clear warnings; sustained recovery clears once."""
    policy = AlertPolicy(settings)
    policy.acknowledge(1, 100)
    assert policy.due(snapshot(45), 110) is None
    assert policy.due(snapshot(), 120) is None
    assert policy.due(snapshot(), 145) is None
    assert policy.due(snapshot(), 150) == 0
    policy.acknowledge(0, 150)
    assert policy.due(snapshot(), 1000) is None


def test_urgent_recovery_does_not_flap(settings):
    """Recover from urgent to warning only after sufficient stable headroom."""
    policy = AlertPolicy(settings)
    policy.acknowledge(2, 100)
    assert policy.due(snapshot(22), 105) is None
    assert policy.due(snapshot(35), 110) is None
    assert policy.due(snapshot(35), 140) == 1


@pytest.fixture(name="proc")
def proc_files(tmp_path):
    """Provide kernel-style files with free memory much lower than available."""
    (tmp_path / "pressure").mkdir()
    (tmp_path / "meminfo").write_text(
        "MemTotal: 1000 kB\nMemAvailable: 600 kB\nMemFree: 1 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n",
        encoding="utf-8",
    )
    (tmp_path / "pressure/memory").write_text(
        "some avg10=80.00 avg60=10.00 avg300=1.00 total=100\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n",
        encoding="utf-8",
    )
    return tmp_path


def test_reclaimable_cache_is_available_and_no_swap_is_supported(proc, settings):
    """Use MemAvailable and full PSI, without requiring a swap device."""
    reading = MemorySnapshot.read(proc)
    assert reading.available == 600 * 1024
    assert reading.swap_total == 0
    assert reading.pressure == 0
    assert AlertPolicy(settings).due(reading, 100) is None


@pytest.mark.parametrize("pressure", ["full avg10=nan\n", "full avg10=101\n", "some avg10=0.00\n"])
def test_invalid_pressure_is_not_reported_as_healthy(proc, pressure):
    """Missing or invalid counters must produce an actionable error."""
    (proc / "pressure/memory").write_text(pressure, encoding="utf-8")
    with pytest.raises(ValueError, match="pressure"):
        MemorySnapshot.read(proc)


def test_invalid_memory_counters_are_rejected(proc):
    """A negative MemAvailable value must not manufacture an urgent notification."""
    path = proc / "meminfo"
    path.write_text(path.read_text().replace("MemAvailable: 600", "MemAvailable: -1"), encoding="utf-8")
    with pytest.raises(ValueError, match="counters"):
        MemorySnapshot.read(proc)


def test_notification_uses_only_read_only_process_inspection_and_notify_send(settings, monkeypatch):
    """Keep alerts non-destructive, bounded, persistent when urgent, and markup-safe."""
    notifications = []

    def run(command, **kwargs):
        assert kwargs["timeout"] <= 5
        if command == ["/usr/bin/ps", "-eo", "pid=,comm=,rss=", "--sort=-rss"]:
            return subprocess.CompletedProcess(command, 0, "123 <worker> 102400\n", "")
        assert command[0] == "/usr/bin/notify-send"
        notifications.append(command)
        return subprocess.CompletedProcess(command, 0, "42\n", "")

    monkeypatch.setattr(subprocess, "run", run)
    monitor = MemoryMonitor(settings)
    monitor.notify(snapshot(15), 2)
    monitor.notify(snapshot(15), 2)
    assert "--urgency=critical" in notifications[0]
    assert "--expire-time=0" in notifications[0]
    assert "&lt;worker&gt;" in notifications[0][-1]
    assert "--replace-id=42" in notifications[1]


def test_notification_failure_is_visible(settings, monkeypatch):
    """A failed notification must not be counted as delivered."""

    def fail(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, "notify-send")

    monkeypatch.setattr(subprocess, "run", fail)
    monitor = MemoryMonitor(settings)
    with pytest.raises(subprocess.CalledProcessError):
        monitor.notify(snapshot(), 0, test=True)
    assert monitor.notification_id == 0
