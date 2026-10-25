#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=e2e-common.sh
source "$script_dir/e2e-common.sh"

stage="${2:-all}"
case "$stage" in
all | arrange | act) ;;
*)
	printf '%s\n' 'Expected cleanup stage: all, arrange, or act.' >&2
	exit 2
	;;
esac
if [[ $# -gt 2 ]]; then
	printf '%s\n' 'Too many cleanup arguments.' >&2
	exit 2
fi

resolve_e2e_workstation_context "${1:-workstation-manager-v1}"
if [[ "$stage" != arrange ]]; then
	require_e2e_env_vars \
		BITWARDEN_CLIENT_ID \
		BITWARDEN_CLIENT_SECRET \
		BITWARDEN_PASSWORD
fi

target_user_home="$(resolve_e2e_target_user_home)"
browser_root="${target_user_home}/.config/BraveSoftware/Brave-Browser"

if [[ "$stage" != act ]]; then
	run_e2e_vm_shell "
mkdir -p '$browser_root/managed-e2e-stale' '$browser_root/Profile 9999' '$browser_root/e2e-component-cache'
printf '%s\n' '{}' >'$browser_root/managed-e2e-stale/Preferences'
printf '%s\n' '{}' >'$browser_root/Profile 9999/Preferences'
printf '%s\n' 'preserve' >'$browser_root/managed-e2e-stale/e2e-preserve-marker'
printf '%s\n' 'preserve' >'$browser_root/Profile 9999/e2e-preserve-marker'
printf '%s\n' 'preserve' >'$browser_root/e2e-component-cache/e2e-preserve-marker'
"
	if [[ "$stage" == arrange ]]; then
		exit 0
	fi
else
	run_e2e_vm_shell "
		set -eu
		for directory in managed-e2e-stale 'Profile 9999' e2e-component-cache; do
			if [ ! -f '$browser_root'/\"\$directory\"/e2e-preserve-marker ]; then
				printf '%s\\n' 'Run cleanup arrange before cleanup act.' >&2
				exit 1
			fi
		done
	"
fi

run_e2e_detached_workstation_action \
	cleanup \
	"WORKSTATION_MANAGER_PRIVATE_OVERRIDE_FILE=$target_user_home/.local/state/workstation-manager/e2e/private.override.yml" \
	"BITWARDEN_CLIENT_ID=${BITWARDEN_CLIENT_ID}" \
	"BITWARDEN_CLIENT_SECRET=${BITWARDEN_CLIENT_SECRET}" \
	"BITWARDEN_PASSWORD=${BITWARDEN_PASSWORD}"
