#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=e2e-tests/e2e-common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/e2e-common.sh"

E2E_VM_NAME="${1:?Lima instance name is required}"
instances="$(limactl list --format '{{.Name}}')"
if ! printf '%s\n' "$instances" | grep -Fxq "$E2E_VM_NAME"; then
	exit 0
fi

status="$(limactl list "$E2E_VM_NAME" --format '{{.Status}}')"
if [[ "$status" != "Running" ]]; then
	# A stopped guest still owns its remote devices. Resume it before discarding
	# the identities needed by Brave's native current-device leave operation.
	limactl start --timeout=2m "$E2E_VM_NAME"
fi

# Sync waits and retries are bounded per device. Let every captured profile
# finish instead of interrupting the whole fixture during a leave or restoration.
if ! run_e2e_lima_shell \
	env PYTHONPATH=/workspace/ansible/collections \
	python3 /workspace/e2e-tests/browser_sync_fixture.py leave; then
	printf '%s\n' 'Browser fixture teardown failed; the VM and recorded device identities were retained for diagnosis.' >&2
	exit 1
fi

limactl stop "$E2E_VM_NAME"
limactl delete -f "$E2E_VM_NAME"
