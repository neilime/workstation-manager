"""Check persistent credentials, private failures, and read-only previews without network access."""

import json
import subprocess

import pytest
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
        elif command[1:3] == ["auth", "token"]:
            output = "stored-secret"
        elif command[1:3] == ["auth", "login"]:
            assert options["input"] in ("supplied-secret", "stored-secret")
            state["login"] = {
                "state": "success",
                "active": True,
                "login": state.get("new_account", "fixture"),
                "tokenSource": "keyring",
            }
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
    assert auth.ensure(token="" if existing else "supplied-secret")["authenticated"]
    assert any(command[1:3] == ["auth", "login"] for command in state["calls"])
    assert not any("secret" in part for command in state["calls"] for part in command if part != "secret-tool")
    assert not auth.ensure()["changed"]


def test_locked_keyring_stops_before_gh_can_write_plaintext(authentication):
    """A temporary automation token must not become a plaintext permanent credential."""
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


def test_missing_noninteractive_login_is_actionable(authentication):
    """Unattended setup cannot claim authentication it did not establish."""
    auth, state = authentication
    state["login"] = {}
    with pytest.raises(ValueError, match="unlocked GNOME terminal"):
        auth.ensure()


def test_blank_account_is_rejected_before_credential_access(authentication):
    """Calling the authentication module directly cannot bypass the account requirement."""
    auth, state = authentication
    with pytest.raises(ValueError, match="account is required"):
        GitHubAuthentication(auth.home, auth.host, " \t")
    assert state["calls"] == []


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
