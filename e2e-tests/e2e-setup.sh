#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=e2e-common.sh
source "$script_dir/e2e-common.sh"

stage="${2:-all}"
case "$stage" in
all | arrange | act | repeat) ;;
*)
	printf '%s\n' 'Expected setup stage: all, arrange, act, or repeat.' >&2
	exit 2
	;;
esac
if [[ $# -gt 2 ]]; then
	printf '%s\n' 'Too many setup arguments.' >&2
	exit 2
fi

resolve_e2e_workstation_context "${1:-workstation-manager-v1}"
if [[ "$stage" != arrange ]]; then
	require_e2e_env_vars \
		BITWARDEN_CLIENT_ID \
		BITWARDEN_CLIENT_SECRET \
		BITWARDEN_PASSWORD
fi

backup_root="/tmp/workstation-manager-e2e-backup"
target_user_home="$(resolve_e2e_target_user_home)"
restore_environment=()
repeat_guard="$HOME/.lima/${1:-workstation-manager-v1}/setup-repeat.pending"

if [[ "$stage" == repeat ]]; then
	# Keep the original ownership record and retain the VM after interrupted or
	# unverifiable repeats, including unexpected additional remote identities.
	mkdir -p "$(dirname "$repeat_guard")"
	touch "$repeat_guard"
	run_e2e_lima_shell env PYTHONPATH=/workspace/ansible/collections \
		python3 /workspace/e2e-tests/browser_sync_fixture.py verify
else
	restore_archive="$(
		run_e2e_vm_shell "set -eu; archives=\$(find '$backup_root' -maxdepth 1 -type f -name 'workstation-manager-backup-*.tar.gz' | sort); [ \"\$(printf '%s\\n' \"\$archives\" | sed '/^$/d' | wc -l)\" -eq 1 ]; printf '%s' \"\$archives\""
	)"
	restore_environment=("WORKSTATION_MANAGER_RESTORE_ARCHIVE=$restore_archive")

	if [[ "$stage" != act ]]; then
		run_e2e_vm_shell "$(
			cat <<EOF
rm -rf '$target_user_home/Documents/dev-projects'
rm -rf '$target_user_home/.config/workstation-manager'
EOF
		)"
		if [[ "$stage" == arrange ]]; then
			exit 0
		fi
	else
		run_e2e_vm_shell "
		set -eu
		for path in '$target_user_home/Documents/dev-projects' '$target_user_home/.config/workstation-manager'; do
			if [ -e \"\$path\" ] || [ -L \"\$path\" ]; then
				printf '%s\\n' 'Run setup arrange before setup act.' >&2
				exit 1
			fi
		done
	"
	fi

	run_e2e_lima_shell env PYTHONPATH=/workspace/ansible/collections \
		python3 /workspace/e2e-tests/browser_sync_fixture.py prepare
fi

capture_browser_devices() {
	local setup_status=$?
	local capture_status=0
	local capture_args=(capture)
	if [[ "$stage" == repeat ]]; then
		capture_args=(verify)
	elif [[ $setup_status -eq 0 ]]; then
		capture_args+=(--require-initialized)
	fi
	run_e2e_lima_shell env PYTHONPATH=/workspace/ansible/collections \
		python3 /workspace/e2e-tests/browser_sync_fixture.py "${capture_args[@]}" || capture_status=$?
	if [[ "$stage" == repeat && $capture_status -eq 0 && $setup_status -ne 130 && $setup_status -ne 143 ]]; then
		rm -f "$repeat_guard"
	fi
	if [[ $setup_status -eq 0 ]]; then
		setup_status=$capture_status
	fi
	exit "$setup_status"
}
trap capture_browser_devices EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

timing_phase=setup-command
if [[ "$stage" == repeat ]]; then timing_phase=setup-repeat-command; fi
run_e2e_timed_command "$timing_phase" run_e2e_workstation_action \
	setup \
	"WORKSTATION_MANAGER_GHCR_TOKEN=${WORKSTATION_MANAGER_GHCR_TOKEN:-}" \
	"WORKSTATION_MANAGER_PRIVATE_OVERRIDE_FILE=$target_user_home/.local/state/workstation-manager/e2e/private.override.yml" \
	"BITWARDEN_CLIENT_ID=${BITWARDEN_CLIENT_ID}" \
	"BITWARDEN_CLIENT_SECRET=${BITWARDEN_CLIENT_SECRET}" \
	"BITWARDEN_PASSWORD=${BITWARDEN_PASSWORD}" \
	"${restore_environment[@]}"
