#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=e2e-common.sh
source "$script_dir/e2e-common.sh"

resolve_e2e_workstation_context "${1:-workstation-manager-v1}"
require_e2e_env_vars \
	BITWARDEN_CLIENT_ID \
	BITWARDEN_CLIENT_SECRET \
	BITWARDEN_PASSWORD

backup_root="/tmp/workstation-manager-e2e-backup"
target_user_home="$(resolve_e2e_target_user_home)"
restore_archive="$(
	run_e2e_vm_shell "set -eu; archives=\$(find '$backup_root' -maxdepth 1 -type f -name 'workstation-manager-backup-*.tar.gz' | sort); [ \"\$(printf '%s\\n' \"\$archives\" | sed '/^$/d' | wc -l)\" -eq 1 ]; printf '%s' \"\$archives\""
)"

run_e2e_vm_shell "$(
	cat <<EOF
rm -rf '$target_user_home/Documents/dev-projects'
rm -rf '$target_user_home/.config/workstation-manager'
EOF
)"

run_e2e_lima_shell env PYTHONPATH=/workspace/ansible/collections \
	python3 /workspace/e2e-tests/browser_sync_fixture.py prepare

capture_browser_devices() {
	local setup_status=$?
	local capture_status=0
	local capture_args=(capture)
	if [[ $setup_status -eq 0 ]]; then
		capture_args+=(--require-initialized)
	fi
	run_e2e_lima_shell env PYTHONPATH=/workspace/ansible/collections \
		python3 /workspace/e2e-tests/browser_sync_fixture.py "${capture_args[@]}" || capture_status=$?
	if [[ $setup_status -eq 0 ]]; then
		setup_status=$capture_status
	fi
	exit "$setup_status"
}
trap capture_browser_devices EXIT

run_e2e_workstation_action \
	setup \
	"WORKSTATION_MANAGER_GHCR_TOKEN=${WORKSTATION_MANAGER_GHCR_TOKEN:-}" \
	"WORKSTATION_MANAGER_PRIVATE_OVERRIDE_FILE=$target_user_home/.local/state/workstation-manager/e2e/private.override.yml" \
	"BITWARDEN_CLIENT_ID=${BITWARDEN_CLIENT_ID}" \
	"BITWARDEN_CLIENT_SECRET=${BITWARDEN_CLIENT_SECRET}" \
	"BITWARDEN_PASSWORD=${BITWARDEN_PASSWORD}" \
	"WORKSTATION_MANAGER_RESTORE_ARCHIVE=${restore_archive}"
