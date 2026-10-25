"""Exercise fresh-VM backup preparation without a vault or workstation changes."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess

import pytest
from ansible.parsing.dataloader import DataLoader

WORKSPACE = pathlib.Path(__file__).parents[2]


@pytest.fixture(name="backup_environment")
def backup_environment_fixture(tmp_path: pathlib.Path) -> dict[str, str]:
    """Isolate the guest fixture while retaining real entrypoint credential handling."""

    scripts = tmp_path / "e2e-tests"
    scripts.mkdir()
    (scripts / "e2e-backup.sh").write_text((WORKSPACE / "e2e-tests/e2e-backup.sh").read_text())
    (scripts / "e2e-common.sh").write_text(
        (WORKSPACE / "e2e-tests/e2e-common.sh").read_text()
        + r"""
resolve_e2e_workstation_context() {
    E2E_REPOSITORY_PATH=fixture/workstation-manager
    E2E_REPOSITORY_URL=https://github.com/fixture/workstation-manager.git
    E2E_BRANCH_NAME=fixture-revision
}
resolve_e2e_target_user_home() { printf '%s\n' "$HOME"; }
run_e2e_vm_shell() {
    local command="${1//\/tmp\/workstation-manager-e2e-recovery/$TEST_FIXTURE/recovery}"
    case "$1" in
        *workstation-manager-e2e-recovery*) bash -c "$command" ;;
        *) : ;; # Project fixtures are unrelated to recovery preparation.
    esac
}
run_e2e_lima_control_command() {
    [[ "$1" == 20 ]]
    if [[ "$TEST_FINISH_STATUS" != 0 ]]; then return "$TEST_FINISH_STATUS"; fi
    run_e2e_vm_shell "${@: -1}"
}
run_e2e_lima_shell() {
    # SSH does not inherit host credentials; require explicit forwarding.
    env -u BITWARDEN_CLIENT_ID -u BITWARDEN_CLIENT_SECRET -u BITWARDEN_PASSWORD \
        "${@//\/tmp\/workstation-manager-e2e-recovery/$TEST_FIXTURE/recovery}"
}
stream_e2e_entrypoint_script() { cat "$TEST_FIXTURE/wrapper.sh"; }
run_e2e_workstation_action() {
    [[ "$1" == backup ]]
    printf 'backup\n' >>"$TEST_FIXTURE/trace"
    if [[ -n "${TEST_BACKUP_SIGNAL:-}" ]]; then kill -"$TEST_BACKUP_SIGNAL" "$$"; fi
    return "$TEST_BACKUP_STATUS"
}
"""
    )
    # Keep real wrapper initialization, replacing external operations only.
    (tmp_path / "wrapper.sh").write_text(
        (WORKSPACE / "workstation.sh").read_text().rsplit('\nmain "$@"', 1)[0]
        + r"""
prepare_action_dependencies() {
    PRIVATE_OVERRIDE_LOCAL_FILE="$TEST_FIXTURE/private.yml"
}
download_github_file() { cp "$TEST_WORKSPACE/$3" "$4"; }
run_ansible_pull() {
    [[ "$1" == ansible/prepare_e2e_backup.yml && "$2" == 0 ]]
    [[ "$REPOSITORY_BRANCH" == fixture-revision ]]
    [[ "$BITWARDEN_CLIENT_ID_VALUE" == fixture-client ]]
    [[ "$BITWARDEN_CLIENT_SECRET_VALUE" == fixture-secret ]]
    [[ "$BITWARDEN_PASSWORD_VALUE" == fixture-password ]]
    [[ "$PRIVATE_OVERRIDE_LOCAL_FILE" == "$HOME/.local/share/chezmoi/private.override.yml" ]]
    cp "$PRIVATE_OVERRIDE_LOCAL_FILE" "$TEST_FIXTURE/prepared.yml"
    printf 'restore\n' >>"$TEST_FIXTURE/trace"
    return "$TEST_RESTORE_STATUS"
}
main "$@"
"""
    )
    skills = [{"name": "fixture-skill", "source": "~/.agents/skills/example"}]
    bitwarden = {
        "ssh_collection_id": "fixture-ssh",
        "gpg_collection_id": "fixture-gpg",
        "browser_profiles_collection_id": "fixture-browser",
    }
    private = {
        "development": {"ai_tools": {"skills": skills}},
        "secrets": {"bitwarden": bitwarden},
    }
    (tmp_path / "private.yml").write_text(json.dumps(private))
    (tmp_path / "chezmoi").write_text(
        "#!/bin/bash\nset -euo pipefail\n"
        'if [[ "$1" == init ]]; then\n'
        '    mkdir -p "$HOME/.local/share"\n'
        '    git clone "$2" "$HOME/.local/share/chezmoi"\n'
        "fi\n"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    dpkg = bin_dir / "dpkg"
    dpkg.write_text('#!/bin/sh\n[ "$1" = --print-architecture ] || exit 99\nprintf amd64\n')
    dpkg.chmod(0o755)
    curl = bin_dir / "curl"
    curl.write_text('#!/bin/bash\nset -euo pipefail\n[[ "$3" == -o ]]\ncp "$TEST_FIXTURE/chezmoi" "$4"\n')
    curl.chmod(0o755)
    user_home = tmp_path / "home"
    user_home.mkdir()
    return {
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "HOME": str(user_home),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "BITWARDEN_CLIENT_ID": "fixture-client",
        "BITWARDEN_CLIENT_SECRET": "fixture-secret",
        "BITWARDEN_PASSWORD": "fixture-password",
        "TEST_WORKSPACE": str(WORKSPACE),
        "TEST_FIXTURE": str(tmp_path),
        "TEST_RESTORE_STATUS": "0",
        "TEST_BACKUP_STATUS": "0",
        "TEST_FINISH_STATUS": "0",
    }


def run_backup(
    tmp_path: pathlib.Path, environment: dict[str, str], stage: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Invoke the production action script with only VM and external operations isolated."""
    return subprocess.run(
        ["bash", str(tmp_path / "e2e-tests/e2e-backup.sh"), "fixture-vm", *([stage] if stage else [])],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


@pytest.mark.parametrize("restore_status", [0, 37])
def test_backup_prepares_keys_and_stops_if_restoration_fails(
    tmp_path: pathlib.Path, backup_environment: dict[str, str], restore_status: int
) -> None:
    """Restore the configured collections before backup, retaining failure and cleanup."""
    result = run_backup(tmp_path, {**backup_environment, "TEST_RESTORE_STATUS": str(restore_status)})
    user_home = pathlib.Path(backup_environment["HOME"])
    private = json.loads((tmp_path / "private.yml").read_text())
    assert result.returncode == restore_status, result.stdout + result.stderr
    phases = (tmp_path / "trace").read_text().splitlines()
    assert phases == (["restore", "backup"] if restore_status == 0 else ["restore"])
    prepared = DataLoader().load_from_file(str(tmp_path / "prepared.yml"))
    assert prepared["secrets"]["bitwarden"] == {
        **private["secrets"]["bitwarden"],
        "browser_profiles_collection_id": "",
    }
    setup_override = user_home / ".local/state/workstation-manager/e2e/private.override.yml"
    setup = DataLoader().load_from_file(str(setup_override))
    assert setup == {
        **private,
        "development": {"ai_tools": {**private["development"]["ai_tools"], "authenticate": False}},
    }
    assert setup_override.stat().st_mode & 0o777 == 0o600
    assert json.loads((tmp_path / "private.yml").read_text()) == private
    assert not (user_home / ".local/share/chezmoi").exists()
    assert not (user_home / ".config/chezmoi/chezmoi.yaml").exists()
    assert not (tmp_path / "recovery").exists()
    assert "fixture-secret" not in result.stdout + result.stderr
    assert "fixture-password" not in result.stdout + result.stderr


@pytest.mark.parametrize("action_status,signal,expected", [(0, "", 0), (29, "", 29), (0, "TERM", 143), (0, "INT", 130)])
def test_separate_backup_stages_retain_fixture_until_act_and_always_remove_it(
    tmp_path: pathlib.Path, backup_environment: dict[str, str], action_status: int, signal: str, expected: int
) -> None:
    """Separate actions share private recovery state, then clean it even after failure or interruption."""
    arranged = run_backup(tmp_path, backup_environment, "arrange")
    assert arranged.returncode == 0, arranged.stdout + arranged.stderr
    recovery = tmp_path / "recovery"
    assert recovery.stat().st_mode & 0o777 == 0o700
    assert (recovery / "ready").is_file()
    assert (tmp_path / "trace").read_text().splitlines() == ["restore"]
    user_home = pathlib.Path(backup_environment["HOME"])
    assert (user_home / ".local/share/chezmoi/private.override.yml").is_file()

    result = run_backup(
        tmp_path,
        {**backup_environment, "TEST_BACKUP_STATUS": str(action_status), "TEST_BACKUP_SIGNAL": signal},
        "act",
    )
    assert result.returncode == expected, result.stdout + result.stderr
    assert (tmp_path / "trace").read_text().splitlines() == ["restore", "backup"]
    assert not recovery.exists()
    assert not (user_home / ".local/share/chezmoi").exists()
    assert not (user_home / ".config/chezmoi/chezmoi.yaml").exists()


def test_finish_without_credentials_preserves_later_setup_state(
    tmp_path: pathlib.Path, backup_environment: dict[str, str]
) -> None:
    """Repeated finalization cannot remove the real Chezmoi state installed after backup."""
    assert run_backup(tmp_path, backup_environment).returncode == 0
    user_home = pathlib.Path(backup_environment["HOME"])
    source = user_home / ".local/share/chezmoi/real-source"
    source.parent.mkdir(parents=True)
    source.write_text("real source")
    config = user_home / ".config/chezmoi/chezmoi.yaml"
    config.write_text("real configuration")
    environment = {name: value for name, value in backup_environment.items() if not name.startswith("BITWARDEN_")}
    for _ in range(2):
        result = run_backup(tmp_path, environment, "finish")
        assert result.returncode == 0, result.stdout + result.stderr
    assert source.read_text() == "real source"
    assert config.read_text() == "real configuration"


def test_arrange_refuses_to_reuse_or_clean_an_existing_fixture(
    tmp_path: pathlib.Path, backup_environment: dict[str, str]
) -> None:
    """An unsuccessful directory claim must not install cleanup for a previous fixture."""
    assert run_backup(tmp_path, backup_environment, "arrange").returncode == 0
    result = run_backup(tmp_path, backup_environment, "arrange")
    assert result.returncode != 0
    assert (tmp_path / "recovery/ready").is_file()
    assert (tmp_path / "trace").read_text().splitlines() == ["restore"]
    assert (pathlib.Path(backup_environment["HOME"]) / ".local/share/chezmoi/private.override.yml").is_file()
    assert run_backup(tmp_path, backup_environment, "finish").returncode == 0


@pytest.mark.parametrize("action_status,expected", [(0, 42), (37, 37)])
def test_backup_cleanup_errors_do_not_replace_the_action_failure(
    tmp_path: pathlib.Path, backup_environment: dict[str, str], action_status: int, expected: int
) -> None:
    """A failed bounded cleanup fails successful backup but preserves an earlier action failure."""
    assert run_backup(tmp_path, backup_environment, "arrange").returncode == 0
    result = run_backup(
        tmp_path,
        {**backup_environment, "TEST_BACKUP_STATUS": str(action_status), "TEST_FINISH_STATUS": "42"},
        "act",
    )
    assert result.returncode == expected, result.stdout + result.stderr
    assert (tmp_path / "recovery").exists()
    assert run_backup(tmp_path, backup_environment, "finish").returncode == 0


def test_backup_act_requires_a_completed_arrangement(
    tmp_path: pathlib.Path, backup_environment: dict[str, str]
) -> None:
    """Backup cannot run before a recovery fixture has completed preparation."""
    result = run_backup(tmp_path, backup_environment, "act")
    assert result.returncode != 0
    assert "Run backup arrange" in result.stderr
    assert not (tmp_path / "trace").exists()
