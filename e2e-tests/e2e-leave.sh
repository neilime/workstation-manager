#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=e2e-tests/e2e-common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/e2e-common.sh"

E2E_VM_NAME="${1:?Lima instance name is required}"
status="$(limactl list "$E2E_VM_NAME" --format '{{.Status}}')"
if [[ "$status" != "Running" ]]; then
	# Retain access to captured identities until their remote removal is verified.
	limactl start --timeout=2m "$E2E_VM_NAME"
fi

# Let the bounded per-device retries finish before authorizing VM deletion.
if ! run_e2e_lima_shell \
	env PYTHONPATH=/workspace/ansible/collections \
	python3 /workspace/e2e-tests/browser_sync_fixture.py leave; then
	printf '%s\n' 'Browser fixture teardown failed; the VM and recorded device identities were retained for diagnosis.' >&2
	exit 1
fi
