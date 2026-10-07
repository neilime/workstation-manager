#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=e2e-common.sh
source "$script_dir/e2e-common.sh"

vm_name="${1:-workstation-manager-v1}"
ssh_host="lima-${vm_name}"
tooling_image="${TOOLING_IMAGE:-workstation-manager-tooling:local}"
host_home="${HOME}"
workspace_dir="$(cd -- "$script_dir/.." && pwd)"
ssh_config_path="${host_home}/.lima/${vm_name}/ssh.config"
report_dir="${REPORTS_DIR:-}"
screenshot_dir="${SCREENSHOTS_DIR:-${report_dir:-.reports}/screenshots}"
cleanup_phase_timeout_seconds="${E2E_CLEANUP_PHASE_TIMEOUT_SECONDS:-720}"
setup_test_paths=()

E2E_VM_NAME="$vm_name"

for test_path in e2e-tests/test_*.py; do
	case "$(basename "$test_path")" in
	test_backup.py | test_cleanup.py) ;;
	*)
		setup_test_paths+=("$test_path")
		;;
	esac
done

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
	local phase_name="$1"
	local phase_report_option=()
	local phase_report_file=""
	shift

	# Setup can add groups. Reauthenticate the test connection so assertions see
	# the same permissions as a new terminal session after login.
	if [[ "$phase_name" == setup ]] && ssh -F "$ssh_config_path" -O check "$ssh_host" >/dev/null 2>&1; then
		ssh -F "$ssh_config_path" -O exit "$ssh_host"
	fi

	if [[ -n "$report_dir" ]]; then
		phase_report_file="$report_dir/tests/e2e-${phase_name}.junit.xml"
		mkdir -p "$(dirname "$phase_report_file")"
		phase_report_option=("--junitxml=/workspace/$phase_report_file")
	fi

	docker run --rm \
		--network host \
		--user "$(id -u):$(id -g)" \
		--env HOME=/tmp \
		--env XDG_CACHE_HOME=/tmp/.cache \
		--volume /etc/passwd:/etc/passwd:ro \
		--volume /etc/group:/etc/group:ro \
		--volume "$workspace_dir:/workspace" \
		--volume "$host_home/.lima:$host_home/.lima:ro" \
		--workdir /workspace \
		"$tooling_image" \
		python3 -m pytest \
		-q \
		-o cache_dir=/tmp/pytest-cache \
		--ssh-config="$ssh_config_path" \
		--hosts="ssh://$ssh_host" \
		"${phase_report_option[@]}" \
		"$@"
}

finish_e2e_suite() {
	local suite_status=$?
	local restore_status=0

	restore_e2e_task_profiling || restore_status=$?
	if [[ $suite_status -eq 0 ]]; then
		suite_status=$restore_status
	fi
	exit "$suite_status"
}

trap finish_e2e_suite EXIT
prepare_e2e_task_profiling

run_e2e_timed_command backup bash "$script_dir/e2e-backup.sh" "$vm_name"
run_e2e_timed_command backup-assertions run_phase_tests backup e2e-tests/test_backup.py
setup_status=0
run_e2e_timed_command setup bash "$script_dir/e2e-setup.sh" "$vm_name" || setup_status=$?
if [[ $setup_status -eq 0 ]]; then
	run_e2e_timed_command desktop-restart restart_e2e_desktop_session || setup_status=$?
fi
if [[ $setup_status -eq 0 ]]; then
	run_e2e_timed_command clipboard-extension wait_for_e2e_clipboard_extension || setup_status=$?
fi
capture_status=0
run_e2e_timed_command setup-screenshot capture_phase_screenshot setup || capture_status=$?
if [[ $setup_status -ne 0 ]]; then
	exit "$setup_status"
fi
run_e2e_timed_command setup-assertions run_phase_tests setup "${setup_test_paths[@]}"
cleanup_status=0
run_e2e_timed_command cleanup timeout \
	--kill-after=15s \
	"${cleanup_phase_timeout_seconds}s" \
	bash "$script_dir/e2e-cleanup.sh" "$vm_name" || cleanup_status=$?
if [[ $cleanup_status -ne 0 ]]; then
	if [[ $cleanup_status -eq 124 || $cleanup_status -eq 137 ]]; then
		printf '%s\n' \
			"E2E cleanup phase exceeded its ${cleanup_phase_timeout_seconds}s hard deadline" >&2
	fi
	exit "$cleanup_status"
fi
run_e2e_timed_command cleanup-assertions run_phase_tests cleanup e2e-tests/test_cleanup.py
if [[ $capture_status -ne 0 ]]; then
	exit "$capture_status"
fi
