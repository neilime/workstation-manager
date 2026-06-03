# shellcheck shell=bash

E2E_VM_NAME="${E2E_VM_NAME:-}"
E2E_BRANCH_NAME="${E2E_BRANCH_NAME:-}"
E2E_REPOSITORY_PATH="${E2E_REPOSITORY_PATH:-}"
E2E_REPOSITORY_URL="${E2E_REPOSITORY_URL:-}"
E2E_ENTRYPOINT_SCRIPT_URL="${E2E_ENTRYPOINT_SCRIPT_URL:-}"

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

resolve_e2e_instance_dir() {
	printf '%s\n' "$HOME/.lima/$E2E_VM_NAME"
}

resolve_e2e_cloud_config_path() {
	printf '%s\n' "$(resolve_e2e_instance_dir)/cloud-config.yaml"
}

resolve_e2e_cloud_config_value() {
	local field_name="$1"
	local cloud_config_path=""

	cloud_config_path="$(resolve_e2e_cloud_config_path)"
	if [[ ! -f "$cloud_config_path" ]]; then
		return 1
	fi

	awk -v field_name="$field_name" '
		$1 == "-" && $2 == "name:" && user_section_started == 0 {
			user_section_started = 1
			current_name = $3
			gsub(/^"|"$/, "", current_name)
			if (field_name == "name") {
				print current_name
				exit
			}
		}
		user_section_started == 1 && $1 == field_name ":" {
			value = $2
			gsub(/^"|"$/, "", value)
			print value
			exit
		}
	' "$cloud_config_path"
}

resolve_e2e_target_user_entry() {
	local passwd_entry=""
	local target_user=""
	local target_user_id=""
	local target_user_home=""

	target_user="$(resolve_e2e_cloud_config_value name || true)"
	target_user_id="$(resolve_e2e_cloud_config_value uid || true)"
	target_user_home="$(resolve_e2e_cloud_config_value homedir || true)"
	if [[ -n "$target_user" && -n "$target_user_id" && -n "$target_user_home" ]]; then
		printf '%s:x:%s:::%s:/bin/bash\n' "$target_user" "$target_user_id" "$target_user_home"
		return 0
	fi

	passwd_entry="$(limactl shell --workdir / "$E2E_VM_NAME" env sh -lc 'getent passwd 1000' | tr -d '\r')"
	if [[ -z "$passwd_entry" ]]; then
		printf '%s\n' 'failed to resolve e2e desktop user from uid 1000' >&2
		return 1
	fi

	printf '%s\n' "$passwd_entry"
}

resolve_e2e_target_user_home() {
	resolve_e2e_target_user_entry | cut -d: -f6
}

resolve_e2e_target_user() {
	resolve_e2e_target_user_entry | cut -d: -f1

}

resolve_e2e_target_user_id() {
	resolve_e2e_target_user_entry | cut -d: -f3
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
			-H "Authorization: Bearer ${WORKSTATION_MANAGER_GITHUB_TOKEN}" \
			-H "Accept: application/vnd.github.raw" \
			"https://api.github.com/repos/${E2E_REPOSITORY_PATH}/contents/workstation.sh?ref=${E2E_BRANCH_NAME}"
		return
	fi

	curl -fsSL "$E2E_ENTRYPOINT_SCRIPT_URL"
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
	limactl shell --workdir / "$E2E_VM_NAME" env sh -lc "$1"
}

copy_e2e_vm_file() {
	local remote_path="$1"
	local local_path="$2"

	require_e2e_command base64
	mkdir -p "$(dirname "$local_path")"
	if run_e2e_vm_shell "base64 -w 0 '$remote_path'" | base64 -d >"$local_path"; then
		return 0
	fi
	rm -f "$local_path"
	return 1
}

write_e2e_placeholder_png() {
	local output_path="$1"

	mkdir -p "$(dirname "$output_path")"
	cat <<'EOF' | base64 -d >"$output_path"
iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAK0lEQVR42mN4+fQWTRHDqAWjFoxaMGrBqAWjFoxaMGrBqAWjFoxaMFQsAAAOkqCXNXhYbQAAAABJRU5ErkJggg==
EOF
}

capture_e2e_vm_desktop() {
	local capture_name="$1"
	local output_dir="$2"
	local target_user=""
	local target_user_id=""
	local target_user_home=""
	local remote_image_path="/tmp/${capture_name}.png"
	local remote_log_path="/tmp/${capture_name}.log"
	local remote_script_path="/tmp/${capture_name}.sh"
	local local_image_path="$output_dir/${capture_name}.png"
	local local_log_path="$output_dir/${capture_name}.log"
	local capture_exit_code=0
	local remote_capture_command=""

	mkdir -p "$output_dir"
	target_user="$(resolve_e2e_target_user)"
	target_user_id="$(resolve_e2e_target_user_id)"
	target_user_home="$(resolve_e2e_target_user_home)"
	remote_capture_command="$({
		cat <<EOF
REMOTE_IMAGE_PATH=$(printf '%q' "$remote_image_path")
REMOTE_LOG_PATH=$(printf '%q' "$remote_log_path")
REMOTE_SCRIPT_PATH=$(printf '%q' "$remote_script_path")
TARGET_USER=$(printf '%q' "$target_user")
TARGET_USER_ID=$(printf '%q' "$target_user_id")
TARGET_USER_HOME=$(printf '%q' "$target_user_home")
EOF
		cat <<'REMOTE_CAPTURE_SCRIPT'
set -eu
rm -f "$REMOTE_IMAGE_PATH" "$REMOTE_LOG_PATH" "$REMOTE_SCRIPT_PATH"
cat >"$REMOTE_SCRIPT_PATH" <<'SCRIPT'
#!/usr/bin/env bash

set -euo pipefail

capture_path="$1"
runtime_dir="/run/user/$TARGET_USER_ID"
display_value=":0"
dbus_session_bus_address="unix:path=$runtime_dir/bus"
xauthority_path="$TARGET_USER_HOME/.Xauthority"
capture_path_env='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
gsettings_available=0

export PATH="$capture_path_env"

for command_name in pgrep systemctl; do
	command -v "$command_name" >/dev/null 2>&1 || {
		printf '%s\n' "$command_name is required for desktop capture" >&2
		exit 1
	}
done

if ! command -v gnome-screenshot >/dev/null 2>&1 \
	&& ! command -v gdbus >/dev/null 2>&1 \
	&& ! command -v import >/dev/null 2>&1; then
	printf '%s\n' 'desktop capture requires gnome-screenshot, gdbus, or import' >&2
	exit 1
fi

if command -v gsettings >/dev/null 2>&1; then
	gsettings_available=1
fi

export HOME="$TARGET_USER_HOME"
export USER="$TARGET_USER"
export LOGNAME="$TARGET_USER"
export XDG_CACHE_HOME="$HOME/.cache"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_DATA_HOME="$HOME/.local/share"

load_capture_environment() {
	local candidate_pid=''
	local env_name=''
	local env_value=''
	local candidate_display=''
	local candidate_dbus=''
	local candidate_xauthority=''
	local candidate_runtime_dir=''
	local candidate_session_type='x11'
	local candidate_desktop='ubuntu'
	local session_pid=''

	while IFS= read -r candidate_pid; do
		[[ -r "/proc/$candidate_pid/environ" ]] || continue
		candidate_display=''
		candidate_dbus=''
		candidate_xauthority=''
		candidate_runtime_dir=''
		candidate_session_type='x11'
		candidate_desktop='ubuntu'

		while IFS='=' read -r env_name env_value; do
			case "$env_name" in
			DISPLAY)
				candidate_display="$env_value"
				;;
			DBUS_SESSION_BUS_ADDRESS)
				candidate_dbus="$env_value"
				;;
			XAUTHORITY)
				candidate_xauthority="$env_value"
				;;
			XDG_RUNTIME_DIR)
				candidate_runtime_dir="$env_value"
				;;
			XDG_SESSION_TYPE)
				candidate_session_type="$env_value"
				;;
			DESKTOP_SESSION | XDG_SESSION_DESKTOP)
				candidate_desktop="$env_value"
				;;
			esac
		done < <(tr '\0' '\n' </proc/"$candidate_pid"/environ)

		if [[ -n "$candidate_display" ]]; then
			display_value="$candidate_display"
			if [[ -n "$candidate_dbus" ]]; then
				dbus_session_bus_address="$candidate_dbus"
			fi
			if [[ -n "$candidate_xauthority" ]]; then
				xauthority_path="$candidate_xauthority"
			fi
			if [[ -n "$candidate_runtime_dir" ]]; then
				runtime_dir="$candidate_runtime_dir"
			fi
			export DISPLAY="$display_value"
			export DBUS_SESSION_BUS_ADDRESS="$dbus_session_bus_address"
			export XDG_RUNTIME_DIR="$runtime_dir"
			export XAUTHORITY="$xauthority_path"
			export XDG_CURRENT_DESKTOP='ubuntu:GNOME'
			export XDG_SESSION_DESKTOP="$candidate_desktop"
			export XDG_SESSION_TYPE="$candidate_session_type"
			export DESKTOP_SESSION="$candidate_desktop"
			export GSETTINGS_BACKEND='dconf'
			export NO_AT_BRIDGE='1'
			return 0
		fi
	 done < <(
		{
			pgrep -u "$TARGET_USER" -x gnome-shell 2>/dev/null || true
			pgrep -u "$TARGET_USER" -x gnome-session-binary 2>/dev/null || true
			pgrep -u "$TARGET_USER" -x gnome-session 2>/dev/null || true
			pgrep -u "$TARGET_USER" -x Xorg 2>/dev/null || true
			pgrep -u "$TARGET_USER" -x Xwayland 2>/dev/null || true
			pgrep -u "$TARGET_USER" -f gdm-x-session 2>/dev/null || true
		} | awk '!seen[$0]++'
	)

	export DISPLAY="$display_value"
	export DBUS_SESSION_BUS_ADDRESS="$dbus_session_bus_address"
	export XDG_RUNTIME_DIR="$runtime_dir"
	export XAUTHORITY="$xauthority_path"
	export XDG_CURRENT_DESKTOP='ubuntu:GNOME'
	export XDG_SESSION_DESKTOP='ubuntu'
	export XDG_SESSION_TYPE='x11'
	export DESKTOP_SESSION='ubuntu'
	export GSETTINGS_BACKEND='dconf'
	export NO_AT_BRIDGE='1'
	return 1
}

load_capture_environment || true

if [[ "$gsettings_available" -eq 1 ]]; then
	gsettings set org.gnome.desktop.notifications show-banners false || true
	gsettings set org.gnome.desktop.notifications show-in-lock-screen false || true
fi

capture_desktop() {
	if command -v gnome-screenshot >/dev/null 2>&1; then
		gnome-screenshot --file "$capture_path" >/dev/null 2>&1
		return
	fi

	if command -v gdbus >/dev/null 2>&1; then
		gdbus call \
			--session \
			--dest org.gnome.Shell.Screenshot \
			--object-path /org/gnome/Shell/Screenshot \
			--method org.gnome.Shell.Screenshot.Screenshot \
			false \
			false \
			"$capture_path" >/dev/null 2>&1 && return
	fi

	import -display "$DISPLAY" -window root "$capture_path" >/dev/null 2>&1
}

for attempt in $(seq 1 60); do
	if systemctl is-active --quiet gdm3; then
		load_capture_environment || true
		if [[ "$gsettings_available" -eq 1 ]]; then
			gsettings set org.gnome.desktop.notifications show-banners false || true
			gsettings set org.gnome.desktop.notifications show-in-lock-screen false || true
		fi
		if capture_desktop && [ -s "$capture_path" ]; then
			exit 0
		fi
	fi
	sleep 2
done

printf '%s\n' 'desktop capture failed after waiting for graphical session' >&2
exit 1
SCRIPT
chmod 0700 "$REMOTE_SCRIPT_PATH"
sudo -u "$TARGET_USER" env \
	TARGET_USER="$TARGET_USER" \
	TARGET_USER_ID="$TARGET_USER_ID" \
	TARGET_USER_HOME="$TARGET_USER_HOME" \
	HOME="$TARGET_USER_HOME" \
	PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
	USER="$TARGET_USER" \
	LOGNAME="$TARGET_USER" \
	bash "$REMOTE_SCRIPT_PATH" "$REMOTE_IMAGE_PATH" >"$REMOTE_LOG_PATH" 2>&1
REMOTE_CAPTURE_SCRIPT
	})"

	if run_e2e_vm_shell "$remote_capture_command"; then
		capture_exit_code=0
	else
		capture_exit_code=$?
	fi

	copy_e2e_vm_file "$remote_log_path" "$local_log_path" || {
		printf '%s\n' "Desktop capture log was not available for $capture_name" >"$local_log_path"
	}

	if [[ "$capture_exit_code" -ne 0 ]]; then
		return "$capture_exit_code"
	fi

	copy_e2e_vm_file "$remote_image_path" "$local_image_path" || {
		return 1
	}
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
		limactl shell --workdir / "$E2E_VM_NAME" \
			env \
			REPOSITORY_URL="$E2E_REPOSITORY_URL" \
			REPOSITORY_BRANCH="$E2E_BRANCH_NAME" \
			"${env_args[@]}" \
			sh -s -- "$action_name"
}
