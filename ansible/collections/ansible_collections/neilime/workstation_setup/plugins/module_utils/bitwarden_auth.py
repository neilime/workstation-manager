"""Authenticate Bitwarden CLI email/password logins with hidden verification prompts."""

from __future__ import annotations

import os
import pty
import re
import select
import subprocess
import termios
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_ANSI_ESCAPE_RE: Final[re.Pattern[str]] = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_CODE_PROMPTS: Final[tuple[tuple[str, str], ...]] = (
    ("Two-step login code:", "Bitwarden emailed a two-step login code: "),
    (
        "New device verification required. Enter OTP sent to login email:",
        "Bitwarden emailed a new-device verification code: ",
    ),
)
_CODE_REQUIRED_MESSAGES: Final[tuple[str, ...]] = ("Code is required.", "Verification code is required.")
_CODE_REJECTED_MESSAGES: Final[tuple[str, ...]] = ("Invalid verification code.", "Invalid email or verification code")
_EMAIL_PASSWORD_REJECTED_MESSAGES: Final[tuple[str, ...]] = (
    "Invalid master password.",
    "Username or password is incorrect. Try again.",
)
_LOGIN_ARGUMENTS: Final[tuple[str, ...]] = (
    "--passwordenv",
    "BITWARDEN_PASSWORD",
    "--method",
    "1",
    "--raw",
)
_LOGIN_RETRY_NOTICE: Final[str] = (
    "Bitwarden rejected the supplied verification code; request the latest email code and try again.\n"
)


class BitwardenPromptUnavailableError(RuntimeError):
    """Raised when an interactive verification prompt cannot use the terminal."""


class BitwardenPromptCancelledError(RuntimeError):
    """Raised when a verification prompt is cancelled."""


@dataclass(frozen=True)
class BitwardenLoginResult:
    """Return the unlocked login token or a safe retry reason."""

    session: str = ""
    failure_reason: str = ""


def login_with_email_password(
    email: str,
    password: str,
    *,
    interactive: bool,
    prompt_for_code: Callable[[str], str] | None = None,
    notice: Callable[[str], None] | None = None,
) -> BitwardenLoginResult:
    """Log in with email/password and hide any emailed verification code entry."""

    prompt_callback = prompt_for_code if prompt_for_code is not None else _prompt_for_hidden_code
    notice_callback = notice if notice is not None else _write_notice

    while True:
        result = _run_login_attempt(
            email,
            password,
            interactive=interactive,
            prompt_for_code=prompt_callback,
        )
        if result.failure_reason != "code_rejected" or not interactive:
            return result
        notice_callback(_LOGIN_RETRY_NOTICE)


def _run_login_attempt(
    email: str,
    password: str,
    *,
    interactive: bool,
    prompt_for_code: Callable[[str], str],
) -> BitwardenLoginResult:
    """Execute one Bitwarden login attempt and classify only safe failure reasons."""

    argv = ["bw", "login", email, *_LOGIN_ARGUMENTS]
    environment = os.environ.copy()
    environment["BITWARDEN_PASSWORD"] = password
    environment["BW_SESSION"] = ""

    if not interactive:
        completed = subprocess.run(  # noqa: S603,S607
            argv,
            capture_output=True,
            check=False,
            env=environment,
            stdin=subprocess.DEVNULL,
            text=True,
        )
        output = _normalize_output((completed.stdout + completed.stderr).encode())
        return _result_from_output(completed.returncode, output)

    return _run_interactive_login(argv, environment, prompt_for_code)


def _run_interactive_login(
    argv: list[str], environment: dict[str, str], prompt_for_code: Callable[[str], str]
) -> BitwardenLoginResult:
    """Run Bitwarden CLI under a hidden TTY relay to keep emailed codes out of logs."""

    master_fd, slave_fd = pty.openpty()
    output = bytearray()
    handled_prompts = {prompt: 0 for prompt, _ in _CODE_PROMPTS}
    try:
        _disable_echo(slave_fd)
        with subprocess.Popen(  # noqa: S603,S607
            argv,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=environment,
            close_fds=True,
        ) as process:
            while True:
                if process.poll() is not None:
                    _drain_master(master_fd, output)
                    break
                ready, _, _ = select.select([master_fd], [], [], 0.1)
                if master_fd not in ready:
                    continue
                chunk = _read_master(master_fd)
                if not chunk:
                    continue
                output.extend(chunk)
                result = _handle_code_prompts(
                    _normalize_output(bytes(output)),
                    handled_prompts,
                    prompt_for_code,
                    master_fd,
                    process,
                )
                if result is not None:
                    return result
            return _result_from_output(process.wait(), _normalize_output(bytes(output)))
    finally:
        os.close(slave_fd)
        os.close(master_fd)


def _result_from_output(returncode: int, output: str) -> BitwardenLoginResult:
    """Map Bitwarden CLI output to retryable reasons without exposing private data."""

    if returncode == 0:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        session = lines[-1] if lines else ""
        if session:
            return BitwardenLoginResult(session=session)
        raise ValueError("Bitwarden login succeeded without returning a session token.")

    if any(message in output for message in _CODE_REQUIRED_MESSAGES):
        return BitwardenLoginResult(failure_reason="code_required")
    if any(message in output for message in _CODE_REJECTED_MESSAGES):
        return BitwardenLoginResult(failure_reason="code_rejected")
    if any(message in output for message in _EMAIL_PASSWORD_REJECTED_MESSAGES):
        return BitwardenLoginResult(failure_reason="email_password_rejected")
    raise ValueError("Bitwarden CLI login failed unexpectedly.")


def _disable_echo(tty_fd: int) -> None:
    """Prevent echoed codes from appearing in captured terminal output."""

    attributes = termios.tcgetattr(tty_fd)
    attributes[3] &= ~termios.ECHO
    termios.tcsetattr(tty_fd, termios.TCSANOW, attributes)


def _handle_code_prompts(
    output: str,
    handled_prompts: dict[str, int],
    prompt_for_code: Callable[[str], str],
    master_fd: int,
    process: subprocess.Popen[bytes],
) -> BitwardenLoginResult | None:
    """Prompt privately for each newly seen Bitwarden verification-code request."""

    for prompt, tty_prompt in _CODE_PROMPTS:
        prompt_count = output.count(prompt)
        while handled_prompts[prompt] < prompt_count:
            try:
                code = prompt_for_code(tty_prompt)
            except BitwardenPromptUnavailableError:
                _terminate(process)
                return BitwardenLoginResult(failure_reason="code_required")
            except BitwardenPromptCancelledError as error:
                _terminate(process)
                raise ValueError("Bitwarden verification code entry was cancelled.") from error
            os.write(master_fd, code.encode() + b"\n")
            handled_prompts[prompt] += 1
    return None


def _drain_master(master_fd: int, output: bytearray) -> None:
    """Collect remaining child output after the process exits."""

    while True:
        ready, _, _ = select.select([master_fd], [], [], 0)
        if master_fd not in ready:
            return
        chunk = _read_master(master_fd)
        if not chunk:
            return
        output.extend(chunk)


def _read_master(master_fd: int) -> bytes:
    """Read one chunk from the Bitwarden pseudo-terminal."""

    try:
        return os.read(master_fd, 4096)
    except OSError:
        return b""


def _normalize_output(raw_output: bytes) -> str:
    """Decode terminal output into stable plain text for prompt and error matching."""

    text = raw_output.decode(errors="replace").replace("\r", "\n")
    return _ANSI_ESCAPE_RE.sub("", text)


def _prompt_for_hidden_code(prompt: str) -> str:
    """Read a non-empty verification code from the controlling terminal without echo."""

    try:
        with Path("/dev/tty").open("r+", encoding="utf-8", buffering=1) as tty:
            while True:
                tty.write(prompt)
                tty.flush()
                tty_fd = tty.fileno()
                original = termios.tcgetattr(tty_fd)
                hidden = termios.tcgetattr(tty_fd)
                hidden[3] &= ~termios.ECHO
                termios.tcsetattr(tty_fd, termios.TCSANOW, hidden)
                try:
                    value = tty.readline()
                except KeyboardInterrupt as error:
                    raise BitwardenPromptCancelledError("Bitwarden verification code entry was cancelled.") from error
                finally:
                    termios.tcsetattr(tty_fd, termios.TCSANOW, original)
                    tty.write("\n")
                    tty.flush()
                if value == "":
                    raise BitwardenPromptCancelledError("Bitwarden verification code entry reached EOF.")
                value = value.strip()
                if value:
                    return value
    except OSError as error:
        raise BitwardenPromptUnavailableError("Interactive Bitwarden verification needs a terminal.") from error


def _write_notice(message: str) -> None:
    """Best-effort safe notice for retryable verification failures."""

    try:
        with Path("/dev/tty").open("w", encoding="utf-8", buffering=1) as tty:
            tty.write(message)
    except OSError:
        pass


def _terminate(process: subprocess.Popen[bytes]) -> None:
    """Stop the child process before abandoning the current login attempt."""

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
