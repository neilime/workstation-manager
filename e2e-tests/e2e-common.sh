# shellcheck shell=bash

E2E_VM_NAME="${E2E_VM_NAME:-}"
E2E_BRANCH_NAME="${E2E_BRANCH_NAME:-}"
E2E_REPOSITORY_PATH="${E2E_REPOSITORY_PATH:-}"
E2E_REPOSITORY_URL="${E2E_REPOSITORY_URL:-}"
E2E_ENTRYPOINT_SCRIPT_URL="${E2E_ENTRYPOINT_SCRIPT_URL:-}"
E2E_CONTROL_COMMAND_TIMEOUT_SECONDS="${E2E_CONTROL_COMMAND_TIMEOUT_SECONDS:-20}"
E2E_DETACHED_ACTION_TIMEOUT_SECONDS="${E2E_DETACHED_ACTION_TIMEOUT_SECONDS:-600}"
E2E_TRANSPORT_FAILURE_TIMEOUT_SECONDS="${E2E_TRANSPORT_FAILURE_TIMEOUT_SECONDS:-120}"

require_e2e_command() {
	local command_name="$1"

	command -v "$command_name" >/dev/null 2>&1 || {
		printf '%s\n' "$command_name is required" >&2
		return 1
	}
}

resolve_e2e_workspace_dir() {
	cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd
}

resolve_e2e_target_user_home() {
	run_e2e_lima_shell env sh -lc 'printenv HOME' | tr -d '\r'
}

resolve_e2e_instance_dir() {
	printf '%s\n' "$HOME/.lima/$E2E_VM_NAME"
}

resolve_e2e_qmp_socket_path() {
	printf '%s\n' "$(resolve_e2e_instance_dir)/qmp.sock"
}

resolve_e2e_ssh_command() {
	printf '%s\n' "$(resolve_e2e_workspace_dir)/e2e-tests/lima-ssh.sh"
}

run_e2e_lima_shell() {
	local ssh_command=""

	ssh_command="$(resolve_e2e_ssh_command)"
	if [[ ! -x "$ssh_command" ]]; then
		printf '%s\n' "Lima SSH wrapper is not executable: $ssh_command" >&2
		return 1
	fi

	SSH="$ssh_command" limactl shell --workdir / "$E2E_VM_NAME" "$@"
}

run_e2e_lima_control_command() {
	local timeout_seconds="${1:-$E2E_CONTROL_COMMAND_TIMEOUT_SECONDS}"
	local ssh_command=""
	shift

	require_e2e_command timeout
	ssh_command="$(resolve_e2e_ssh_command)"
	if [[ ! -x "$ssh_command" ]]; then
		printf '%s\n' "Lima SSH wrapper is not executable: $ssh_command" >&2
		return 1
	fi

	SSH="$ssh_command" timeout \
		--kill-after=5s \
		"${timeout_seconds}s" \
		limactl shell --workdir / "$E2E_VM_NAME" "$@"
}

resolve_github_repository_path() {
	local origin_url="$1"
	local repo_path=""

	case "$origin_url" in
	git@github.com:*)
		repo_path="${origin_url#git@github.com:}"
		;;
	https://github.com/*)
		repo_path="${origin_url#https://github.com/}"
		;;
	*)
		return 1
		;;
	esac

	printf '%s\n' "${repo_path%.git}"
}

require_e2e_env_vars() {
	local missing_names=()
	local env_name=""

	for env_name in "$@"; do
		if [[ -z "${!env_name:-}" ]]; then
			missing_names+=("$env_name")
		fi
	done

	if [[ ${#missing_names[@]} -eq 0 ]]; then
		return
	fi

	printf '%s\n' "${missing_names[*]} are required for this e2e action" >&2
	return 1
}

stream_e2e_entrypoint_script() {
	if [[ -n "${WORKSTATION_MANAGER_GITHUB_TOKEN:-}" ]]; then
		curl -fsSL \
			--connect-timeout 10 \
			--max-time 30 \
			-H "Authorization: Bearer ${WORKSTATION_MANAGER_GITHUB_TOKEN}" \
			-H "Accept: application/vnd.github.raw" \
			"https://api.github.com/repos/${E2E_REPOSITORY_PATH}/contents/workstation.sh?ref=${E2E_BRANCH_NAME}"
		return
	fi

	curl -fsSL \
		--connect-timeout 10 \
		--max-time 30 \
		"$E2E_ENTRYPOINT_SCRIPT_URL"
}

print_e2e_vm_diagnostics() {
	local instance_dir=""
	local log_path=""

	instance_dir="$(resolve_e2e_instance_dir)"
	printf '%s\n' "Lima instance state:"
	limactl list "$E2E_VM_NAME" 2>&1 || true
	for log_path in "$instance_dir/serial.log" "$instance_dir/ha.stderr.log"; do
		if [[ ! -f "$log_path" ]]; then
			continue
		fi
		printf '%s\n' "Last 120 lines of $log_path:"
		tail -n 120 "$log_path" || true
	done
}

resolve_e2e_workstation_context() {
	local vm_name="$1"
	local branch_name=""
	local origin_url=""
	local repo_path=""
	local workspace_dir=""

	require_e2e_command curl
	require_e2e_command git

	workspace_dir="$(resolve_e2e_workspace_dir)"
	if [[ ! -f "$workspace_dir/workstation.sh" ]]; then
		printf '%s\n' "workstation.sh is required in the workspace root for e2e actions" >&2
		return 1
	fi

	origin_url="${E2E_REPOSITORY_URL:-$(git -C "$workspace_dir" config --get remote.origin.url)}"
	if [[ -z "$origin_url" ]]; then
		printf '%s\n' "git remote.origin.url is required for e2e actions" >&2
		return 1
	fi
	repo_path="$(resolve_github_repository_path "$origin_url")" || {
		printf '%s\n' "unsupported origin URL for e2e actions: $origin_url" >&2
		return 1
	}

	branch_name="${E2E_REPOSITORY_REF:-$(git -C "$workspace_dir" branch --show-current)}"
	if [[ -z "$branch_name" ]]; then
		branch_name="$(git -C "$workspace_dir" rev-parse HEAD)"
	fi

	E2E_VM_NAME="$vm_name"
	E2E_BRANCH_NAME="$branch_name"
	E2E_REPOSITORY_PATH="$repo_path"
	E2E_REPOSITORY_URL="https://github.com/${repo_path}.git"
	E2E_ENTRYPOINT_SCRIPT_URL="https://raw.githubusercontent.com/${repo_path}/${branch_name}/workstation.sh"
}

run_e2e_vm_shell() {
	run_e2e_lima_shell env sh -lc "$1"
}

restart_e2e_desktop_session() {
	local desktop_user_id=""
	local old_shell_pid=""
	local new_shell_pid=""

	desktop_user_id="$(run_e2e_lima_control_command 10 id -u | tr -d '\r')"
	old_shell_pid="$(
		run_e2e_lima_control_command 10 \
			pgrep --euid "$desktop_user_id" --oldest --exact gnome-shell 2>/dev/null |
			tr -d '\r' || true
	)"
	run_e2e_lima_control_command 30 sudo -n systemctl restart gdm3

	for _attempt in $(seq 1 45); do
		new_shell_pid="$(
			run_e2e_lima_control_command 10 \
				pgrep --euid "$desktop_user_id" --oldest --exact gnome-shell 2>/dev/null |
				tr -d '\r' || true
		)"
		if [[ -n "$new_shell_pid" && "$new_shell_pid" != "$old_shell_pid" ]]; then
			return 0
		fi
		sleep 2
	done

	printf '%s\n' "GNOME did not return after restarting gdm3" >&2
	return 1
}

wait_for_e2e_user_process() {
	local process_name="$1"
	local desktop_user_id=""

	desktop_user_id="$(run_e2e_lima_control_command 10 id -u | tr -d '\r')"

	for _attempt in $(seq 1 30); do
		if run_e2e_lima_control_command 10 \
			pgrep --euid "$desktop_user_id" --exact "$process_name" >/dev/null; then
			return 0
		fi
		sleep 2
	done

	printf '%s\n' "$process_name did not start in the graphical user session" >&2
	return 1
}

capture_e2e_vm_desktop() {
	local capture_name="$1"
	local output_dir="$2"
	local qmp_socket_path=""
	local ppm_path=""
	local local_image_path=""
	local local_log_path=""
	local screenshot_tool=""

	require_e2e_command python3
	mkdir -p "$output_dir"
	output_dir="$(cd -- "$output_dir" && pwd)"
	qmp_socket_path="$(resolve_e2e_qmp_socket_path)"
	ppm_path="$output_dir/${capture_name}.ppm"
	local_image_path="$output_dir/${capture_name}.png"
	local_log_path="$output_dir/${capture_name}.log"
	screenshot_tool="$(resolve_e2e_workspace_dir)/e2e-tests/qemu_screenshot.py"

	rm -f "$ppm_path" "$local_image_path" "${local_image_path}.tmp"
	: >"$local_log_path"
	if [[ ! -S "$qmp_socket_path" ]]; then
		printf '%s\n' "QMP socket is not available: $qmp_socket_path" >"$local_log_path"
		return 1
	fi
	if ! run_e2e_lima_control_command 20 \
		sudo -n loginctl unlock-sessions >>"$local_log_path" 2>&1; then
		printf '%s\n' \
			"warning: could not unlock the graphical session before capture" \
			>>"$local_log_path"
	fi

	for attempt in $(seq 1 30); do
		printf 'attempt=%s\n' "$attempt" >>"$local_log_path"
		if python3 "$screenshot_tool" \
			"$qmp_socket_path" \
			"$ppm_path" \
			"$local_image_path" >>"$local_log_path" 2>&1; then
			rm -f "$ppm_path"
			return 0
		fi
		sleep 2
	done

	rm -f "$ppm_path"
	return 1
}

run_e2e_workstation_action() {
	local action_name="$1"
	local env_args=()
	shift

	env_args+=("$@")
	if [[ -n "${WORKSTATION_MANAGER_GITHUB_TOKEN:-}" ]]; then
		env_args+=("WORKSTATION_MANAGER_GITHUB_TOKEN=${WORKSTATION_MANAGER_GITHUB_TOKEN}")
	fi

	stream_e2e_entrypoint_script |
		run_e2e_lima_shell \
			env \
			REPOSITORY_URL="$E2E_REPOSITORY_URL" \
			REPOSITORY_BRANCH="$E2E_BRANCH_NAME" \
			"${env_args[@]}" \
			sh -s -- "$action_name"
}

run_e2e_detached_workstation_action() {
	local action_name="$1"
	local active_state=""
	local action_deadline=0
	local action_started_at=0
	local action_timed_out=false
	local env_arg=""
	local env_args=()
	local exit_status=""
	local guest_user=""
	local guest_user_home=""
	local last_status_summary=""
	local remote_script=""
	local remaining_seconds=0
	local result=""
	local status_code=0
	local status_output=""
	local status_summary=""
	local sub_state=""
	local systemd_env_args=()
	local transport_failed=false
	local unreachable_since=-1
	local unit_name=""
	shift
	action_started_at=$SECONDS
	action_deadline=$((action_started_at + E2E_DETACHED_ACTION_TIMEOUT_SECONDS))

	env_args+=("$@")
	if [[ -n "${WORKSTATION_MANAGER_GITHUB_TOKEN:-}" ]]; then
		env_args+=("WORKSTATION_MANAGER_GITHUB_TOKEN=${WORKSTATION_MANAGER_GITHUB_TOKEN}")
	fi

	unit_name="workstation-manager-e2e-${action_name}"
	remote_script="/tmp/${unit_name}.sh"
	guest_user="$(run_e2e_lima_control_command 30 id -un | tr -d '\r')"
	guest_user_home="$(run_e2e_lima_control_command 30 env sh -lc 'printenv HOME' | tr -d '\r')"
	for env_arg in \
		"REPOSITORY_URL=$E2E_REPOSITORY_URL" \
		"REPOSITORY_BRANCH=$E2E_BRANCH_NAME" \
		"HOME=$guest_user_home" \
		"USER=$guest_user" \
		"LOGNAME=$guest_user" \
		"${env_args[@]}"; do
		systemd_env_args+=("--setenv=$env_arg")
	done

	stream_e2e_entrypoint_script |
		run_e2e_lima_control_command 30 sh -c "umask 077; cat >\"$remote_script\""

	run_e2e_lima_control_command 30 \
		sudo -n systemd-run \
		--unit="$unit_name" \
		--uid="$guest_user" \
		--property=Type=exec \
		--property=RemainAfterExit=yes \
		--property="RuntimeMaxSec=${E2E_DETACHED_ACTION_TIMEOUT_SECONDS}s" \
		--property=TimeoutStopSec=15s \
		--property=KillMode=mixed \
		--property=StandardOutput=journal+console \
		--property=StandardError=journal+console \
		"${systemd_env_args[@]}" \
		/bin/sh "$remote_script" "$action_name"

	printf '%s\n' \
		"Waiting up to ${E2E_DETACHED_ACTION_TIMEOUT_SECONDS}s for ${unit_name}.service"
	while ((SECONDS < action_deadline)); do
		status_code=0
		status_output="$(
			run_e2e_lima_control_command \
				"$E2E_CONTROL_COMMAND_TIMEOUT_SECONDS" \
				sudo -n systemctl show "${unit_name}.service" \
				--property=ActiveState \
				--property=SubState \
				--property=Result \
				--property=ExecMainStatus 2>&1
		)" || status_code=$?
		if [[ $status_code -eq 0 ]]; then
			unreachable_since=-1
			active_state="$(printf '%s\n' "$status_output" | sed -n 's/^ActiveState=//p')"
			sub_state="$(printf '%s\n' "$status_output" | sed -n 's/^SubState=//p')"
			result="$(printf '%s\n' "$status_output" | sed -n 's/^Result=//p')"
			exit_status="$(printf '%s\n' "$status_output" | sed -n 's/^ExecMainStatus=//p')"
			status_summary="ActiveState=${active_state:-unknown}, SubState=${sub_state:-unknown}, Result=${result:-unknown}, ExecMainStatus=${exit_status:-unknown}"
		else
			active_state=""
			sub_state=""
			result=""
			exit_status=""
			if ((unreachable_since < 0)); then
				unreachable_since=$SECONDS
			fi
			status_summary="Cleanup status probe failed (rc=$status_code, unavailable for $((SECONDS - unreachable_since))s): ${status_output:-no diagnostic output}"
		fi

		remaining_seconds=$((action_deadline - SECONDS))
		printf '%s\n' \
			"Cleanup heartbeat: elapsed=$((SECONDS - action_started_at))s remaining=${remaining_seconds}s; $status_summary"
		last_status_summary="$status_summary"

		if [[ "$sub_state" == "exited" || "$active_state" == "failed" ]]; then
			break
		fi
		if ((unreachable_since >= 0 && SECONDS - unreachable_since >= E2E_TRANSPORT_FAILURE_TIMEOUT_SECONDS)); then
			transport_failed=true
			break
		fi
		if ((remaining_seconds > 5)); then
			sleep 5
		elif ((remaining_seconds > 0)); then
			sleep "$remaining_seconds"
		fi
	done

	if [[ "$transport_failed" == true ]]; then
		printf '%s\n' \
			"Lost access to the E2E VM for ${E2E_TRANSPORT_FAILURE_TIMEOUT_SECONDS}s during ${action_name}" >&2
		print_e2e_vm_diagnostics >&2
		return 1
	fi

	if [[ "$sub_state" != "exited" && "$active_state" != "failed" ]]; then
		action_timed_out=true
	fi

	run_e2e_lima_control_command 60 \
		sudo -n journalctl --unit="${unit_name}.service" --no-pager --output=cat || true
	run_e2e_lima_control_command 30 \
		sudo -n systemctl stop "${unit_name}.service" >/dev/null 2>&1 || true
	run_e2e_lima_control_command 30 rm -f "$remote_script" || true

	if [[ "$action_timed_out" == true ]]; then
		printf '%s\n' \
			"Detached ${action_name} exceeded its ${E2E_DETACHED_ACTION_TIMEOUT_SECONDS}s deadline; last status: ${last_status_summary:-unavailable}" >&2
		return 1
	fi

	if [[ "$active_state" != "active" || "$sub_state" != "exited" ||
		"$result" != "success" || "$exit_status" != "0" ]]; then
		printf '%s\n' \
			"Detached ${action_name} failed: ActiveState=${active_state:-unknown}, SubState=${sub_state:-unknown}, Result=${result:-unknown}, ExecMainStatus=${exit_status:-unknown}" >&2
		return 1
	fi
}
