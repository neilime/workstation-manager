"""Exercise fresh-VM backup preparation without a vault or workstation changes."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess

import pytest
from ansible.parsing.dataloader import DataLoader

WORKSPACE = pathlib.Path(__file__).parents[2]


@pytest.mark.parametrize("restore_status", [0, 37])
def test_backup_prepares_keys_and_stops_if_restoration_fails(tmp_path: pathlib.Path, restore_status: int) -> None:
    """Restore the configured collections before backup, retaining failure and cleanup."""

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
    case "$1" in
        'mktemp -d '*) mktemp -d "$TEST_FIXTURE/recovery.XXXXXX" ;;
        *source-created*) bash -c "$1" ;;
        *) : ;; # Project fixtures are unrelated to recovery preparation.
    esac
}
run_e2e_lima_shell() {
    # SSH does not inherit host credentials; require explicit forwarding.
    env -u BITWARDEN_CLIENT_ID -u BITWARDEN_CLIENT_SECRET -u BITWARDEN_PASSWORD "$@"
}
stream_e2e_entrypoint_script() { cat "$TEST_FIXTURE/wrapper.sh"; }
run_e2e_workstation_action() {
    [[ "$1" == backup ]]
    printf 'backup\n' >>"$TEST_FIXTURE/trace"
}
"""
    )
    # Keep real wrapper initialization, replacing external operations only.
    (tmp_path / "wrapper.sh").write_text(
        (WORKSPACE / "workstation.sh").read_text().rsplit('\nmain "$@"', 1)[0]
        + r"""
prepare_action_dependencies() {
    [[ "$1" == backup ]]
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
    private = {
        "secrets": {
            "bitwarden": {
                "ssh_collection_id": "fixture-ssh",
                "gpg_collection_id": "fixture-gpg",
                "browser_profiles_collection_id": "fixture-browser",
            }
        }
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
    curl = bin_dir / "curl"
    curl.write_text('#!/bin/bash\nset -euo pipefail\n[[ "$3" == -o ]]\ncp "$TEST_FIXTURE/chezmoi" "$4"\n')
    curl.chmod(0o755)
    user_home = tmp_path / "home"
    user_home.mkdir()
    result = subprocess.run(
        ["bash", str(scripts / "e2e-backup.sh"), "fixture-vm"],
        cwd=tmp_path,
        env={
            "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
            "HOME": str(user_home),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "BITWARDEN_CLIENT_ID": "fixture-client",
            "BITWARDEN_CLIENT_SECRET": "fixture-secret",
            "BITWARDEN_PASSWORD": "fixture-password",
            "TEST_WORKSPACE": str(WORKSPACE),
            "TEST_FIXTURE": str(tmp_path),
            "TEST_RESTORE_STATUS": str(restore_status),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == restore_status, result.stdout + result.stderr
    phases = (tmp_path / "trace").read_text().splitlines()
    assert phases == (["restore", "backup"] if restore_status == 0 else ["restore"])
    prepared = DataLoader().load_from_file(str(tmp_path / "prepared.yml"))
    assert prepared["secrets"]["bitwarden"] == {
        **private["secrets"]["bitwarden"],
        "browser_profiles_collection_id": "",
    }
    assert not (user_home / ".local/share/chezmoi").exists()
    assert not (user_home / ".config/chezmoi/chezmoi.yaml").exists()
    assert not list(tmp_path.glob("recovery.*"))
    assert "fixture-secret" not in result.stdout + result.stderr
    assert "fixture-password" not in result.stdout + result.stderr
