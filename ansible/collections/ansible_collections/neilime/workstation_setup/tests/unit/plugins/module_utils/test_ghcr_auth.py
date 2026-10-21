"""Protect registry credential storage, configuration preservation, and read-only previews."""

import json
import stat
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.ghcr_auth import (
    GhcrAuthentication,
)

TOKEN = "synthetic-registry-secret"


@pytest.fixture(name="registry")
def registry_fixture(tmp_path, monkeypatch):
    """Model Docker and Secret Service without contacting a registry or the real keyring."""
    monkeypatch.setenv("DOCKER_CONFIG", "/other/docker")
    monkeypatch.setenv("DOCKER_AUTH_CONFIG", "inherited-secret")
    auth = GhcrAuthentication(tmp_path, "fixture")
    auth.github = Mock()
    auth.github.ensure.return_value = {"changed": False, "authenticated": True}
    auth.github.read_token.return_value = TOKEN
    state = {"credential": {}, "calls": [], "failure": False, "save": True}

    def run(command, **options):
        assert not any(key.startswith("DOCKER_") for key in options["env"])
        assert "GH_TOKEN" not in options["env"]
        assert TOKEN not in command
        state["calls"].append(command)
        if command[0] == "/usr/bin/docker":
            config = Path(command[2]) / "config.json"
            assert json.loads(config.read_text()) == {"credHelpers": {"ghcr.io": "secretservice"}}
            assert stat.S_IMODE(config.stat().st_mode) == 0o600
            assert options["input"] == TOKEN and command[-1] == "--password-stdin"
            if state["failure"]:
                return subprocess.CompletedProcess(command, 1, TOKEN, TOKEN)
            if state["save"]:
                state["credential"] = {"Username": "fixture", "Secret": TOKEN}
        else:
            assert command == ["/usr/local/bin/docker-credential-secretservice", "get"]
            assert options["input"] == "ghcr.io\n"
            if not state["credential"]:
                return subprocess.CompletedProcess(command, 1, "credentials not found in native keychain", "")
        return subprocess.CompletedProcess(command, 0, json.dumps(state["credential"]), "")

    monkeypatch.setattr(subprocess, "run", run)
    return auth, state


def test_verified_login_preserves_other_registries_and_is_idempotent(registry):
    """Only GHCR inline credentials are replaced, after the keyring login is verified."""
    auth, state = registry
    original = {
        "auths": {"https://ghcr.io/v1/": {"auth": "old"}, "registry.example.test": {"auth": "preserved"}},
        "credHelpers": {"registry.example.test": "pass"},
        "currentContext": "desktop-linux",
        "credsStore": "pass",
    }
    auth.path.parent.mkdir()
    auth.path.write_text(json.dumps(original))
    assert auth.ensure() == {"changed": True, "authenticated": True, "account": "fixture"}
    saved = json.loads(auth.path.read_text())
    assert saved == {
        **original,
        "auths": {"registry.example.test": {"auth": "preserved"}},
        "credHelpers": {"registry.example.test": "pass", "ghcr.io": "secretservice"},
    }
    assert stat.S_IMODE(auth.path.stat().st_mode) == 0o600
    assert TOKEN not in auth.path.read_text()
    auth.github.ensure.assert_called_with(terminal="", check_mode=False, scopes=("write:packages",))
    assert not auth.ensure()["changed"]
    assert len([command for command in state["calls"] if command[0] == "/usr/bin/docker"]) == 2
    assert not any(Path(command[2]).exists() for command in state["calls"] if command[0] == "/usr/bin/docker")


def test_rotated_github_token_replaces_stale_docker_credential(registry):
    """Rerunning setup synchronizes a new GitHub token even when Docker configuration is correct."""
    auth, state = registry
    auth.ensure()
    state["credential"]["Secret"] = "stale-token"
    assert auth.ensure()["changed"]
    assert state["credential"]["Secret"] == TOKEN


@pytest.mark.parametrize("failure", ["registry", "storage"])
def test_failed_login_preserves_configuration_and_redacts_credentials(registry, failure):
    """A registry rejection or failed keyring write cannot discard recoverable Docker configuration."""
    auth, state = registry
    auth.path.parent.mkdir()
    original = '{"auths": {"ghcr.io": {"auth": "recoverable"}}}\n'
    auth.path.write_text(original)
    state.update(failure=failure == "registry", save=failure != "storage")
    with pytest.raises(ValueError, match="Docker login") as error:
        auth.ensure()
    assert TOKEN not in str(error.value)
    assert auth.path.read_text() == original


def test_preview_reads_credentials_without_logging_in_or_writing_config(registry):
    """Check mode may inspect stored credentials but cannot authorize or mutate Docker state."""
    auth, state = registry
    assert auth.ensure(check_mode=True) == {"changed": True, "authenticated": False, "account": "fixture"}
    assert not auth.path.parent.exists()
    assert all(command[-1] == "get" for command in state["calls"])
    auth.github.ensure.return_value = {"changed": True, "authenticated": False}
    state["calls"].clear()
    assert not auth.ensure(check_mode=True)["authenticated"]
    assert not state["calls"]


@pytest.mark.parametrize("content", ["[]", '{"auths": []}', '{"credHelpers": {"ghcr.io": 3}}', '{"x":1,"x":2}', TOKEN])
def test_invalid_docker_configuration_fails_before_authentication(registry, content):
    """Invalid configuration cannot be overwritten or echoed in failure output."""
    auth, state = registry
    auth.path.parent.mkdir()
    auth.path.write_text(content)
    with pytest.raises(ValueError) as error:
        auth.ensure()
    assert TOKEN not in str(error.value)
    assert auth.path.read_text() == content
    auth.github.ensure.assert_not_called()
    assert not state["calls"]


def test_symlinked_docker_configuration_is_preserved(registry, tmp_path):
    """Credential management refuses indirect paths that may expose or overwrite other files."""
    auth, _state = registry
    target = tmp_path / "shared.json"
    target.write_text("{}")
    auth.path.parent.mkdir()
    auth.path.symlink_to(target)
    with pytest.raises(ValueError, match="symlinked"):
        auth.ensure()
    assert target.read_text() == "{}" and auth.path.is_symlink()


def test_keyring_failures_are_not_treated_as_missing_credentials(registry, monkeypatch):
    """Locked or malformed keyring responses stop before changing configuration."""
    auth, _state = registry
    for result, message in (
        (subprocess.CompletedProcess([], 1, TOKEN, TOKEN), "unlock the desktop keyring"),
        (subprocess.CompletedProcess([], 0, TOKEN, ""), "invalid response"),
    ):
        monkeypatch.setattr(subprocess, "run", Mock(return_value=result))
        with pytest.raises(ValueError, match=message) as error:
            auth.ensure()
        assert TOKEN not in str(error.value)
        assert not auth.path.exists()
