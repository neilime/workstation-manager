"""Temporarily close only the managed user's selected Brave instance."""

from __future__ import annotations

import os
import pwd
import shutil
import signal
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_inspection import (
    _object,
    _read_settings,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_paths import (
    BrowserProfilePathsPlanner,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_seed import (
    _browser_process_arguments,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desktop_session import (
    DesktopSession,
)

_BROWSER_NAMES = frozenset(("brave", "brave-browser", "brave-browser-stable"))


class BrowserLifecycleBlocked(ValueError):
    """The initial browser close could not complete before any approved writes."""


def browser_processes(root: Path) -> list[int]:
    """Identify main processes owned by this account and using this exact data root."""

    result = []
    default = Path(pwd.getpwuid(os.geteuid()).pw_dir) / ".config/BraveSoftware/Brave-Browser"
    for process in Path("/proc").iterdir():
        try:
            if not process.name.isdigit() or process.stat().st_uid != os.geteuid():
                continue
            arguments = _browser_process_arguments(process)
            if not arguments or Path(arguments[0]).name not in _BROWSER_NAMES:
                continue
            if any(argument == "--type" or argument.startswith(("--type=", "--type ")) for argument in arguments):
                continue
            selected = str(default)
            for index, argument in enumerate(arguments):
                if argument.startswith("--user-data-dir="):
                    selected = argument.split("=", 1)[1]
                elif argument.startswith("--user-data-dir "):
                    selected = argument[len("--user-data-dir ") :].lstrip()
                elif argument == "--user-data-dir" and index + 1 < len(arguments):
                    selected = arguments[index + 1]
            if Path(selected).is_absolute() and Path(selected).resolve() == root.resolve():
                result.append(int(process.name))
        except (FileNotFoundError, ProcessLookupError, PermissionError, UnicodeError):
            continue
    return result


def _request_close(process: int) -> None:
    """Send one handled exit request; never send a signal with its default kill action."""

    try:
        status = (Path("/proc") / str(process) / "status").read_text()
        caught = next(line.split(":", 1)[1].strip() for line in status.splitlines() if line.startswith("SigCgt:"))
        if not int(caught, 16) & (1 << (signal.SIGINT - 1)):
            # Chromium resets the handler after the first request. A repeated
            # signal would kill it if a previous graceful shutdown was blocked.
            raise BrowserLifecycleBlocked("Brave cannot accept another safe close request; its process was retained")
        os.kill(process, signal.SIGINT)
    except (FileNotFoundError, ProcessLookupError):
        pass


def _previous_profiles(root: Path) -> list[str]:
    """Remember the profiles open before automation changes Brave's last-used profile."""

    profiles = _object(_read_settings(root / "Local State"), "profile").get("last_active_profiles", [])
    if not isinstance(profiles, list):
        raise ValueError("Brave's previous session profile list is invalid")
    planner = BrowserProfilePathsPlanner()
    return list(dict.fromkeys(planner.validate_profile_directory(profile) for profile in profiles))


def _reopen_browser(executable: str, root: Path, environment: dict[str, str], profiles: list[str]) -> None:
    """Restore every previously open profile without leaving debugging enabled."""

    for profile in profiles or [""]:
        arguments = [executable, f"--user-data-dir={root}", "--restore-last-session"]
        if profile:
            arguments.append(f"--profile-directory={profile}")
        # The restored desktop process intentionally outlives this backup.
        # The Ansible-only checker is absent from standalone Pylint.
        # pylint: disable-next=unknown-option-value
        # pylint: disable-next=consider-using-with,ansible-bad-function
        reopened = subprocess.Popen(
            arguments,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            if reopened.wait(timeout=2) != 0:
                raise ValueError("Brave could not reopen its previous desktop session")
        except subprocess.TimeoutExpired:
            pass


@contextmanager
def closed_browser(user_data_dir: str) -> Iterator[tuple[str, dict[str, str]]]:
    """Gracefully close and later reopen a previously running browser after approval."""

    root = Path(user_data_dir)
    if not root.is_absolute() or root.is_symlink():
        raise ValueError("Browser automation requires an absolute, unlinked profile root")
    executable = shutil.which("brave-browser") or shutil.which("brave-browser-stable")
    executable = executable or "brave-browser"
    environment = DesktopSession.environment()
    running = browser_processes(root)
    if running and not (environment.get("DISPLAY") or environment.get("WAYLAND_DISPLAY")):
        raise BrowserLifecycleBlocked("The desktop session is unavailable; Brave cannot be safely reopened")
    for process in running:
        _request_close(process)
    deadline = time.monotonic() + 30
    while browser_processes(root) and time.monotonic() < deadline:
        time.sleep(0.2)
    if browser_processes(root):
        raise BrowserLifecycleBlocked("Brave did not accept the close request; no profiles were forced closed")
    previous_profiles: list[str] = []
    try:
        if os.path.lexists(root / "SingletonLock"):
            raise BrowserLifecycleBlocked(
                "Brave's profile is still locked; retry after it finishes closing. The lock was retained."
            )
        if running:
            previous_profiles = _previous_profiles(root)
        yield executable, environment
    finally:
        if running and not browser_processes(root) and not os.path.lexists(root / "SingletonLock"):
            _reopen_browser(executable, root, environment, previous_profiles)
