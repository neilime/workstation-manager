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
projects_dir="${target_user_home}/Documents/dev-projects/client-restore"
managed_config_dir="${target_user_home}/.config/workstation-manager"
git_remote_dir="/tmp/workstation-manager-e2e-origin-client-restore.git"
git_seed_dir="/tmp/workstation-manager-e2e-seed-client-restore"

run_e2e_vm_shell "rm -rf '$backup_root' '$git_remote_dir' '$git_seed_dir'"

run_e2e_vm_shell "$(
	cat <<EOF
mkdir -p '$managed_profiles_dir'
mkdir -p '$chrome_config_dir'
mkdir -p '$managed_config_dir'
git init --bare '$git_remote_dir'
git init --initial-branch main '$git_seed_dir'
git -C '$git_seed_dir' config user.name 'E2E User'
git -C '$git_seed_dir' config user.email 'e2e@example.com'
printf '%s\n' 'remote-base' >'$git_seed_dir/tracked.txt'
git -C '$git_seed_dir' add tracked.txt
git -C '$git_seed_dir' commit -m 'initial commit'
git -C '$git_seed_dir' remote add origin '$git_remote_dir'
git -C '$git_seed_dir' push origin main
git --git-dir='$git_remote_dir' symbolic-ref HEAD refs/heads/main
git clone '$git_remote_dir' '$projects_dir'
printf '%s\n' 'browser-profile-fixture' >'$managed_profiles_dir/profile.txt'
printf '%s\n' 'restored-project' >'$projects_dir/project.txt'
printf '%s\n' 'local-untracked' >'$projects_dir/local-note.txt'
printf '%s\n' 'local-change' >>'$projects_dir/tracked.txt'
printf '%s\n' 'managed-config-fixture' >'$managed_config_dir/restore-fixture.txt'
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
