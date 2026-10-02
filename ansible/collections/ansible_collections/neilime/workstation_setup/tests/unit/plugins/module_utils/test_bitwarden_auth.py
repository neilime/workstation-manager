"""Unit tests for Bitwarden email/password authentication helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    bitwarden_auth,
)


def _write_fake_bw(path: Path, scenario: str) -> None:
    """Create a small fake Bitwarden CLI that matches the helper's prompt handling."""

    path.write_text(
        f"""#!{sys.executable}
import os
import pathlib
import sys

root = pathlib.Path(os.environ["HOME"])
attempt_file = root / "attempt.txt"
attempt = int(attempt_file.read_text()) + 1 if attempt_file.exists() else 1
attempt_file.write_text(str(attempt))
scenario = {scenario!r}
password = os.environ["BITWARDEN_PASSWORD"]

if sys.argv[1:] == ["login", "fixture@example.com", "--passwordenv", "BITWARDEN_PASSWORD", "--method", "1", "--raw"]:
    if password != "fixture-password":
        print(
            "Invalid master password. Confirm your email is correct and your account was created on "
            "vault.example.invalid."
        )
        sys.exit(1)
    if scenario == "success":
        print("fixture-login-session")
        sys.exit(0)
    if scenario == "email-code":
        if not sys.stdin.isatty():
            print("Code is required.")
            sys.exit(1)
        print("Two-step login code:", end="", flush=True)
        code = sys.stdin.readline().strip()
        if code != "123456":
            print("\\nInvalid verification code.")
            sys.exit(1)
        print("\\nfixture-login-session")
        sys.exit(0)
    if scenario == "two-codes":
        if not sys.stdin.isatty():
            print("Code is required.")
            sys.exit(1)
        print("Two-step login code:", end="", flush=True)
        first = sys.stdin.readline().strip()
        if first != "123456":
            print("\\nInvalid verification code.")
            sys.exit(1)
        print("\\nNew device verification required. Enter OTP sent to login email:", end="", flush=True)
        second = sys.stdin.readline().strip()
        if second != "654321":
            print("\\nInvalid email or verification code")
            sys.exit(1)
        print("\\nfixture-login-session")
        sys.exit(0)
    print("Code is required.")
    sys.exit(1)

print("unexpected arguments", sys.argv[1:])
sys.exit(99)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _fixture_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str) -> None:
    """Install the fake bw script on PATH with an isolated HOME directory."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_bw(bin_dir / "bw", scenario)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")


def test_login_returns_session_without_verification_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A normal email/password login should return the raw Bitwarden session token."""

    _fixture_environment(tmp_path, monkeypatch, "success")

    result = bitwarden_auth.login_with_email_password(
        "fixture@example.com",
        "fixture-password",
        interactive=False,
    )

    assert result == bitwarden_auth.BitwardenLoginResult(session="fixture-login-session")


def test_login_retries_after_rejected_verification_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A bad emailed verification code should retry the full login and request a fresh code."""

    _fixture_environment(tmp_path, monkeypatch, "email-code")
    prompts: list[str] = []
    notices: list[str] = []
    answers = iter(["bad-code", "123456"])

    def prompt_code(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers)

    result = bitwarden_auth.login_with_email_password(
        "fixture@example.com",
        "fixture-password",
        interactive=True,
        prompt_for_code=prompt_code,
        notice=notices.append,
    )

    assert result == bitwarden_auth.BitwardenLoginResult(session="fixture-login-session")
    assert prompts == [
        "Bitwarden emailed a two-step login code: ",
        "Bitwarden emailed a two-step login code: ",
    ]
    assert notices == [
        "Bitwarden rejected the supplied verification code; request the latest email code and try again.\n"
    ]
    assert (tmp_path / "attempt.txt").read_text() == "2"


def test_login_handles_two_distinct_emailed_codes_in_one_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new-device email challenge may follow the two-step email challenge in the same login."""

    _fixture_environment(tmp_path, monkeypatch, "two-codes")
    prompts: list[str] = []
    answers = iter(["123456", "654321"])

    def prompt_code(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers)

    result = bitwarden_auth.login_with_email_password(
        "fixture@example.com",
        "fixture-password",
        interactive=True,
        prompt_for_code=prompt_code,
        notice=lambda _message: None,
    )

    assert result == bitwarden_auth.BitwardenLoginResult(session="fixture-login-session")
    assert prompts == [
        "Bitwarden emailed a two-step login code: ",
        "Bitwarden emailed a new-device verification code: ",
    ]
    assert (tmp_path / "attempt.txt").read_text() == "1"


def test_login_reports_email_password_rejection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid email/password combinations must keep the existing retry marker behavior."""

    _fixture_environment(tmp_path, monkeypatch, "success")

    result = bitwarden_auth.login_with_email_password(
        "fixture@example.com",
        "wrong-password",
        interactive=False,
    )

    assert result == bitwarden_auth.BitwardenLoginResult(failure_reason="email_password_rejected")


def test_login_requires_interactive_code_prompt_when_noninteractive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Noninteractive runs should fail clearly when Bitwarden needs an emailed code."""

    _fixture_environment(tmp_path, monkeypatch, "email-code")

    result = bitwarden_auth.login_with_email_password(
        "fixture@example.com",
        "fixture-password",
        interactive=False,
    )

    assert result == bitwarden_auth.BitwardenLoginResult(failure_reason="code_required")
