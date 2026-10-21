"""Protect persistent AI login reuse, interactive sign-in, previews and private errors."""

import io
import json
import subprocess
from pathlib import Path

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils import ai_auth


@pytest.fixture(name="authentication")
def provider_authentication(tmp_path, monkeypatch):
    """Emulate both native clients without credentials, network or desktop changes."""
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-inherited-secret")
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "synthetic-inherited-secret")
    monkeypatch.setenv("GH_TOKEN", "synthetic-inherited-secret")
    monkeypatch.setenv("WORKSTATION_MANAGER_GHCR_TOKEN", "synthetic-registry-secret")
    monkeypatch.setenv("CODEX_HOME", "/other/user")
    monkeypatch.setenv("COPILOT_HOME", "/other/user")
    state = {"authenticated": True, "calls": [], "login": "fixture", "host": "https://github.com"}

    def run(argv, **options):
        state["calls"].append(argv)
        environment = options["env"]
        assert environment["HOME"] == str(tmp_path)
        assert environment["CODEX_HOME"] == str(tmp_path / ".codex")
        assert environment["COPILOT_HOME"] == str(tmp_path / ".copilot")
        assert (
            not {"OPENAI_API_KEY", "COPILOT_GITHUB_TOKEN", "GH_TOKEN", "WORKSTATION_MANAGER_GHCR_TOKEN"}
            & environment.keys()
        )
        assert options["cwd"] == tmp_path
        if argv[1:] == ["login", "status"]:
            return subprocess.CompletedProcess(
                argv,
                0 if state["authenticated"] else 1,
                b"",
                b"Logged in using ChatGPT" if state["authenticated"] else b"Not logged in",
            )
        if argv[1] == "--headless":
            assert b'"auth.getStatus"' in options["input"]
            assert "--no-auto-update" in argv
            result = {"isAuthenticated": state["authenticated"], "login": state["login"], "host": state["host"]}
            content = json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}).encode()
            return subprocess.CompletedProcess(
                argv, 0, f"Content-Length: {len(content)}\r\n\r\n".encode() + content, b""
            )
        assert argv[1] == "login"
        assert options["stdin"] is options["stdout"] is options["stderr"]
        assert options["stdin"].isatty()
        state["login_environment"] = dict(environment)
        state["authenticated"] = not state.get("reject_login", False)
        return subprocess.CompletedProcess(argv, 1 if state.get("login_failure") else 0, None, None)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(ai_auth.DesktopSession, "environment", lambda: {})
    return tmp_path, state


def client(authentication, provider):
    """Select the native client for the isolated user."""
    home = authentication[0]
    return ai_auth.AiProviderAuthentication(
        home, provider, f"/installed/{provider}", host="github.com", account="fixture"
    )


@pytest.mark.parametrize("provider", ["codex", "copilot"])
def test_existing_native_login_needs_no_authentication(authentication, provider):
    """Stored credentials are checked without inherited tokens or model requests."""
    assert client(authentication, provider).ensure() == {"changed": False, "authenticated": True, "deferred": False}
    assert len(authentication[1]["calls"]) == 1


@pytest.mark.parametrize("provider", ["codex", "copilot"])
def test_missing_login_fails_unattended_setup_with_actionable_instructions(authentication, provider):
    """Unattended setup cannot claim success or start an unseen sign-in flow."""
    authentication[1]["authenticated"] = False
    with pytest.raises(ValueError, match=f"run {provider} login"):
        client(authentication, provider).ensure()
    assert len(authentication[1]["calls"]) == 1


@pytest.mark.parametrize("provider", ["codex", "copilot"])
def test_preview_never_starts_a_provider(authentication, provider):
    """Check mode neither reads native caches through clients nor starts login."""
    assert client(authentication, provider).ensure(check_mode=True)["deferred"]
    assert authentication[1]["calls"] == []


class LoginTerminal(io.StringIO):
    """Supply a synthetic terminal only to the mocked native login process."""

    def isatty(self):
        """Model the real terminal required by interactive authentication."""
        return True


@pytest.mark.parametrize("provider", ["codex", "copilot"])
def test_interactive_login_uses_the_terminal_then_rechecks_status(authentication, provider, monkeypatch):
    """Login codes bypass captured output; success requires a fresh status check."""
    state = authentication[1]
    state["authenticated"] = False
    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: LoginTerminal())
    assert client(authentication, provider).ensure(terminal="/dev/pts/fixture")["changed"]
    assert len(state["calls"]) == 3
    assert state["calls"][1] == [f"/installed/{provider}", "login"] + (
        ["--host", "https://github.com"] if provider == "copilot" else []
    )
    assert not client(authentication, provider).ensure()["changed"]


@pytest.mark.parametrize("provider", ["codex", "copilot"])
def test_interactive_login_passes_the_live_desktop_to_open_the_browser(authentication, provider, monkeypatch):
    """Native sign-in receives the managed user's display so it opens the system browser, not an editor."""
    state = authentication[1]
    state["authenticated"] = False
    monkeypatch.setattr(
        ai_auth.DesktopSession,
        "environment",
        lambda: {"DISPLAY": ":5", "WAYLAND_DISPLAY": "wayland-5", "XDG_CURRENT_DESKTOP": "ubuntu:GNOME"},
    )
    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: LoginTerminal())
    assert client(authentication, provider).ensure(terminal="/dev/pts/fixture")["changed"]
    assert state["login_environment"]["DISPLAY"] == ":5"
    assert state["login_environment"]["WAYLAND_DISPLAY"] == "wayland-5"
    assert state["login_environment"]["XDG_CURRENT_DESKTOP"] == "ubuntu:GNOME"


@pytest.mark.parametrize("failure", ["reject_login", "login_failure"])
def test_native_login_failure_never_reports_success(authentication, monkeypatch, failure):
    """Both rejected login and unpersisted credentials fail the transaction."""
    state = authentication[1]
    state.update(authenticated=False, **{failure: True})
    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: LoginTerminal())
    with pytest.raises(ValueError, match="sign-in|login is still missing"):
        client(authentication, "codex").ensure(terminal="/dev/pts/fixture")


@pytest.mark.parametrize("identity", [{"login": "different"}, {"host": "other.example.test"}])
def test_copilot_requires_the_configured_github_identity(authentication, identity):
    """An unrelated stored account must not silently replace the managed GitHub identity."""
    authentication[1].update(identity)
    with pytest.raises(ValueError, match="configured GitHub account"):
        client(authentication, "copilot").ensure()


@pytest.mark.parametrize("output", [b"synthetic-private-secret", b"Content-Length: synthetic-private-secret\r\n\r\n{}"])
def test_malformed_native_status_is_redacted(tmp_path, monkeypatch, output):
    """Private CLI errors never become public authentication failure text."""
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, output, b""))
    with pytest.raises(ValueError, match="invalid authentication status") as error:
        ai_auth.AiProviderAuthentication(Path(tmp_path), "copilot", "/installed/copilot").ensure()
    assert "synthetic-private-secret" not in str(error.value)


def test_invalid_copilot_hostname_never_exposes_the_response(authentication):
    """Invalid server identity syntax is a private protocol failure."""
    authentication[1]["host"] = "https://[synthetic-private-secret]"
    with pytest.raises(ValueError, match="invalid authentication status") as error:
        client(authentication, "copilot").ensure()
    assert "synthetic-private-secret" not in str(error.value)


def test_unexpected_codex_failure_does_not_trigger_login(authentication, monkeypatch):
    """Configuration errors stop setup without replacing an existing account."""
    monkeypatch.setattr(
        subprocess, "run", lambda *_args, **_kwargs: subprocess.CompletedProcess([], 2, b"", b"synthetic-secret")
    )
    with pytest.raises(ValueError, match="Cannot check Codex login") as error:
        client(authentication, "codex").ensure()
    assert "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize(
    "status", [b"Logged in using an API key - synthetic-private-secret", b"synthetic-private-secret"]
)
def test_codex_requires_chatgpt_login_without_exposing_or_replacing_other_credentials(
    authentication, monkeypatch, status
):
    """Only a reported ChatGPT session satisfies setup; an API key cannot silently change billing."""
    calls = []

    def run(argv, **_options):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", status)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ValueError, match="ChatGPT sign-in") as error:
        client(authentication, "codex").ensure(terminal="/dev/pts/fixture")
    assert "synthetic-private-secret" not in str(error.value)
    assert calls == [["/installed/codex", "login", "status"]]


def test_login_refuses_a_non_terminal(authentication, monkeypatch):
    """Login must never write authentication codes to an ordinary file."""
    authentication[1]["authenticated"] = False
    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: io.StringIO())
    with pytest.raises(ValueError, match="interactive terminal"):
        client(authentication, "codex").ensure(terminal="/fixture/file")
    assert len(authentication[1]["calls"]) == 1
