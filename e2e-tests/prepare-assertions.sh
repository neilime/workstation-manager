#!/usr/bin/env bash
set -euo pipefail
umask 077
vm_name="${1:?Expected VM name}"
phase="${2:?Expected assertion phase}"
case "$phase" in backup | setup | cleanup) ;; *) exit 2 ;; esac
report_dir="${REPORTS_DIR:-.reports}"
if [[ -n "${E2E_SUITE_DEADLINE:-}" ]]; then
	[[ "$E2E_SUITE_DEADLINE" =~ ^[0-9]{1,10}$ ]] || exit 2
	remaining=$((10#$E2E_SUITE_DEADLINE - $(date +%s)))
	if [[ "$remaining" -lt 60 ]]; then
		printf '%s\n' 'E2E stages exhausted their shared deadline.' >&2
		exit 124
	fi
fi
mkdir -p "$report_dir/goss"
# Setup exports expectations once; cleanup reuses the same guest identity.
if [[ "$phase" == setup ]]; then
	timeout --kill-after=5s "${remaining:-60}s" limactl shell --workdir=/tmp "$vm_name" bash -s <<'GUEST' >"$report_dir/goss/vars.json"
set -euo pipefail
umask 077
root="$HOME/.local/state/workstation-manager/e2e"
mkdir -p "$root"
staging=$(mktemp "$root/goss-vars.XXXXXXXX")
trap 'rm -f "$staging"' EXIT
/opt/workstation-manager/venv/bin/python /workspace/e2e-tests/goss_vars.py >"$staging"
mv "$staging" "$root/goss-vars.json"
cat "$root/goss-vars.json"
GUEST
fi

# Bound each CI assertion by the remaining shared budget, rounded down.
minutes=10
if [[ -n "${E2E_SUITE_DEADLINE:-}" ]]; then
	[[ "$E2E_SUITE_DEADLINE" =~ ^[0-9]{1,10}$ ]] || exit 2
	minutes=$(((10#$E2E_SUITE_DEADLINE - $(date +%s)) / 60))
	if [[ "$minutes" -lt 1 ]]; then
		printf '%s\n' 'E2E stages exhausted their shared deadline.' >&2
		exit 124
	fi
	if [[ "$minutes" -gt 40 ]]; then minutes=40; fi
fi
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
	printf 'timeout-minutes=%s\n' "$minutes" >>"$GITHUB_OUTPUT"
fi
