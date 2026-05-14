#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=e2e-common.sh
source "$script_dir/e2e-common.sh"

resolve_e2e_workstation_context "${1:-workstation-manager-v1}"

backup_root="/tmp/workstation-manager-e2e-backup"
target_user_home="$(resolve_e2e_target_user_home)"
chrome_config_dir="${target_user_home}/.config/google-chrome/Default"
managed_profiles_dir="${target_user_home}/.local/share/workstation-manager/browser-profiles/personal"

run_e2e_vm_shell "rm -rf '$backup_root'"

run_e2e_vm_shell "$(
	cat <<EOF
mkdir -p '$managed_profiles_dir'
mkdir -p '$chrome_config_dir'
cat >'$chrome_config_dir/Bookmarks' <<'JSON'
{
	"checksum": "backup-fixture",
	"roots": {
		"bookmark_bar": {
			"children": [
				{
					"id": "1",
					"name": "workstation-manager",
					"type": "url",
					"url": "https://github.com/neilime/workstation-manager"
				}
			],
			"id": "10",
			"name": "Bookmarks bar",
			"type": "folder"
		},
		"other": {
			"children": [],
			"id": "11",
			"name": "Other bookmarks",
			"type": "folder"
		},
		"synced": {
			"children": [],
			"id": "12",
			"name": "Mobile bookmarks",
			"type": "folder"
		}
	},
	"version": 1
}
JSON
EOF
)"

run_e2e_workstation_action \
	backup \
	"WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR=$backup_root"
