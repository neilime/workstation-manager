#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
vm_name="${1:-workstation-manager-v1}"
ssh_host="lima-${vm_name}"
tooling_image="${TOOLING_IMAGE:-workstation-manager-tooling:local}"
host_home="${HOME}"
workspace_dir="$(cd -- "$script_dir/.." && pwd)"
ssh_config_path="${host_home}/.lima/${vm_name}/ssh.config"
report_dir="${REPORTS_DIR:-}"
setup_test_paths=()

for test_path in e2e-tests/test_*.py; do
	case "$(basename "$test_path")" in
	test_backup.py | test_cleanup.py) ;;
	*)
		setup_test_paths+=("$test_path")
		;;
	esac
done
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
bash "$script_dir/e2e-setup.sh" "$vm_name"
run_phase_tests setup "${setup_test_paths[@]}"
bash "$script_dir/e2e-cleanup.sh" "$vm_name"
run_phase_tests cleanup e2e-tests/test_cleanup.py
