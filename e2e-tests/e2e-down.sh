#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=e2e-tests/e2e-common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/e2e-common.sh"

E2E_VM_NAME="${1:?Lima instance name is required}"
instances="$(limactl list --format '{{.Name}}')"
if ! printf '%s\n' "$instances" | grep -Fxq "$E2E_VM_NAME"; then
	exit 0
fi

bash "$(dirname -- "${BASH_SOURCE[0]}")/e2e-leave.sh" "$E2E_VM_NAME"

limactl stop "$E2E_VM_NAME"
limactl delete -f "$E2E_VM_NAME"
