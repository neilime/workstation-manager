"""Shared shell snippets for workstation entrypoint integration tests."""

from __future__ import annotations


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
