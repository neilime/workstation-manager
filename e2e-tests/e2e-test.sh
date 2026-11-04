#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=e2e-common.sh
source "$script_dir/e2e-common.sh"

vm_name="${1:-workstation-manager-v1}"
stage="${2:-all}"
stages=(backup-arrange backup-act backup-assert setup-arrange setup-act setup-assert cleanup-arrange cleanup-act cleanup-assert)
case "$stage" in
all | finish | backup-arrange | backup-act | backup-assert | setup-arrange | setup-act | setup-assert | cleanup-arrange | cleanup-act | cleanup-assert) ;;
*)
	printf '%s\n' 'Unsupported E2E stage.' >&2
	exit 2
	;;
esac

# CI shares one deadline across all nine steps, leaving verified teardown outside it.
if [[ "$stage" != all && "$stage" != finish && -n "${E2E_SUITE_DEADLINE:-}" ]]; then
	if [[ ! "$E2E_SUITE_DEADLINE" =~ ^[0-9]{1,10}$ ]]; then
		printf '%s\n' 'E2E suite deadline must be an epoch timestamp.' >&2
		exit 2
	fi
	remaining_seconds=$((10#$E2E_SUITE_DEADLINE - $(date +%s)))
	if [[ $remaining_seconds -le 0 ]]; then
		printf '%s\n' 'E2E stages exhausted their shared deadline.' >&2
		exit 124
	fi
	exec timeout --kill-after=60s "${remaining_seconds}s" \
		env -u E2E_SUITE_DEADLINE bash "$0" "$vm_name" "$stage"
fi

report_dir="${REPORTS_DIR:-}"
screenshot_dir="${SCREENSHOTS_DIR:-${report_dir:-.reports}/screenshots}"
screenshot_status_path="$screenshot_dir/e2e-setup-desktop.status"
cleanup_phase_timeout_seconds="${E2E_CLEANUP_PHASE_TIMEOUT_SECONDS:-720}"

E2E_VM_NAME="$vm_name"

capture_phase_screenshot() {
	local phase_name="$1"
	local screenshot_name=""
	local screenshot_path=""
	local status_path=""

	screenshot_name="e2e-${phase_name}-desktop"
	screenshot_path="$screenshot_dir/${screenshot_name}.png"
	status_path="$screenshot_dir/${screenshot_name}.txt"
	mkdir -p "$screenshot_dir"

	if capture_e2e_vm_desktop "$screenshot_name" "$screenshot_dir" && [[ -s "$screenshot_path" ]]; then
		printf '%s\n' "Captured ${screenshot_name}.png" >"$status_path"
		return 0
	fi

	printf '%s\n' "Desktop screenshot capture failed for phase ${phase_name}. See ${screenshot_name}.log for details." >"$status_path"
	return 1
}

run_phase_tests() {
	bash "$script_dir/run-assertions.sh" "$vm_name" "$1"
}

run_setup_action() {
	local setup_status=0
	local capture_status=0

	bash "$script_dir/e2e-setup.sh" "$vm_name" act || setup_status=$?
	if [[ $setup_status -eq 0 ]]; then
		# Restart in Act so concurrent Goss checks observe a stable native daemon.
		run_e2e_lima_shell sudo -n systemctl restart docker.service || setup_status=$?
	fi
	if [[ $setup_status -eq 0 ]]; then
		# Expand HOME inside the guest, not on the controller.
		# shellcheck disable=SC2016
		run_e2e_lima_shell sh -c '"$HOME/.local/bin/workstation-manager-bleachbit-clean"' || setup_status=$?
	fi
	if [[ $setup_status -eq 0 ]]; then
		restart_e2e_desktop_session || setup_status=$?
	fi
	if [[ $setup_status -eq 0 ]]; then
		wait_for_e2e_clipboard_extension || setup_status=$?
	fi
	capture_phase_screenshot setup || capture_status=$?
	# Defer screenshot-only failure until after all assertions and cleanup.
	if ! printf '%s\n' "$capture_status" >"$screenshot_status_path"; then
		printf '%s\n' 'Could not record the E2E screenshot status.' >&2
		if [[ $setup_status -eq 0 ]]; then
			setup_status=1
		fi
	fi
	if [[ $setup_status -ne 0 ]]; then
		print_e2e_desktop_diagnostics ||
			printf '%s\n' 'Desktop diagnostics could not complete.' >&2
		run_e2e_lima_shell \
			env PYTHONPATH=/workspace/ansible/collections \
			python3 /workspace/e2e-tests/browser_sync_diagnostics.py ||
			printf '%s\n' 'Browser initialization diagnostics could not complete.' >&2
	fi
	return "$setup_status"
}

run_cleanup_action() {
	local cleanup_status=0
	timeout --kill-after=15s "${cleanup_phase_timeout_seconds}s" \
		bash "$script_dir/e2e-cleanup.sh" "$vm_name" act || cleanup_status=$?
	if [[ $cleanup_status -eq 124 || $cleanup_status -eq 137 ]]; then
		printf '%s\n' "E2E cleanup phase exceeded its ${cleanup_phase_timeout_seconds}s hard deadline" >&2
	fi
	return "$cleanup_status"
}

finish_e2e_fixtures() {
	local finish_status=0
	timeout --kill-after=5s 60s bash "$script_dir/e2e-backup.sh" "$vm_name" finish || finish_status=$?
	if [[ -f "$screenshot_status_path" && "$(cat "$screenshot_status_path")" != 0 ]]; then
		printf '%s\n' 'E2E setup screenshot failed; see the screenshot diagnostics.' >&2
		if [[ $finish_status -eq 0 ]]; then
			finish_status=1
		fi
	fi
	return "$finish_status"
}

finish_e2e_suite() {
	local suite_status=$?
	local finish_status=0
	finish_e2e_fixtures || finish_status=$?
	if [[ $suite_status -eq 0 ]]; then
		suite_status=$finish_status
	fi
	exit "$suite_status"
}

trap 'exit 143' TERM
trap 'exit 130' INT
if [[ "$stage" == all ]]; then
	trap finish_e2e_suite EXIT
	for suite_stage in "${stages[@]}"; do
		bash "$0" "$vm_name" "$suite_stage"
	done
	exit 0
fi
if [[ "$stage" == finish ]]; then
	finish_e2e_fixtures
	exit 0
fi
if [[ "$stage" == backup-arrange ]]; then
	rm -f "$screenshot_status_path"
fi

case "$stage" in
backup-arrange | backup-act | setup-arrange | cleanup-arrange)
	bash "$script_dir/e2e-${stage%-*}.sh" "$vm_name" "${stage##*-}"
	;;
setup-act) run_setup_action ;;
cleanup-act) run_cleanup_action ;;
backup-assert) run_phase_tests backup ;;
setup-assert) run_phase_tests setup ;;
cleanup-assert) run_phase_tests cleanup ;;
esac
