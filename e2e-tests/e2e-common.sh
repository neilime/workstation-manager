# shellcheck shell=bash

E2E_VM_NAME=""
E2E_BRANCH_NAME=""
E2E_REPOSITORY_PATH=""
E2E_REPOSITORY_URL=""
E2E_ENTRYPOINT_SCRIPT_URL=""

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
	limactl shell --workdir / "$E2E_VM_NAME" env sh -lc 'printenv HOME' | tr -d '\r'
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

	origin_url="$(git -C "$workspace_dir" config --get remote.origin.url)"
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

run_e2e_workstation_action() {
	local action_name="$1"
	local env_args=()
	shift

	env_args+=("$@")

	stream_e2e_entrypoint_script |
		limactl shell --workdir / "$E2E_VM_NAME" \
			env \
			REPOSITORY_URL="$E2E_REPOSITORY_URL" \
			REPOSITORY_BRANCH="$E2E_BRANCH_NAME" \
			"${env_args[@]}" \
			sh -s -- "$action_name"
}
