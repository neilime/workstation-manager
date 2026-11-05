"""Warn about memory shortages without controlling other processes."""

from __future__ import annotations

import argparse
import html
import json
import math
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

GIB = 1024**3


@dataclass(frozen=True)
class MemoryAlertSettings:
    """Validated notification thresholds, expressed as percentages."""

    available_warning_percent: float
    available_critical_percent: float
    pressure_warning_percent: float
    pressure_critical_percent: float

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 < value <= 100
            ):
                raise ValueError(f"desktop.memory_alerts.{name} must be a number above 0 and at most 100")
        if self.available_critical_percent >= self.available_warning_percent:
            raise ValueError("desktop.memory_alerts requires available_critical_percent < available_warning_percent")
        if self.pressure_warning_percent >= self.pressure_critical_percent:
            raise ValueError("desktop.memory_alerts requires pressure_warning_percent < pressure_critical_percent")


@dataclass(frozen=True)
class MemorySnapshot:
    """A system-wide memory reading; reclaimable cache counts as available."""

    total: int
    available: int
    swap_total: int
    swap_free: int
    pressure: float

    @classmethod
    def read(cls, proc: Path = Path("/proc")) -> MemorySnapshot:
        """Read kernel counters without inspecting process arguments or environments."""
        memory = {}
        for line in (proc / "meminfo").read_text().splitlines():
            name, value = line.split(":", 1)
            memory[name] = int(value.split()[0]) * 1024
        pressure = None
        for line in (proc / "pressure/memory").read_text().splitlines():
            if line.startswith("full "):
                fields = dict(field.split("=", 1) for field in line.split()[1:])
                pressure = float(fields["avg10"])
        if pressure is None or not math.isfinite(pressure) or not 0 <= pressure <= 100:
            raise ValueError("Missing or invalid memory pressure reading")
        snapshot = cls(
            memory["MemTotal"],
            memory["MemAvailable"],
            memory["SwapTotal"],
            memory["SwapFree"],
            pressure,
        )
        if snapshot.total <= 0 or not 0 <= snapshot.available <= snapshot.total:
            raise ValueError("Invalid memory or swap counters")
        if not 0 <= snapshot.swap_free <= snapshot.swap_total:
            raise ValueError("Invalid memory or swap counters")
        return snapshot

    def describe(self) -> str:
        """Render measurements shared by status output and notifications."""
        return (
            f"RAM available: {self.available / GIB:.1f} / {self.total / GIB:.1f} GiB\n"
            f"Swap used: {(self.swap_total - self.swap_free) / GIB:.1f}"
            f" / {self.swap_total / GIB:.1f} GiB\n"
            f"Memory stalls (last 10 seconds): {self.pressure:.1f}%"
        )


class AlertPolicy:
    """Debounce warnings, escalate immediately, and avoid notification floods."""

    def __init__(self, settings: MemoryAlertSettings) -> None:
        self.settings = settings
        self.level = 0
        self.pending_level = 0
        self.pending_since = 0.0
        self.last_notification = 0.0

    def due(self, snapshot: MemorySnapshot, now: float) -> int | None:
        """Return a notification level when a threshold or reminder becomes due."""
        # Hysteresis keeps small changes near a threshold from toggling alerts.
        critical_ram = snapshot.total * self.settings.available_critical_percent / 100
        warning_ram = snapshot.total * self.settings.available_warning_percent / 100
        critical_pressure = self.settings.pressure_critical_percent
        warning_pressure = self.settings.pressure_warning_percent
        if self.level == 2:
            critical_ram *= 1.2
            critical_pressure *= 0.8
        if self.level:
            warning_ram *= 1.2
            warning_pressure *= 0.8
        if snapshot.available <= critical_ram or snapshot.pressure >= critical_pressure:
            candidate = 2
        elif snapshot.available <= warning_ram or snapshot.pressure >= warning_pressure:
            candidate = 1
        else:
            candidate = 0

        if candidate != self.pending_level:
            self.pending_level = candidate
            self.pending_since = now
        if candidate != self.level:
            delay = 30 if candidate < self.level else (0 if candidate == 2 else 10)
            if now - self.pending_since >= delay:
                return candidate
        elif candidate and now - self.last_notification >= (120 if candidate == 2 else 600):
            return candidate
        return None

    def acknowledge(self, level: int, now: float) -> None:
        """Start the reminder cooldown only after notification delivery succeeds."""
        self.level = level
        self.last_notification = now


class MemoryMonitor:
    """Poll memory counters and deliver desktop alerts without changing workloads."""

    def __init__(self, settings: MemoryAlertSettings) -> None:
        self.policy = AlertPolicy(settings)
        self.notification_id = 0

    @staticmethod
    def largest_processes() -> str:
        """Show individual RSS for a few processes, without collecting command lines."""
        try:
            result = subprocess.run(
                ["/usr/bin/ps", "-eo", "pid=,comm=,rss=", "--sort=-rss"],
                check=True,
                capture_output=True,
                text=True,
                timeout=3,
            )
            rows = []
            for line in result.stdout.splitlines()[:4]:
                fields = line.split()
                name = " ".join(fields[1:-1])
                rows.append(f"{name} (PID {fields[0]}): {int(fields[-1]) / 1024:.0f} MiB")
            return "\nLargest processes (individual RSS):\n" + "\n".join(rows)
        except (OSError, subprocess.SubprocessError, ValueError, IndexError) as error:
            print(f"Process snapshot unavailable: {error}", file=sys.stderr, flush=True)
            return ""

    def notify(self, snapshot: MemorySnapshot, level: int, *, test: bool = False) -> None:
        """Replace the previous notification and request persistent urgent alerts."""
        titles = ("Memory pressure recovered", "Memory running low", "Memory critically low")
        title = "Memory alerts test" if test else titles[level]
        body = snapshot.describe()
        if level:
            body += "\nSave your work and avoid starting additional heavy jobs."
            body += self.largest_processes()
        if test:
            body += "\nThis is a test. The monitor only sends alerts."
        result = subprocess.run(
            [
                "/usr/bin/notify-send",
                "--app-name=Workstation memory alerts",
                "--icon=dialog-warning",
                "--urgency=" + ("critical" if level == 2 else "normal"),
                "--expire-time=" + ("0" if level == 2 else "15000"),
                "--print-id",
                f"--replace-id={self.notification_id}",
                title,
                html.escape(body),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.notification_id = int(result.stdout.strip())
        print(f"{title}: {body.replace(chr(10), '; ')}", flush=True)

    def run(self) -> None:
        """Keep transient reading and notification failures visible and retry them."""
        print(f"Memory alerts started: {asdict(self.policy.settings)}", flush=True)
        while True:
            try:
                snapshot = MemorySnapshot.read()
                now = time.monotonic()
                level = self.policy.due(snapshot, now)
                if level is not None:
                    self.notify(snapshot, level)
                    # A failed notification remains due and is retried.
                    self.policy.acknowledge(level, now)
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                print(f"Memory alert check failed: {error}", file=sys.stderr, flush=True)
            time.sleep(5)


def main() -> None:
    """Run the installed monitor, inspect memory, or test desktop delivery."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="Managed JSON threshold configuration")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--status", action="store_true", help="Print current measurements and exit")
    modes.add_argument("--test-notification", action="store_true", help="Send a desktop test notification")
    args = parser.parse_args()
    try:
        settings = MemoryAlertSettings(**json.loads(args.config.read_text(encoding="utf-8")))
    except TypeError as error:
        raise ValueError("Memory alert configuration must contain exactly the four threshold settings") from error
    if args.status:
        print(MemorySnapshot.read().describe())
    elif args.test_notification:
        MemoryMonitor(settings).notify(MemorySnapshot.read(), 0, test=True)
    else:
        MemoryMonitor(settings).run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        sys.exit(f"Memory alerts: {error}")
