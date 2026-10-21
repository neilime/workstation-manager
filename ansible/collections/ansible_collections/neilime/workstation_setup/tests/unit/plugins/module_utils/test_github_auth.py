"""Check persistent credentials, private failures, and read-only previews without network access."""

import json
import subprocess
from unittest.mock import mock_open

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    github_auth,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.github_auth import (
    GitHubAuthentication,
)


@pytest.fixture(name="authentication")
def authentication_fixture(tmp_path, monkeypatch):
    """Model gh and Secret Service at the subprocess boundary."""
    state = {
        "login": {"state": "success", "active": True, "login": "fixture", "tokenSource": "keyring"},
        "helper": "!/usr/bin/gh auth git-credential",
        "probe": "",
        "calls": [],
        "keyring": True,
    }
    monkeypatch.setenv("GH_TOKEN", "inherited-secret")
    monkeypatch.setenv("GH_CONFIG_DIR", "/other/account")

    def run(command, **options):
        state["calls"].append(command)
        environment = options["env"]
        assert "GH_TOKEN" not in environment
        assert environment["GH_CONFIG_DIR"] == str(tmp_path / ".config/gh")
        output, status = "", 0
        if command[1:3] == ["auth", "status"]:
            output = json.dumps({"hosts": {"github.com": [state["login"]] if state["login"] else []}})
        elif command[1:3] in (["auth", "login"], ["auth", "refresh"]):
            if "--with-token" in command:
                assert options["input"] == "supplied-secret"
            else:
                assert "--web" in command or command[2] == "refresh"
                assert options["stdin"].isatty()
                assert options["stdin"] is options["stdout"] is options["stderr"]
                assert "GH_PROMPT_DISABLED" not in environment
                assert "input" not in options
                state["login_environment"] = dict(environment)
            state["login"] = {
                "state": "success",
                "active": True,
                "login": state.get("new_account", "fixture"),
                "tokenSource": state.get("new_storage", "keyring"),
                "scopes": state.get("new_scopes", "repo, write:packages"),
            }
            status = state.get("login_status", 0)
        elif command[1:3] == ["auth", "token"]:
            output = "stored-secret"
            status = state.get("token_status", 0)
        elif command[0] == "secret-tool":
            if command[1] == "store":
                state["probe"] = options["input"]
                status = 0 if state["keyring"] else 1
            elif command[1] == "lookup":
                output = state["probe"]
        elif command[1:4] == ["config", "--global", "--get-all"]:
            output = state["helper"]
        elif command[1:3] == ["auth", "setup-git"]:
            state["helper"] = "!/usr/bin/gh auth git-credential"
        return subprocess.CompletedProcess(command, status, output, "private-failure-secret" if status else "")

    monkeypatch.setattr(subprocess, "run", run)
    return GitHubAuthentication(tmp_path, "github.com", "fixture"), state


def test_stored_login_survives_token_overrides_and_needs_no_reauthentication(authentication):
    """A valid keyring login and existing helper are reused without credential writes."""
    auth, state = authentication
    assert auth.ensure() == {
        "changed": False,
        "authenticated": True,
        "account": "fixture",
    }
    assert not any(command[0] == "secret-tool" or command[1:3] == ["auth", "login"] for command in state["calls"])


@pytest.mark.parametrize("existing", [False, True])
def test_missing_or_plaintext_credentials_are_saved_in_the_keyring(authentication, existing):
    """Tokens travel on stdin only after a successful credential-store write/read probe."""
    auth, state = authentication
    state["login"] = dict(state["login"], tokenSource="/home/fixture/.config/gh/hosts.yml") if existing else {}
    state["helper"] = ""
    assert auth.ensure(token="supplied-secret")["authenticated"]
    assert any(command[1:3] == ["auth", "login"] for command in state["calls"])
    assert not any("secret" in part for command in state["calls"] for part in command if part != "secret-tool")
    assert not auth.ensure()["changed"]


def test_locked_keyring_stops_before_gh_can_write_plaintext(authentication):
    """A supplied token must not become a plaintext permanent credential."""
    auth, state = authentication
    state.update(login={}, keyring=False)
    with pytest.raises(ValueError, match="Unlock the GNOME credential store") as error:
        auth.ensure(token="supplied-secret")
    assert "private-failure-secret" not in str(error.value)
    assert not any(command[1:3] == ["auth", "login"] for command in state["calls"])


def test_preview_does_not_log_in_or_modify_credentials(authentication):
    """Check mode records missing persistent login without probing or writing secrets."""
    auth, state = authentication
    state["login"] = {}
    result = auth.ensure(token="supplied-secret", check_mode=True)
    assert result["changed"] and not result["authenticated"]
    assert len(state["calls"]) == 1


def test_package_permissions_are_added_to_the_existing_keyring_login(authentication, monkeypatch):
    """Native refresh adds package access and subsequent runs reuse the authorized account."""
    auth, state = authentication
    state["login"]["scopes"] = "repo"
    terminal = mock_open()
    terminal.return_value.isatty.return_value = True
    monkeypatch.setattr("builtins.open", terminal)
    monkeypatch.setattr(github_auth.DesktopSession, "environment", dict)
    assert auth.ensure(terminal="/dev/fixture", scopes=("write:packages",))["changed"]
    assert not auth.ensure(scopes=("write:packages",))["changed"]
    refresh = [command for command in state["calls"] if command[1:3] == ["auth", "refresh"]]
    assert len(refresh) == 1 and refresh[0][-2:] == ["--scopes", "write:packages"]


def test_missing_package_scope_is_read_only_in_preview_and_actionable_unattended(authentication):
    """A preview cannot authorize new scopes and unattended setup explains the required authorization."""
    auth, state = authentication
    result = auth.ensure(check_mode=True, scopes=("write:packages",))
    assert result["changed"] and not result["authenticated"]
    with pytest.raises(ValueError, match="gh auth refresh.*write:packages"):
        auth.ensure(scopes=("write:packages",))
    assert not any(command[0] == "secret-tool" or command[1:3] == ["auth", "refresh"] for command in state["calls"])


@pytest.mark.parametrize(
    "updates",
    [{"new_scopes": "repo"}, {"new_account": "other"}, {"new_storage": "hosts.yml"}, {"login_status": 1}],
)
def test_scope_refresh_requires_the_expected_account_secure_storage_and_permission(
    authentication, monkeypatch, updates
):
    """Unverified permission changes fail without leaking native client diagnostics."""
    auth, state = authentication
    state.update(updates)
    terminal = mock_open()
    terminal.return_value.isatty.return_value = True
    monkeypatch.setattr("builtins.open", terminal)
    monkeypatch.setattr(github_auth.DesktopSession, "environment", dict)
    with pytest.raises(ValueError, match="permission refresh was not verified") as error:
        auth.ensure(terminal="/dev/fixture", scopes=("write:packages",))
    assert "private-failure-secret" not in str(error.value)


def test_token_access_selects_the_account_and_redacts_failures(authentication):
    """Registry clients receive only the explicit account's stored token."""
    auth, state = authentication
    assert auth.read_token() == "stored-secret"
    assert state["calls"][-1][-2:] == ["--user", "fixture"]
    state["token_status"] = 1
    with pytest.raises(ValueError, match="Cannot read") as error:
        auth.read_token()
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("existing", [False, True])
def test_unattended_login_requires_stored_credentials_or_a_token(authentication, existing):
    """Unattended runs cannot start browser prompts or reuse plaintext credentials."""
    auth, state = authentication
    state["login"] = dict(state["login"], tokenSource="hosts.yml") if existing else {}
    with pytest.raises(ValueError, match="GitHub sign-in is required"):
        auth.ensure()
    assert len(state["calls"]) == 1


def test_bootstrap_discovers_account_before_private_configuration(authentication):
    """Bootstrap can authenticate before the expected account is available from private configuration."""
    auth, state = authentication
    state["login"] = {}
    bootstrap = GitHubAuthentication(auth.home, auth.host)
    assert bootstrap.ensure(token="supplied-secret")["account"] == "fixture"


def test_interactive_login_uses_browser_authorization_once(authentication, monkeypatch):
    """Native sign-in uses the caller's terminal, the live desktop, and reuses the saved login."""
    auth, state = authentication
    state["login"] = {}
    monkeypatch.setattr(
        github_auth.DesktopSession,
        "environment",
        lambda: {
            "DISPLAY": ":9",
            "WAYLAND_DISPLAY": "wayland-9",
            "XDG_CURRENT_DESKTOP": "ubuntu:GNOME",
        },
    )
    terminal = mock_open()
    terminal.return_value.isatty.return_value = True
    monkeypatch.setattr("builtins.open", terminal)
    assert auth.ensure(terminal="/dev/fixture-terminal")["authenticated"]
    assert state["login_environment"]["DISPLAY"] == ":9"
    assert state["login_environment"]["WAYLAND_DISPLAY"] == "wayland-9"
    assert state["login_environment"]["XDG_CURRENT_DESKTOP"] == "ubuntu:GNOME"
    assert not auth.ensure()["changed"]
    assert sum(command[1:3] == ["auth", "login"] for command in state["calls"]) == 1


def test_interactive_login_proceeds_when_the_desktop_session_is_unavailable(authentication, monkeypatch):
    """A missing live session must not stop sign-in; gh still prints the URL for manual opening."""
    auth, state = authentication
    state["login"] = {}

    def unavailable() -> dict[str, str]:
        raise ValueError("Cannot read the managed user's desktop session environment; log in to GNOME and retry")

    monkeypatch.setattr(github_auth.DesktopSession, "environment", unavailable)
    terminal = mock_open()
    terminal.return_value.isatty.return_value = True
    monkeypatch.setattr("builtins.open", terminal)
    assert auth.ensure(terminal="/dev/fixture-terminal")["authenticated"]
    assert state["login_environment"] == {
        key: value for key, value in auth.environment.items() if key != "GH_PROMPT_DISABLED"
    }


@pytest.mark.parametrize("failure", ["login", "plaintext"])
def test_failed_or_insecure_login_cannot_complete_setup(authentication, failure):
    """A successful credential probe cannot hide a failed login or insecure saved result."""
    auth, state = authentication
    state.update(
        login={},
        login_status=1 if failure == "login" else 0,
        new_storage="hosts.yml" if failure == "plaintext" else "keyring",
    )
    with pytest.raises(ValueError, match="GitHub login") as error:
        auth.ensure(token="supplied-secret")
    assert "private-failure-secret" not in str(error.value)


def test_new_login_must_match_the_configured_account(authentication):
    """A valid token for another account must not complete setup or configure Git."""
    auth, state = authentication
    state.update(login={}, new_account="other", helper="")
    with pytest.raises(ValueError, match="different account"):
        auth.ensure(token="supplied-secret")
    assert not any(command[1:3] == ["auth", "setup-git"] for command in state["calls"])


@pytest.mark.parametrize(
    "status,message",
    [
        ({"state": "timeout", "active": True}, "network access"),
        ({"state": "success", "active": True, "login": "other"}, "configured GitHub account"),
    ],
)
def test_account_and_network_failures_have_distinct_diagnostics(authentication, status, message):
    """A wrong account or network outage must not trigger an unrelated login."""
    auth, state = authentication
    state["login"] = status
    with pytest.raises(ValueError, match=message):
        auth.ensure()


@pytest.mark.parametrize(
    "diagnostic,message",
    [
        ("unknown flag: --json", "update GitHub CLI"),
        ("unknown flag: --active", "update GitHub CLI"),
        ("error connecting to github.com", "check connectivity"),
    ],
)
def test_status_failures_report_safe_actionable_diagnostics(authentication, monkeypatch, diagnostic, message):
    """Unsupported CLI flags and connection failures stop without exposing stderr or starting login."""
    auth, state = authentication

    def run(command, **_options):
        state["calls"].append(command)
        return subprocess.CompletedProcess(command, 1, "", diagnostic + "\nprivate-failure-secret")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ValueError, match=message) as error:
        auth.ensure(token="supplied-secret")
    assert "private-failure-secret" not in str(error.value)
    assert len(state["calls"]) == 1
