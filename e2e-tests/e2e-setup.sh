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
rm -rf '$target_user_home/.config/google-chrome'
rm -rf '$target_user_home/.config/workstation-manager'
rm -rf '$target_user_home/.local/share/workstation-manager/browser-profiles'
EOF
)"

run_e2e_workstation_action \
	setup \
	"BITWARDEN_CLIENT_ID=${BITWARDEN_CLIENT_ID}" \
	"BITWARDEN_CLIENT_SECRET=${BITWARDEN_CLIENT_SECRET}" \
	"BITWARDEN_PASSWORD=${BITWARDEN_PASSWORD}" \
	"WORKSTATION_MANAGER_RESTORE_ARCHIVE=${restore_archive}"
