"""Keep the cached sudo credential fresh so long runs finish without re-prompting."""

from __future__ import annotations

import pathlib
import subprocess

ENTRYPOINT = pathlib.Path(__file__).parents[2] / "workstation.sh"


def _run_snippet(tmp_path: pathlib.Path, snippet: str) -> subprocess.CompletedProcess[str]:
    """Source the entrypoint definitions and run a focused shell snippet with a stubbed sudo."""
    sudo = tmp_path / "sudo"
    sudo.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >>"$TEST_SUDO_LOG"\nexit 0\n')
    sudo.chmod(0o700)
    # Collapse the keepalive's `sleep 50` to a short real sleep so the loop iterates quickly.
    sleep = tmp_path / "sleep"
    sleep.write_text("#!/bin/sh\nexec /bin/sleep 0.2\n")
    sleep.chmod(0o700)
    return subprocess.run(
        ["sh", "-s"],
        input=ENTRYPOINT.read_text().rsplit('main "$@"', 1)[0] + snippet,
        env={
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "TEST_SUDO_LOG": str(tmp_path / "sudo.log"),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def test_require_sudo_starts_a_keepalive_that_refreshes_until_stopped(tmp_path) -> None:
    """require_sudo runs a background refresh; stopping it clears the tracked process."""
    result = _run_snippet(
        tmp_path,
        "\n".join(
            [
                "",
                "require_sudo",
                'printf "started=%s\\n" "$SUDO_KEEPALIVE_PID"',
                'kill -0 "$SUDO_KEEPALIVE_PID" 2>/dev/null && printf "alive=yes\\n"',
                'keepalive_pid="$SUDO_KEEPALIVE_PID"',
                "start_sudo_keepalive",
                'printf "same=%s\\n" "$([ "$SUDO_KEEPALIVE_PID" = "$keepalive_pid" ] && echo yes || echo no)"',
                "/bin/sleep 0.3",
                "stop_sudo_keepalive",
                'printf "after=%s\\n" "$SUDO_KEEPALIVE_PID"',
                "/bin/sleep 0.3",
                'kill -0 "$keepalive_pid" 2>/dev/null && printf "still=yes\\n" || printf "still=no\\n"',
                "",
            ]
        ),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    assert report["started"], "require_sudo must start the keepalive"
    assert report["alive"] == "yes"
    assert report["same"] == "yes", "a second start must not spawn another keepalive"
    assert report["after"] == "", "stopping the keepalive must clear its tracked process"
    assert report["still"] == "no", "the keepalive process must be terminated"
    refreshes = (tmp_path / "sudo.log").read_text().splitlines()
    assert "-v" in refreshes, "require_sudo validates the initial credential"
    assert "-n -v" in refreshes, "the keepalive refreshes the credential non-interactively"


def test_stop_sudo_keepalive_without_a_running_keepalive_is_a_noop(tmp_path) -> None:
    """Stopping when nothing is running must not error or require a process id."""
    result = _run_snippet(
        tmp_path,
        "\nstop_sudo_keepalive\nprintf 'done=%s\\n' \"$SUDO_KEEPALIVE_PID\"\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "done=" in result.stdout
