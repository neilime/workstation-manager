"""Run a foreground command with private, locked, disk-backed temporary storage."""

from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


class ScratchCommand:
    """Own disposable files without touching checkouts or unrelated temporary data."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def prepare(self) -> None:
        """Require a private directory on a filesystem that does not consume RAM."""
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = self.root.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise ValueError(f"Scratch storage must be a private directory owned by this user: {self.root}")
        filesystem = subprocess.run(
            ["stat", "--file-system", "--format=%T", "--", str(self.root)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if filesystem in {"tmpfs", "ramfs"}:
            raise ValueError(f"Scratch storage must be on disk, not {filesystem}: {self.root}")

    @staticmethod
    def clean(directory: Path) -> None:
        """Remove only this invocation's directory once inherited leases are released."""
        # Use the same cleaner as the timer, including its mount and symlink guards.
        path = json.dumps(str(directory).replace("%", "%%"), ensure_ascii=False)
        subprocess.run(
            ["systemd-tmpfiles", "--user", "--clean", "-"],
            input=f"e {path} - - - 0\n",
            capture_output=True,
            text=True,
            check=True,
        )
        try:
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                # A child still holds the lease; the daily cleaner can retry later.
                print(f"Scratch storage is still in use; retained for scheduled cleanup: {directory}", file=sys.stderr)
                return
            if directory.lstat().st_ino != os.fstat(descriptor).st_ino:
                raise ValueError(f"Scratch directory changed during execution: {directory}")
            try:
                directory.rmdir()
            except OSError as error:
                if error.errno not in {errno.ENOTEMPTY, errno.EBUSY}:
                    raise
                print(f"Scratch storage contains protected entries; retained: {directory}", file=sys.stderr)
        finally:
            os.close(descriptor)

    def run(self, command: list[str]) -> int:
        """Preserve the command's environment, working directory, streams, and exit status."""
        self.prepare()
        directory = Path(tempfile.mkdtemp(prefix="task-", dir=self.root))
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH)
            result = subprocess.run(
                command,
                env={**os.environ, "TMPDIR": str(directory)},
                pass_fds=(descriptor,),
                check=False,
            )
            return result.returncode if result.returncode >= 0 else 128 - result.returncode
        finally:
            # Closing our copy preserves any locks inherited by surviving children.
            os.close(descriptor)
            self.clean(directory)


def main() -> int:
    """Expose a command wrapper without changing the caller's shell environment."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs=argparse.REMAINDER, help="foreground command and its arguments")
    arguments = parser.parse_args()
    command = arguments.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("provide a command to run")
    try:
        return ScratchCommand(Path.home() / ".cache/workstation-manager/scratch").run(command)
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"workstation-manager-scratch: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
