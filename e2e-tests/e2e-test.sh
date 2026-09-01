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
	phase_name="$1"
	shift
	phase_report_option=()

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
		--env PIP_DISABLE_PIP_VERSION_CHECK=1 \
		--volume /etc/passwd:/etc/passwd:ro \
		--volume /etc/group:/etc/group:ro \
		--volume "$workspace_dir:/workspace" \
		--volume "$host_home/.lima:$host_home/.lima:ro" \
		--workdir /workspace \
		"$tooling_image" \
		bash -lc '
set -euo pipefail
python3 -m pip install --user -q -r e2e-tests/requirements.txt
export PATH="$HOME/.local/bin:$PATH"
pytest "$@"
' bash \
		-q \
		-o cache_dir=/tmp/pytest-cache \
		--ssh-config="$ssh_config_path" \
		--hosts="ssh://$ssh_host" \
		"${phase_report_option[@]}" \
		"$@"
}

bash "$script_dir/e2e-backup.sh" "$vm_name"
run_phase_tests backup e2e-tests/test_backup.py
setup_status=0
bash "$script_dir/e2e-setup.sh" "$vm_name" || setup_status=$?
if [[ $setup_status -eq 0 ]]; then
	restart_e2e_desktop_session || setup_status=$?
fi
if [[ $setup_status -eq 0 ]]; then
	wait_for_e2e_user_process copyq || setup_status=$?
fi
capture_status=0
capture_phase_screenshot setup || capture_status=$?
if [[ $setup_status -ne 0 ]]; then
	exit "$setup_status"
fi
run_phase_tests setup "${setup_test_paths[@]}"
cleanup_status=0
timeout \
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
run_phase_tests cleanup e2e-tests/test_cleanup.py
if [[ $capture_status -ne 0 ]]; then
	exit "$capture_status"
fi
