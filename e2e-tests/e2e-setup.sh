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

run_e2e_workstation_action \
	setup \
	"BITWARDEN_CLIENT_ID=${BITWARDEN_CLIENT_ID}" \
	"BITWARDEN_CLIENT_SECRET=${BITWARDEN_CLIENT_SECRET}" \
	"BITWARDEN_PASSWORD=${BITWARDEN_PASSWORD}"
