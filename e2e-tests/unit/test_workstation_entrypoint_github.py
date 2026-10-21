"""Verify GitHub-first bootstrap order without touching accounts or the workstation."""

import base64
import json
import os
import subprocess

import pytest
from entrypoint_test_helpers import entrypoint_source_with_mock_controller


@pytest.mark.parametrize(
    "access,preview",
    [
        ("interactive", False),
        ("interactive", True),
        ("ci", False),
        ("auth-failed", False),
        ("token-unavailable", False),
        ("denied", False),
    ],
)
def test_github_login_precedes_private_configuration_and_bitwarden(tmp_path, access, preview):
    """Authorize GitHub first, fetch configuration once, then collect vault credentials and run setup."""
    definitions = entrypoint_source_with_mock_controller().rsplit('main "$@"', 1)[0]
    script = r"""
initialize_target_context() {
    TARGET_USER="$(id -un)"
    TARGET_USER_HOME="$HOME"
    COLLECTIONS_INSTALL_DIR="$HOME/.ansible/collections"
}
require_sudo() { :; }
install_git() { :; }
install_ansible_packages() { :; }
install_collection_requirements() { :; }
has_interactive_terminal() { [ "$TEST_ACCESS" != ci ]; }
sudo() {
    [ "$1" = -u ] && [ "$2" = "$TARGET_USER" ] || exit 81
    printf 'token-read\n' >>"$TEST_AUDIT"
    [ "$TEST_ACCESS" != token-unavailable ] || return 1
    printf '%s' synthetic-saved-token
}
prompt_for_required_value() {
    case "$1" in
    BITWARDEN_EMAIL)
        printf 'bitwarden-email\n' >>"$TEST_AUDIT"
        printf fixture@example.test ;;
    BITWARDEN_PASSWORD)
        printf 'bitwarden-password\n' >>"$TEST_AUDIT"
        printf synthetic-vault-password ;;
    *) exit 82 ;;
    esac
}
run_ansible_pull_with_bitwarden_retry() {
    case "$1" in
    ansible/github_bootstrap.yml)
        [ "$2" = 0 ] || exit 83
        [ -z "$PROMPTED_BITWARDEN_EMAIL" ] || exit 84
        printf 'github-auth\n' >>"$TEST_AUDIT"
        [ "$TEST_ACCESS" != auth-failed ] || return 1 ;;
    ansible/setup.yml)
        [ "$2" = "$TEST_PREVIEW" ] || exit 85
        [ "$GITHUB_TOKEN_VALUE" = synthetic-saved-token ] || exit 86
        [ -n "$BITWARDEN_PASSWORD_VALUE" ] || exit 87
        [ -f "$PRIVATE_OVERRIDE_LOCAL_FILE" ] || exit 88
        printf 'setup\n' >>"$TEST_AUDIT" ;;
    *) exit 89 ;;
    esac
}
clone_private_override_repository() {
    [ "$1" = "$PRIVATE_OVERRIDE_REPOSITORY_URL" ] || exit 90
    printf 'clone\n' >>"$TEST_AUDIT"
    [ "$TEST_ACCESS" != denied ] || return 1
    mkdir -p "$2/ansible"
    printf '{}\n' >"$2/ansible/private.override.yml"
}
main setup "$@"
"""
    audit = tmp_path / "calls"
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "TEST_AUDIT": str(audit),
        "TEST_ACCESS": access,
        "TEST_PREVIEW": str(int(preview)),
    }
    if access == "ci":
        environment.update(
            BITWARDEN_CLIENT_ID="fixture-client",
            BITWARDEN_CLIENT_SECRET="fixture-secret",
            BITWARDEN_PASSWORD="synthetic-vault-password",
            WORKSTATION_MANAGER_GITHUB_TOKEN="synthetic-ci-token",
        )
    result = subprocess.run(
        ["/bin/sh", "-s", "--", *(["--dry-run"] if preview else [])],
        input=definitions + script,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert "synthetic" not in result.stdout + result.stderr
    calls = audit.read_text().splitlines()
    expected = ["github-auth"]
    if access != "auth-failed":
        expected += ["token-read"]
        if access != "token-unavailable":
            expected += ["clone"]
            if access != "denied":
                if access != "ci":
                    expected += ["bitwarden-email", "bitwarden-password"]
                expected += ["setup"]
    assert calls == expected
    assert result.returncode == 0 if access in {"interactive", "ci"} else result.returncode != 0
    assert not list(tmp_path.glob("workstation-manager-private-override-*"))


def test_private_clone_passes_credentials_to_git_without_putting_them_in_the_url(tmp_path):
    """Git receives a scoped HTTP credential through its environment while clone arguments stay safe to log."""
    definitions = entrypoint_source_with_mock_controller().rsplit('main "$@"', 1)[0]
    binary = tmp_path / "git"
    binary.write_text(
        '#!/bin/sh\n[ "$GIT_CONFIG_COUNT" = 1 ] || exit 91\n'
        'printf "%s\\n" "$GIT_CONFIG_KEY_0" "$GIT_CONFIG_VALUE_0" "$@" >"$TEST_INVOCATION"\n'
    )
    binary.chmod(0o700)
    invocation = tmp_path / "invocation"
    token = "synthetic-token'with $shell text"
    result = subprocess.run(
        ["sh", "-s"],
        input=definitions
        + '\nclone_private_override_repository "$PRIVATE_OVERRIDE_REPOSITORY_URL" "$HOME/repository"\n',
        env={
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "WORKSTATION_MANAGER_GITHUB_TOKEN": token,
            "TEST_INVOCATION": str(invocation),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    key, header, *arguments = invocation.read_text().splitlines()
    assert key == "http.https://github.com/.extraheader"
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    assert header == f"Authorization: Basic {encoded}"
    assert token not in json.dumps(arguments) + result.stdout + result.stderr
    assert encoded not in json.dumps(arguments) + result.stdout + result.stderr


def test_each_setup_downloads_the_latest_published_private_override(tmp_path):
    """Separate setup invocations read fresh remote configuration and remove temporary checkouts."""
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "WORKSTATION_MANAGER_GITHUB_TOKEN": "synthetic-private-config-token",
    }

    def git(*arguments):
        return subprocess.run(
            [
                "git",
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.test",
                "-c",
                "commit.gpgsign=false",
                *arguments,
            ],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )

    source = tmp_path / "published"
    git("init", "--initial-branch=main", str(source))
    (source / "ansible").mkdir()
    override = source / "ansible/private.override.yml"
    override.write_text("fixture_revision: initial\n")
    git("-C", str(source), "add", ".")
    git("-C", str(source), "commit", "-m", "Initial private configuration")
    remote = tmp_path / "remote.git"
    git("clone", "--bare", str(source), str(remote))
    environment["TEST_REMOTE"] = remote.as_uri()
    definitions = entrypoint_source_with_mock_controller().rsplit('main "$@"', 1)[0]
    for revision in ("initial", "updated"):
        if revision == "updated":
            override.write_text("fixture_revision: updated\n")
            git("-C", str(source), "commit", "-am", "Publish updated private configuration")
            git("-C", str(source), "push", str(remote), "main")
        result = subprocess.run(
            ["sh", "-s"],
            input=definitions
            + '\nPRIVATE_OVERRIDE_REPOSITORY_URL="$TEST_REMOTE"\n'
            + 'prepare_private_override_file\ncat "$PRIVATE_OVERRIDE_LOCAL_FILE"\n',
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"fixture_revision: {revision}" in result.stdout
        assert "synthetic-private-config-token" not in result.stdout + result.stderr
        assert not list(tmp_path.glob("workstation-manager-private-override-*"))
