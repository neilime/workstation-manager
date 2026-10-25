#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=e2e-tests/e2e-common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/e2e-common.sh"

E2E_VM_NAME="${1:?Lima instance name is required}"
workspace_dir="$(resolve_e2e_workspace_dir)"
runtime_config_file="$(mktemp "${TMPDIR:-/tmp}/workstation-manager-lima-XXXXXX.yml")"
trap 'rm -f "$runtime_config_file"' EXIT
trap 'exit 1' HUP INT TERM
sed "s|location: \".\"|location: \"$workspace_dir\"|" \
	"$workspace_dir/e2e-tests/lima-ubuntu.yml" >"$runtime_config_file"

start_args=(--timeout=20m)
if limactl list --format '{{.Name}}' 2>/dev/null | grep -Fxq "$E2E_VM_NAME"; then
	start_args+=("$E2E_VM_NAME")
else
	start_args+=(-y --containerd=none "--name=$E2E_VM_NAME")
	if [[ -n "${E2E_BASE_IMAGE:-}" ]]; then
		image_override="$(
			python3 - "$E2E_BASE_IMAGE" <<'PY'
import hashlib
import json
import pathlib
import sys

image = pathlib.Path(sys.argv[1]).resolve(strict=True)
with image.open("rb") as stream:
    digest = hashlib.file_digest(stream, "sha256").hexdigest()
print('.images = ' + json.dumps([{"location": str(image), "arch": "x86_64", "digest": "sha256:" + digest}]))
PY
		)"
		start_args+=(--set "$image_override")
	fi
	# Resource overrides apply only when creating a disposable fixture.
	for resource in E2E_VM_CPUS E2E_VM_MEMORY_GIB; do
		value="${!resource:-}"
		if [[ -z "$value" ]]; then
			continue
		fi
		if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
			printf '%s must be a positive integer\n' "$resource" >&2
			exit 1
		fi
		case "$resource" in
		E2E_VM_CPUS) start_args+=("--cpus=$value") ;;
		E2E_VM_MEMORY_GIB) start_args+=("--memory=$value") ;;
		esac
	done
	start_args+=("$runtime_config_file")
fi

if limactl start "${start_args[@]}"; then
	exit 0
else
	start_status=$?
fi

# Preserve the startup failure even when the guest cannot answer diagnostics.
print_e2e_vm_diagnostics >&2 || true
run_e2e_lima_control_command 30 sudo -n bash -s >&2 <<'EOF' || true
printf '\nCloud-init provisioning output:\n'
tail -n 200 /var/log/cloud-init-output.log
printf '\nBoot service logs:\n'
journalctl --boot --no-pager --lines=200 \
  --unit=cloud-init-main --unit=cloud-final --unit=gdm3 --unit=systemd-networkd
printf '\nFailed services:\n'
systemctl --failed --no-pager
printf '\nMemory and disk usage:\n'
free -m
df -h /
EOF
exit "$start_status"
