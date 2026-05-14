#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=e2e-common.sh
source "$script_dir/e2e-common.sh"

resolve_e2e_workstation_context "${1:-workstation-manager-v1}"

target_user_home="$(resolve_e2e_target_user_home)"
stale_profile_dir="${target_user_home}/.local/share/workstation-manager/browser-profiles/e2e-stale"

run_e2e_vm_shell "
rm -rf '$stale_profile_dir'
mkdir -p '$stale_profile_dir/Default'
printf '%s\n' 'e2e-stale-profile' >'$stale_profile_dir/Default/First Run'
"

run_e2e_workstation_action \
	cleanup
