"""Inspect and remove optional Snap installations with verified data recovery."""

from __future__ import annotations

import http.client
import json
import os
import pwd
import re
import shutil
import socket
import tempfile
from collections.abc import Callable
from pathlib import Path

CommandRunner = Callable[[list[str]], tuple[int, str, str]]


class SnapInventory:
    """Read local snapd metadata without querying the store or exposing credentials."""

    @staticmethod
    def read(endpoint: str) -> object:
        """Read one bounded response from the local snapd Unix socket."""
        connection = http.client.HTTPConnection("localhost", timeout=30)
        connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.sock.settimeout(30)
        try:
            connection.sock.connect("/run/snapd.socket")
            connection.request("GET", endpoint)
            response = connection.getresponse()
            body = response.read(4 * 1024 * 1024 + 1)
            if response.status != 200 or len(body) > 4 * 1024 * 1024:
                raise ValueError("Cannot inspect snapd safely; check snapd.socket and retry setup.")
            payload = json.loads(body)
            if not isinstance(payload, dict) or payload.get("type") != "sync":
                raise ValueError("Unexpected snapd response; no Snap removal was attempted.")
            return payload["result"]
        except http.client.HTTPException as error:
            raise ValueError("Cannot read the local snapd inventory; check snapd.socket and retry setup.") from error
        finally:
            connection.close()

    @staticmethod
    def removal_groups(system: object, records: object) -> list[list[str]]:
        """Reject boot dependencies and order applications, bases, then snapd."""
        if not isinstance(system, dict) or system.get("on-classic") is not True:
            raise ValueError("Snap is essential on this installation. Migrate to conventional Ubuntu before setup.")
        if not isinstance(records, list):
            raise ValueError("Invalid installed Snap inventory.")
        groups: list[set[str]] = [set(), set(), set()]
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("Invalid installed Snap record.")
            name, kind = record.get("name"), record.get("type")
            if not isinstance(name, str) or re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name) is None:
                raise ValueError("Invalid installed Snap name.")
            if kind in {"kernel", "gadget"}:
                raise ValueError(
                    "Snap provides boot or encryption components. Migrate to conventional Ubuntu before setup."
                )
            if kind not in {"app", "base", "os", "snapd"}:
                raise ValueError(f"Cannot safely classify Snap {name}; no removal was attempted.")
            index = 2 if kind == "snapd" else 1 if kind in {"base", "os"} else 0
            groups[index].add(name)
        return [sorted(group) for group in groups]

    @staticmethod
    def user_directories() -> list[Path]:
        """Find Snap data in actual account homes, including root."""
        homes = {Path(entry.pw_dir) for entry in pwd.getpwall() if entry.pw_dir.startswith("/")}
        homes.discard(Path("/"))
        return sorted(
            {
                home / name
                for home in homes
                for name in ("snap", ".snap")
                if (home / name).is_dir() or ((home / name).is_symlink() and not (home / name).is_file())
            }
        )

    @staticmethod
    def mounts() -> list[Path]:
        """Read actual mount boundaries, including same-filesystem bind mounts."""
        paths = []
        for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
            encoded = line.split()[4]
            paths.append(Path(re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), encoded)))
        return paths


class SnapRecoveryArchive:
    """Archive stable application data before any Snap package or data deletion."""

    def __init__(self, run: CommandRunner) -> None:
        self.run = run

    @staticmethod
    def validate_paths(paths: list[Path], mounts: list[Path]) -> None:
        """Refuse redirected roots and mounted data that removal could destroy."""
        for path in paths:
            if path.is_symlink() or path.resolve() != path:
                raise ValueError(f"Snap data path {path} is redirected; reconcile it before removal.")
            if any(mount == path or mount.is_relative_to(path) for mount in mounts):
                raise ValueError(f"Snap data path {path} contains mounted data; reconcile it before removal.")

    def create(self, paths: list[Path], destination: Path) -> str:
        """Create an archive with ownership, ACLs, and xattrs, then compare its data."""
        if not paths:
            return ""
        self.validate_paths(paths, SnapInventory.mounts())
        if not destination.is_absolute() or destination.resolve() != destination:
            raise ValueError("Snap recovery directory must not be redirected.")
        forbidden = [*paths, *[Path(value) for value in SnapRemoval.SYSTEM_PATHS]]
        if any(destination == path or destination.is_relative_to(path) for path in forbidden):
            raise ValueError("Snap recovery directory must be outside every removed directory.")
        destination.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination.chmod(0o700)
        directory = Path(tempfile.mkdtemp(prefix="snap-", dir=destination))
        archive = directory / "data.tar"
        descriptor = os.open(archive, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        arguments = ["--acls", "--xattrs", "--numeric-owner", "--file", str(archive), "--directory", "/"]
        create = ["tar", "--create", *arguments, "--", *[str(path).lstrip("/") for path in paths]]
        if self.run(create)[0] != 0:
            raise ValueError("Snap recovery archive could not be created; originals are preserved.")
        if self.run(["tar", "--compare", *arguments])[0] != 0:
            raise ValueError("Snap recovery archive verification failed; originals are preserved.")
        return str(archive)


class SnapRemoval:
    """Converge optional Snap packages and their state to complete absence."""

    SYSTEM_PATHS = ("/snap", "/var/snap", "/var/lib/snapd", "/var/cache/snapd")

    def __init__(self, run: CommandRunner) -> None:
        self.run = run

    def command(self, arguments: list[str], message: str) -> str:
        """Execute a checked command without leaking application state in errors."""
        code, output, _error_output = self.run(arguments)
        if code != 0:
            raise ValueError(message)
        return output

    def installed_packages(self) -> list[str]:
        """Include residual configurations and Ubuntu launchers that depend on snapd."""
        packages = []
        for name in ("snapd", "gnome-software-plugin-snap", "firefox", "chromium-browser", "thunderbird"):
            code, output, _error_output = self.run(
                ["dpkg-query", "--show", "--showformat=${db:Status-Status}\t${Pre-Depends}\t${Depends}", name]
            )
            if code not in (0, 1):
                raise ValueError("Cannot inspect Snap Debian packages.")
            fields = output.split("\t", maxsplit=1)
            present = code == 0 and fields[0].strip() not in {"", "not-installed"}
            depends_on_snap = len(fields) == 2 and re.search(r"(?:^|[,|\t])\s*snapd(?:\s|,|$)", fields[1])
            if present and (name in {"snapd", "gnome-software-plugin-snap"} or depends_on_snap):
                packages.append(name)
        return packages

    def inspect(self) -> list[list[str]]:
        """Fail before mutation if snapd is essential or its inventory is unavailable."""
        if not Path("/usr/bin/snap").exists():
            if list(Path("/var/lib/snapd/snaps").glob("*.snap")):
                raise ValueError("Snap packages remain without a working snapd. Repair snapd before setup.")
            return [[], [], []]
        return SnapInventory.removal_groups(
            SnapInventory.read("/v2/system-info"), SnapInventory.read("/v2/snaps?select=all")
        )

    @staticmethod
    def require_closed_applications() -> None:
        """Avoid taking an inconsistent archive of running graphical applications."""
        for executable in Path("/proc").glob("[0-9]*/exe"):
            try:
                target = os.readlink(executable)
            except FileNotFoundError:
                continue
            if target.startswith("/snap/") and not target.startswith("/snap/snapd/"):
                raise ValueError(
                    "Close Snap applications, including background windows, then rerun setup to preserve their data."
                )

    def remove(self, backup_directory: str, *, check_mode: bool) -> dict[str, object]:
        """Verify recovery, then remove all Snap state."""
        groups = self.inspect()
        packages = self.installed_packages()
        user_paths = SnapInventory.user_directories()
        system_paths = [Path(value) for value in self.SYSTEM_PATHS if Path(value).exists() or Path(value).is_symlink()]
        changed = bool(any(groups) or packages or user_paths or system_paths)
        self._verify_package_purge(packages)
        if check_mode or not changed:
            return {"changed": changed, "backup_archive": ""}
        # Stop service writes before archiving; GUI applications must be closed by their user.
        if any(groups):
            self._stop_services()
        self.require_closed_applications()
        data_paths = [
            path
            for path in [Path("/var/snap"), Path("/var/lib/snapd/snapshots"), *user_paths]
            if path.exists() or path.is_symlink()
        ]
        archive = SnapRecoveryArchive(self.run).create(data_paths, Path(backup_directory))
        for group in groups:
            if group:
                self.command(
                    ["snap", "remove", "--purge", *group],
                    "Snap removal failed. Recovery data is preserved; inspect snap changes and rerun setup.",
                )
        if packages:
            self.command(
                ["apt-get", "--yes", "purge", *packages],
                "Snap Debian package purge failed; recovery data is preserved.",
            )
        self._remove_paths([*system_paths, *user_paths])
        if self.installed_packages():
            raise ValueError("Snap packages remain after removal; setup is incomplete.")
        return {"changed": True, "backup_archive": archive}

    def _verify_package_purge(self, packages: list[str]) -> None:
        """Fail before stopping apps if APT would remove unrelated packages."""
        if packages:
            preview = self.command(
                ["apt-get", "--simulate", "purge", *packages], "Cannot preview the snapd package purge."
            )
            removed = {line.split()[1] for line in preview.splitlines() if line.startswith(("Remv ", "Purg "))}
            if removed.difference(packages):
                raise ValueError(
                    "Purging snapd would remove other packages. Reconcile those dependencies before retrying."
                )

    def _stop_services(self) -> None:
        """Stop only actual Snap services before preserving their data."""
        services = SnapInventory.read("/v2/apps?select=service")
        if not isinstance(services, list):
            raise ValueError("Cannot inspect Snap services before data preservation.")
        for service in services:
            if not isinstance(service, dict) or not all(isinstance(service.get(key), str) for key in ("snap", "name")):
                raise ValueError("Invalid Snap service inventory; no package or data removal was attempted.")
            if service.get("active"):
                self.command(
                    ["snap", "stop", service["snap"] + "." + service["name"]],
                    "Cannot stop Snap services; no package or data removal was attempted.",
                )

    @staticmethod
    def _remove_paths(paths: list[Path]) -> None:
        """Delete only unmounted Snap state after verified recovery."""
        mounts = SnapInventory.mounts()
        for path in paths:
            if any(mount == path or mount.is_relative_to(path) for mount in mounts):
                raise ValueError(f"Snap mount remains beneath {path}; unmount it before retrying cleanup.")
            if path.is_symlink():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                raise ValueError(f"Unexpected file at {path}; manual reconciliation is required.")
