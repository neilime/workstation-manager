"""Drive real backup prompts without using the developer's terminal or credentials."""

from __future__ import annotations

import os
import pathlib
import select
import shlex
import subprocess
import time

INTERACTIVE_DEADLINE_SECONDS = 120
PROMPT_SETTLE_SECONDS = 0.25


def run_interactive(
    command: list[str], directory: pathlib.Path, environment: dict[str, str], answers=()
) -> tuple[int, str]:
    """Answer expected prompts in a private terminal and fail on unexpected waits."""

    command = ["script", "--quiet", "--return", "--command", shlex.join(command), os.devnull]
    pending = list(answers)
    output = ""
    unread = ""
    with subprocess.Popen(
        command,
        cwd=directory,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    ) as process:
        assert process.stdin is not None and process.stdout is not None
        deadline = time.monotonic() + INTERACTIVE_DEADLINE_SECONDS
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise AssertionError(output)
                if not select.select([process.stdout], [], [], 0.2)[0]:
                    continue
                data = os.read(process.stdout.fileno(), 65536)
                if not data:
                    break
                text = data.decode(errors="replace")
                output += text
                unread += text
                if pending and pending[0][0] in unread:
                    _prompt, answer = pending.pop(0)
                    if callable(answer):
                        answer = answer()
                    # pause can still flush tty input just after rendering its prompt on slower CI runners.
                    time.sleep(PROMPT_SETTLE_SECONDS)
                    process.stdin.write((answer + "\n").encode())
                    process.stdin.flush()
                    unread = ""
            returncode = process.wait(timeout=5)
        finally:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=5)
        if pending:
            raise AssertionError(output)
        return returncode, output
