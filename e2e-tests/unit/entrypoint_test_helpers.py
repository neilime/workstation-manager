"""Shared shell snippets for workstation entrypoint integration tests."""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path


def terminal_command(command: list[str]) -> list[str]:
    """Allocate a terminal with the real script utility, bypassing CLI stand-ins."""
    return [shutil.which("script") or "script", "--quiet", "--return", "--command", shlex.join(command), os.devnull]


def entrypoint_source_with_mock_controller() -> str:
    """Point controller commands at each test's existing isolated CLI stand-ins."""
    source = (Path(__file__).parents[2] / "workstation.sh").read_text()
    fixture_controller = r"""
fixture_commands="${PATH%%:*}"
case "$fixture_commands" in
/tmp/*)
    mkdir -p "$fixture_commands/controller"
    if [ ! -L "$fixture_commands/controller/bin" ]; then
        ln -s "$fixture_commands" "$fixture_commands/controller/bin"
    fi
    ANSIBLE_VENV_DIR="$fixture_commands/controller"
    ;;
esac
"""
    return source.rsplit('main "$@"', 1)[0] + fixture_controller + '\nmain "$@"\n'


def controlling_tty_exec_python(exec_arguments: str) -> str:
    """Claim the provided tty before execing /bin/sh with the given arguments."""

    return (
        "import fcntl, os, sys, termios\n"
        "with open(sys.argv[1]) as terminal:\n"
        "    fcntl.ioctl(terminal.fileno(), termios.TIOCSCTTY, 0)\n"
        f'os.execv("/bin/sh", {exec_arguments})\n'
    )


def sudo_passthrough_script(prefix: str = "", *, suffix: str = 'exec "$@"\n') -> str:
    """Ignore preserve-env flags before delegating to the wrapped command."""

    return (
        "#!/bin/sh\n"
        + prefix
        + 'while [ "$#" -gt 0 ]; do\n'
        + '  case "$1" in\n'
        + "    --preserve-env=*) shift; continue ;;\n"
        + "    *) break ;;\n"
        + "  esac\n"
        + "done\n"
        + suffix
    )
