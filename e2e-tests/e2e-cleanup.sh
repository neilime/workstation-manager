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

target_user_home="$(resolve_e2e_target_user_home)"
browser_root="${target_user_home}/.config/BraveSoftware/Brave-Browser"

run_e2e_vm_shell "
mkdir -p '$browser_root/managed-e2e-stale' '$browser_root/Profile 9999' '$browser_root/e2e-component-cache'
printf '%s\n' '{}' >'$browser_root/managed-e2e-stale/Preferences'
printf '%s\n' '{}' >'$browser_root/Profile 9999/Preferences'
printf '%s\n' 'preserve' >'$browser_root/managed-e2e-stale/e2e-preserve-marker'
printf '%s\n' 'preserve' >'$browser_root/Profile 9999/e2e-preserve-marker'
printf '%s\n' 'preserve' >'$browser_root/e2e-component-cache/e2e-preserve-marker'
"

run_e2e_detached_workstation_action \
	cleanup \
	"BITWARDEN_CLIENT_ID=${BITWARDEN_CLIENT_ID}" \
	"BITWARDEN_CLIENT_SECRET=${BITWARDEN_CLIENT_SECRET}" \
	"BITWARDEN_PASSWORD=${BITWARDEN_PASSWORD}"
