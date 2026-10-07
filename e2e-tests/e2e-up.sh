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
	start_args+=(-y --containerd=none "--name=$E2E_VM_NAME" "$runtime_config_file")
fi

if run_e2e_timed_command vm-start limactl start "${start_args[@]}"; then
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
