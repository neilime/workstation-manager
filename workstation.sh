#!/usr/bin/env sh

set -eu

REPOSITORY_URL="${REPOSITORY_URL:-}"
REPOSITORY_BRANCH="${REPOSITORY_BRANCH:-}"
ANSIBLE_CHECKOUT_DIR="/tmp/workstation-manager-v1"
TARGET_USER=""
TARGET_USER_HOME=""
COLLECTIONS_INSTALL_DIR=""
DEFAULT_REPOSITORY_URL="https://github.com/neilime/workstation-manager.git"
DEFAULT_REPOSITORY_BRANCH="main"
PRIVATE_OVERRIDE_LOCAL_FILE="${WORKSTATION_MANAGER_PRIVATE_OVERRIDE_FILE:-}"
PRIVATE_OVERRIDE_TEMP_DIR=""
GITHUB_TOKEN_VALUE="${WORKSTATION_MANAGER_GITHUB_TOKEN:-}"
BACKUP_OUTPUT_DIR="${WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR:-}"
RESTORE_ARCHIVE_PATH="${WORKSTATION_MANAGER_RESTORE_ARCHIVE:-}"
PROMPTED_BACKUP_OUTPUT_DIR=""
PROMPTED_BITWARDEN_EMAIL=""
BITWARDEN_CLIENT_ID_VALUE="${BITWARDEN_CLIENT_ID:-}"
BITWARDEN_CLIENT_SECRET_VALUE="${BITWARDEN_CLIENT_SECRET:-}"
BITWARDEN_PASSWORD_VALUE="${BITWARDEN_PASSWORD:-}"
BITWARDEN_EMAIL_PASSWORD_REJECTED_MARKER="WORKSTATION_MANAGER_BITWARDEN_EMAIL_PASSWORD_REJECTED"
BITWARDEN_PASSWORD_REJECTED_MARKER="WORKSTATION_MANAGER_BITWARDEN_PASSWORD_REJECTED"

PRIVATE_OVERRIDE_REPOSITORY_URL="https://github.com/neilime/workstation-config.git"
PRIVATE_OVERRIDE_REPOSITORY_BRANCH="main"
PRIVATE_OVERRIDE_REPOSITORY_PATH="ansible/private.override.yml"

info() {
	printf '%s\n' "> $*"
}

fail() {
	printf '%s\n' "x $*" >&2
	exit 1
}

cleanup() {
	if [ -n "$PRIVATE_OVERRIDE_TEMP_DIR" ] && [ -d "$PRIVATE_OVERRIDE_TEMP_DIR" ]; then
		rm -rf "$PRIVATE_OVERRIDE_TEMP_DIR"
	fi
}

trap cleanup EXIT

has_interactive_terminal() {
	# A /dev/tty device can exist even when this process has no controlling terminal.
	(: </dev/tty) 2>/dev/null
}

print_to_tty() {
	printf '%s' "$1" >/dev/tty
}

println_to_tty() {
	printf '%s\n' "$1" >/dev/tty
}

prompt_from_tty() (
	prompt_text="$1"
	secret_prompt="$2"
	prompt_value=""

	has_interactive_terminal || return 1

	if [ "$secret_prompt" = "1" ]; then
		# Only echo changes; some stty implementations cannot restore their -g output.
		tty_settings="$(LC_ALL=C stty -a </dev/tty)" || return 1
		case " $tty_settings " in
		*[[:space:]]-echo[[:space:]\;]*) tty_echo="-echo" ;;
		*[[:space:]]echo[[:space:]\;]*) tty_echo="echo" ;;
		*) return 1 ;;
		esac
		# Keep these traps local to the prompt, including on EOF and interruption.
		trap 'stty "$tty_echo" </dev/tty || exit 1; println_to_tty ""' EXIT
		trap 'exit 1' HUP INT TERM
		stty -echo </dev/tty || return 1
	fi

	print_to_tty "$prompt_text" || return 1
	IFS= read -r prompt_value </dev/tty || return 1
	printf '%s' "$prompt_value"
)

prompt_for_required_value() {
	prompt_name="$1"
	prompt_text="$2"
	secret_prompt="$3"
	prompt_value=""

	while [ -z "$prompt_value" ]; do
		prompt_value="$(prompt_from_tty "$prompt_text" "$secret_prompt")" ||
			fail "Failed to read $prompt_name from the terminal"
		if [ -z "$prompt_value" ]; then
			println_to_tty "x $prompt_name cannot be empty"
		fi
	done

	printf '%s' "$prompt_value"
}

interactive_terminal_flag() {
	if has_interactive_terminal; then
		printf '1\n'
		return
	fi

	printf '0\n'
}

shell_quote() {
	printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\''/g")"
}

usage() {
	cat <<EOF
Usage: workstation.sh [setup] [--dry-run] | workstation.sh cleanup [--dry-run] | workstation.sh backup [--dry-run]

Default behavior:
	With no command, run the setup action.

Commands:
	setup            Bootstrap dependencies and converge the workstation.
	cleanup          Clean removable workstation artifacts and report drift.
	backup           Create a workstation backup archive instead of converging state.
	help             Show this help message.

Options:
	--dry-run        Preview the selected action in Ansible check mode.

CI environment overrides:
	REPOSITORY_URL                    GitHub repository source for the hidden checkout.
	REPOSITORY_BRANCH                 Branch, tag, or commit to apply.
	WORKSTATION_MANAGER_GITHUB_TOKEN        Optional GitHub token for private GitHub repositories.
	WORKSTATION_MANAGER_PRIVATE_OVERRIDE_FILE  Optional local private override file.
	WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR   Optional backup output directory for non-interactive runs.
	WORKSTATION_MANAGER_RESTORE_ARCHIVE     Optional backup archive path to replay during setup.
	BITWARDEN_CLIENT_ID               Bitwarden API client ID for secret restore.
	BITWARDEN_CLIENT_SECRET           Bitwarden API client secret for secret restore.
	BITWARDEN_PASSWORD                Bitwarden vault password for secret restore.

Examples:
	curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- setup
	curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- setup --dry-run
	curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | WORKSTATION_MANAGER_RESTORE_ARCHIVE=/path/to/workstation-manager-backup.tar.gz sh -s -- setup
	curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- cleanup --dry-run
	curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- backup --dry-run
EOF
}

require_command() {
	command -v "$1" >/dev/null 2>&1 || fail "$1 is required"
}

require_sudo() {
	require_command sudo
	sudo -v || fail "sudo access is required"
}

resolve_target_user_home() {
	resolved_target_user="$1"

	if command -v getent >/dev/null 2>&1; then
		resolved_home="$(getent passwd "$resolved_target_user" | cut -d: -f6)"
		if [ -n "$resolved_home" ]; then
			printf '%s\n' "$resolved_home"
			return
		fi
	fi

	if [ "$resolved_target_user" = "$(id -un)" ] && [ -n "${HOME:-}" ]; then
		printf '%s\n' "$HOME"
		return
	fi

	printf '/home/%s\n' "$resolved_target_user"
}

initialize_target_context() {
	if [ -n "$TARGET_USER" ] && [ -n "$TARGET_USER_HOME" ] && [ -n "$COLLECTIONS_INSTALL_DIR" ]; then
		return
	fi

	TARGET_USER="${SUDO_USER:-$(id -un)}"
	TARGET_USER_HOME="$(resolve_target_user_home "$TARGET_USER")"
	COLLECTIONS_INSTALL_DIR="$TARGET_USER_HOME/.ansible/collections"
}

install_ansible_packages() {
	if command -v ansible-playbook >/dev/null 2>&1 &&
		command -v ansible-pull >/dev/null 2>&1; then
		return
	fi

	require_sudo
	info "Installing bootstrap packages"
	sudo apt-get update
	sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
		ansible-core \
		ca-certificates
}

install_git() {
	if command -v git >/dev/null 2>&1; then
		return
	fi

	require_sudo
	info "Installing git (required for ansible-pull)"
	sudo apt-get update
	sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends git
}

install_github_cli() {
	if command -v gh >/dev/null 2>&1; then
		return
	fi

	require_sudo
	info "Installing GitHub CLI for private repository authentication"
	sudo apt-get update
	sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends gh ||
		fail "Failed to install GitHub CLI. Install gh manually or configure Git access to $PRIVATE_OVERRIDE_REPOSITORY_URL."
}

can_prompt_for_private_override_auth() {
	has_interactive_terminal || return 1
	[ "$1" = "setup" ] || return 1
	[ -z "$GITHUB_TOKEN_VALUE" ] || return 1
	return 0
}

prompt_for_github_cli_authentication() {
	install_github_cli

	info "Private override access requires GitHub authentication; prompting through GitHub CLI"
	println_to_tty "Complete the GitHub CLI login flow. If this machine has no browser, use the device code on another device."
	gh auth login --git-protocol https --skip-ssh-key ||
		fail "GitHub CLI authentication failed"
	gh auth setup-git ||
		fail "GitHub CLI could not configure git credentials"
}

clone_private_override_repository() {
	repository_url="$1"
	destination_dir="$2"

	GIT_TERMINAL_PROMPT=0 git clone --depth 1 --branch "$PRIVATE_OVERRIDE_REPOSITORY_BRANCH" \
		"$repository_url" "$destination_dir" >/dev/null 2>&1
}

resolve_github_repository_path() {
	repository_url="$1"

	case "$repository_url" in
	git@github.com:*)
		repository_path="${repository_url#git@github.com:}"
		;;
	https://github.com/*)
		repository_path="${repository_url#https://github.com/}"
		;;
	*)
		return 1
		;;
	esac

	repository_path="${repository_path%.git}"
	printf '%s\n' "$repository_path"
}

resolve_authenticated_repository_url() {
	repository_url="$1"

	if [ -n "$GITHUB_TOKEN_VALUE" ] &&
		repository_path="$(resolve_github_repository_path "$repository_url")"; then
		printf 'https://x-access-token:%s@github.com/%s.git\n' "$GITHUB_TOKEN_VALUE" "$repository_path"
		return
	fi

	printf '%s\n' "$repository_url"
}

resolve_local_repository_path() {
	repository_url="$1"

	case "$repository_url" in
	file://*) repository_path="${repository_url#file://}" ;;
	/*) repository_path="$repository_url" ;;
	*) return 1 ;;
	esac

	[ -d "$repository_path" ] || return 1
	printf '%s\n' "$repository_path"
}

resolve_entrypoint_repository_root() {
	command -v git >/dev/null 2>&1 || return 1
	entrypoint_source="$(resolve_entrypoint_source)" || return 1
	entrypoint_dir="$(dirname "$entrypoint_source")"
	repository_root="$(git -C "$entrypoint_dir" rev-parse --show-toplevel 2>/dev/null)" || return 1
	[ -f "$repository_root/workstation.sh" ] || return 1
	[ -f "$repository_root/ansible/collections/requirements.yml" ] || return 1
	printf '%s\n' "$repository_root"
}

resolve_local_repository_ref() {
	repository_root="$1"
	branch_name="$(git -C "$repository_root" branch --show-current 2>/dev/null || true)"
	if [ -n "$branch_name" ]; then
		printf '%s\n' "$branch_name"
		return 0
	fi

	commit_sha="$(git -C "$repository_root" rev-parse HEAD 2>/dev/null || true)"
	[ -n "$commit_sha" ] || return 1
	printf '%s\n' "$commit_sha"
}

initialize_repository_source() {
	if [ -z "$REPOSITORY_URL" ] && repository_root="$(resolve_entrypoint_repository_root)"; then
		REPOSITORY_URL="$repository_root"
		if [ -z "$REPOSITORY_BRANCH" ]; then
			REPOSITORY_BRANCH="$(resolve_local_repository_ref "$repository_root" || true)"
		fi
	fi

	if [ -z "$REPOSITORY_URL" ]; then
		REPOSITORY_URL="$DEFAULT_REPOSITORY_URL"
	fi

	if [ -z "$REPOSITORY_BRANCH" ]; then
		REPOSITORY_BRANCH="$DEFAULT_REPOSITORY_BRANCH"
	fi
}

is_full_git_commit_sha() {
	[ "${#1}" -eq 40 ] || return 1

	case "$1" in
	*[!0-9a-fA-F]*)
		return 1
		;;
	esac

	return 0
}

download_github_file() {
	repository_path="$1"
	ref_name="$2"
	repository_file="$3"
	destination="$4"

	require_command curl

	if [ -n "$GITHUB_TOKEN_VALUE" ]; then
		curl -fsSL \
			-H "Authorization: Bearer $GITHUB_TOKEN_VALUE" \
			-H "Accept: application/vnd.github.raw" \
			"https://api.github.com/repos/${repository_path}/contents/${repository_file}?ref=${ref_name}" \
			-o "$destination"
		return
	fi

	curl -fsSL \
		"https://raw.githubusercontent.com/${repository_path}/${ref_name}/${repository_file}" \
		-o "$destination"
}

install_collection_requirements() {
	requirements_file=""

	info "Installing Ansible collection dependencies"
	if repo_path="$(resolve_github_repository_path "$REPOSITORY_URL")"; then
		requirements_file="$(mktemp "${TMPDIR:-/tmp}/workstation-manager-requirements-XXXXXX.yml")"
		download_github_file "$repo_path" "$REPOSITORY_BRANCH" "ansible/collections/requirements.yml" "$requirements_file"
		ansible-galaxy collection install -r "$requirements_file" -p "$COLLECTIONS_INSTALL_DIR" >/dev/null
		rm -f "$requirements_file"
		return
	fi

	repository_root="$(resolve_local_repository_path "$REPOSITORY_URL")" ||
		fail "REPOSITORY_URL must point to a GitHub repository or local checkout"
	requirements_file="$repository_root/ansible/collections/requirements.yml"
	[ -f "$requirements_file" ] || fail "Collection requirements were not found in $repository_root"
	ansible-galaxy collection install -r "$requirements_file" -p "$COLLECTIONS_INSTALL_DIR" >/dev/null
}

prepare_private_override_file() {
	command_name="$1"

	if [ -n "$PRIVATE_OVERRIDE_LOCAL_FILE" ]; then
		return
	fi

	PRIVATE_OVERRIDE_TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/workstation-manager-private-override-XXXXXX")"
	private_override_checkout_dir="$PRIVATE_OVERRIDE_TEMP_DIR/repository"
	private_override_candidate="$private_override_checkout_dir/$PRIVATE_OVERRIDE_REPOSITORY_PATH"
	authenticated_private_override_repository_url="$(resolve_authenticated_repository_url "$PRIVATE_OVERRIDE_REPOSITORY_URL")"

	info "Fetching private override from $PRIVATE_OVERRIDE_REPOSITORY_URL#$PRIVATE_OVERRIDE_REPOSITORY_BRANCH"
	if ! clone_private_override_repository \
		"$authenticated_private_override_repository_url" \
		"$private_override_checkout_dir"; then
		if can_prompt_for_private_override_auth "$command_name"; then
			prompt_for_github_cli_authentication
			rm -rf "$private_override_checkout_dir"
			if ! clone_private_override_repository \
				"$PRIVATE_OVERRIDE_REPOSITORY_URL" \
				"$private_override_checkout_dir"; then
				fail "Failed to fetch private override repository $PRIVATE_OVERRIDE_REPOSITORY_URL even after GitHub CLI authentication."
			fi
		else
			fail "Failed to fetch private override repository $PRIVATE_OVERRIDE_REPOSITORY_URL. Ensure Git can authenticate to this private repository, authenticate with GitHub CLI during setup, or export WORKSTATION_MANAGER_GITHUB_TOKEN in CI."
		fi
	fi

	[ -f "$private_override_candidate" ] ||
		fail "Private override file $PRIVATE_OVERRIDE_REPOSITORY_PATH was not found in $PRIVATE_OVERRIDE_REPOSITORY_URL#$PRIVATE_OVERRIDE_REPOSITORY_BRANCH"

	PRIVATE_OVERRIDE_LOCAL_FILE="$private_override_candidate"
}

prompt_for_bitwarden_credentials_if_needed() {
	action_name="$1"
	action_purpose="$2"

	if [ -n "$BITWARDEN_CLIENT_ID_VALUE" ] &&
		[ -n "$BITWARDEN_CLIENT_SECRET_VALUE" ] &&
		[ -n "$BITWARDEN_PASSWORD_VALUE" ]; then
		return
	fi

	has_interactive_terminal ||
		fail "$action_name requires interactive Bitwarden login for end users, or BITWARDEN_CLIENT_ID, BITWARDEN_CLIENT_SECRET, and BITWARDEN_PASSWORD in CI"

	info "$action_purpose requires Bitwarden access; prompting for credentials"
	PROMPTED_BITWARDEN_EMAIL="$(prompt_for_required_value "BITWARDEN_EMAIL" "Bitwarden email: " 0)"
	BITWARDEN_PASSWORD_VALUE="$(prompt_for_required_value "BITWARDEN_PASSWORD" "Bitwarden vault password: " 1)"
	BITWARDEN_CLIENT_ID_VALUE=""
	BITWARDEN_CLIENT_SECRET_VALUE=""
	return
}

reprompt_for_bitwarden_credentials() {
	failure_marker="$1"

	has_interactive_terminal || return 1

	case "$failure_marker" in
	"$BITWARDEN_EMAIL_PASSWORD_REJECTED_MARKER")
		info "Bitwarden rejected the supplied email or password; prompting again"
		PROMPTED_BITWARDEN_EMAIL="$(prompt_for_required_value "BITWARDEN_EMAIL" "Bitwarden email: " 0)"
		BITWARDEN_PASSWORD_VALUE="$(prompt_for_required_value "BITWARDEN_PASSWORD" "Bitwarden vault password: " 1)"
		BITWARDEN_CLIENT_ID_VALUE=""
		BITWARDEN_CLIENT_SECRET_VALUE=""
		return
		;;
	"$BITWARDEN_PASSWORD_REJECTED_MARKER")
		info "Bitwarden rejected the supplied vault password; prompting again"
		BITWARDEN_PASSWORD_VALUE="$(prompt_for_required_value "BITWARDEN_PASSWORD" "Bitwarden vault password: " 1)"
		return
		;;
	esac

	return 1
}

prompt_for_backup_output_dir_if_needed() {
	if [ -n "$BACKUP_OUTPUT_DIR" ]; then
		return
	fi

	has_interactive_terminal ||
		fail "backup requires an interactive terminal for the output directory, or WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR in CI"

	PROMPTED_BACKUP_OUTPUT_DIR="$(prompt_for_required_value "WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR" "Backup output directory: " 0)"
	BACKUP_OUTPUT_DIR="$PROMPTED_BACKUP_OUTPUT_DIR"
}

prepare_action_dependencies() {
	command_name="$1"

	initialize_target_context
	require_sudo
	install_ansible_packages
	install_git
	initialize_repository_source
	prepare_private_override_file "$command_name"
	install_collection_requirements
}

run_ansible_pull() {
	playbook_path="$1"
	dry_run="$2"
	shift 2
	initialize_repository_source
	initialize_target_context
	local_repository_root="$(resolve_local_repository_path "$REPOSITORY_URL" 2>/dev/null || true)"
	authenticated_repository_url="$(resolve_authenticated_repository_url "$REPOSITORY_URL")"

	# Share credentials through the environment, including across sudo.
	export BITWARDEN_EMAIL="$PROMPTED_BITWARDEN_EMAIL"
	export BITWARDEN_CLIENT_ID="$BITWARDEN_CLIENT_ID_VALUE"
	export BITWARDEN_CLIENT_SECRET="$BITWARDEN_CLIENT_SECRET_VALUE"
	export BITWARDEN_PASSWORD="$BITWARDEN_PASSWORD_VALUE"

	if [ -n "$GITHUB_TOKEN_VALUE" ]; then
		set -- "WORKSTATION_MANAGER_GITHUB_TOKEN=$GITHUB_TOKEN_VALUE" "$@"
	fi

	# Preserve the target desktop session for GPG and interactive application setup.
	set -- \
		"DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-}" \
		"XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-}" \
		"DISPLAY=${DISPLAY:-}" \
		"WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-}" \
		"GPG_TTY=${GPG_TTY:-}" \
		"SSH_AUTH_SOCK=${SSH_AUTH_SOCK:-}" \
		"WORKSTATION_MANAGER_USER=$TARGET_USER" \
		"WORKSTATION_MANAGER_USER_HOME=$TARGET_USER_HOME" \
		"WORKSTATION_MANAGER_PRIVATE_OVERRIDE_FILE=$PRIVATE_OVERRIDE_LOCAL_FILE" \
		"WORKSTATION_MANAGER_INTERACTIVE=$(interactive_terminal_flag)" "$@"

	# ansible-pull relays playbook output; flush prompts before waiting for input.
	if [ "${WORKSTATION_MANAGER_SKIP_SUDO:-0}" = "1" ]; then
		set -- \
			env \
			PYTHONUNBUFFERED=1 \
			ANSIBLE_COLLECTIONS_PATH="$COLLECTIONS_INSTALL_DIR:/usr/share/ansible/collections" \
			"$@"
	else
		set -- \
			sudo --preserve-env=BITWARDEN_EMAIL,BITWARDEN_CLIENT_ID,BITWARDEN_CLIENT_SECRET,BITWARDEN_PASSWORD env \
			PYTHONUNBUFFERED=1 \
			ANSIBLE_COLLECTIONS_PATH="$COLLECTIONS_INSTALL_DIR:/usr/share/ansible/collections" \
			"$@"
	fi

	if [ -n "$local_repository_root" ]; then
		set -- "$@" \
			ansible-playbook \
			-i "localhost," \
			-c local \
			"$local_repository_root/$playbook_path"

		if [ "$dry_run" = "1" ]; then
			set -- "$@" --check --diff
		fi

		if has_interactive_terminal; then
			(
				cd "$local_repository_root"
				"$@" </dev/tty
			)
		else
			(
				cd "$local_repository_root"
				"$@"
			)
		fi
		return
	fi

	if is_full_git_commit_sha "$REPOSITORY_BRANCH"; then
		# ansible-pull cannot supply the refspec needed for commits outside branches/tags,
		# including GitHub PR merge commits. Fetch the exact object before its checkout.
		"$@" env ANSIBLE_NO_LOG=true ansible localhost -i "localhost," -c local \
			-m ansible.builtin.git \
			-a "repo=$authenticated_repository_url dest=$ANSIBLE_CHECKOUT_DIR version=$REPOSITORY_BRANCH refspec=$REPOSITORY_BRANCH" \
			>/dev/null || fail "Failed to fetch the pinned repository commit. Check repository access and the commit SHA."
	fi

	set -- "$@" \
		ansible-pull \
		--purge \
		-U "$authenticated_repository_url" \
		-C "$REPOSITORY_BRANCH" \
		-d "$ANSIBLE_CHECKOUT_DIR" \
		-i "localhost," \
		-c local \
		"$playbook_path"

	if is_full_git_commit_sha "$REPOSITORY_BRANCH"; then
		set -- "$@" --full
	fi

	if [ "$dry_run" = "1" ]; then
		set -- "$@" --check --diff
	fi

	if has_interactive_terminal; then
		"$@" </dev/tty
	else
		"$@"
	fi
}

resolve_entrypoint_source() {
	if [ -n "${WORKSTATION_MANAGER_ENTRYPOINT_SOURCE:-}" ] && [ -f "$WORKSTATION_MANAGER_ENTRYPOINT_SOURCE" ]; then
		printf '%s\n' "$WORKSTATION_MANAGER_ENTRYPOINT_SOURCE"
		return 0
	fi

	if [ -f "$0" ]; then
		printf '%s\n' "$0"
		return 0
	fi

	resolved_path="$(command -v "$0" 2>/dev/null || true)"
	if [ -n "$resolved_path" ] && [ -f "$resolved_path" ]; then
		printf '%s\n' "$resolved_path"
		return 0
	fi

	return 1
}

copy_entrypoint_definitions() {
	entrypoint_source="$1"
	definitions_file="$2"
	last_line="$(tail -n 1 "$entrypoint_source" 2>/dev/null || true)"

	if [ "$last_line" = 'main "$@"' ]; then
		sed '$d' "$entrypoint_source" >"$definitions_file"
		return
	fi

	cp "$entrypoint_source" "$definitions_file"
}

run_ansible_pull_captured_with_fifo() {
	playbook_path="$1"
	dry_run="$2"
	output_file="$3"
	shift 3

	output_dir="$(mktemp -d "${TMPDIR:-/tmp}/workstation-manager-ansible-XXXXXX")"
	output_pipe="$output_dir/output.pipe"
	mkfifo "$output_pipe" || fail "Failed to create a relay for Ansible output"
	tee "$output_file" <"$output_pipe" &
	tee_pid="$!"

	if run_ansible_pull "$playbook_path" "$dry_run" "$@" >"$output_pipe" 2>&1; then
		exit_code=0
	else
		exit_code="$?"
	fi
	wait "$tee_pid"
	rm -rf "$output_dir"
	return "$exit_code"
}

run_ansible_pull_captured_with_script() {
	playbook_path="$1"
	dry_run="$2"
	output_file="$3"
	shift 3

	entrypoint_source="$(resolve_entrypoint_source)" || return 1
	runner_dir="$(mktemp -d "${TMPDIR:-/tmp}/workstation-manager-script-XXXXXX")"
	definitions_file="$runner_dir/entrypoint-definitions.sh"
	runner_script="$runner_dir/run-ansible-pull.sh"
	runner_command=""
	tmp_output_dir=""
	tmp_output_file=""

	copy_entrypoint_definitions "$entrypoint_source" "$definitions_file" || {
		rm -rf "$runner_dir"
		return 1
	}

	{
		printf '. %s\n' "$(shell_quote "$definitions_file")"
		printf 'WORKSTATION_MANAGER_SKIP_SUDO=1\n'
		printf 'PROMPTED_BITWARDEN_EMAIL=%s\n' "$(shell_quote "$PROMPTED_BITWARDEN_EMAIL")"
		printf 'BITWARDEN_CLIENT_ID_VALUE=%s\n' "$(shell_quote "$BITWARDEN_CLIENT_ID_VALUE")"
		printf 'BITWARDEN_CLIENT_SECRET_VALUE=%s\n' "$(shell_quote "$BITWARDEN_CLIENT_SECRET_VALUE")"
		printf 'BITWARDEN_PASSWORD_VALUE=%s\n' "$(shell_quote "$BITWARDEN_PASSWORD_VALUE")"
		printf 'TARGET_USER=%s\n' "$(shell_quote "$TARGET_USER")"
		printf 'TARGET_USER_HOME=%s\n' "$(shell_quote "$TARGET_USER_HOME")"
		printf 'COLLECTIONS_INSTALL_DIR=%s\n' "$(shell_quote "$COLLECTIONS_INSTALL_DIR")"
		printf 'PRIVATE_OVERRIDE_LOCAL_FILE=%s\n' "$(shell_quote "$PRIVATE_OVERRIDE_LOCAL_FILE")"
		printf 'GITHUB_TOKEN_VALUE=%s\n' "$(shell_quote "$GITHUB_TOKEN_VALUE")"
		printf 'REPOSITORY_URL=%s\n' "$(shell_quote "$REPOSITORY_URL")"
		printf 'REPOSITORY_BRANCH=%s\n' "$(shell_quote "$REPOSITORY_BRANCH")"
		printf 'ANSIBLE_CHECKOUT_DIR=%s\n' "$(shell_quote "$ANSIBLE_CHECKOUT_DIR")"
		printf 'set --'
		for extra_arg in "$@"; do
			printf ' %s' "$(shell_quote "$extra_arg")"
		done
		printf '\n'
		printf 'run_ansible_pull %s %s "$@"\n' \
			"$(shell_quote "$playbook_path")" \
			"$(shell_quote "$dry_run")"
	} >"$runner_script"
	chmod 700 "$runner_script"
	runner_command="/bin/sh $(shell_quote "$runner_script")"
	tmp_output_dir="$(sudo mktemp -d "${TMPDIR:-/tmp}/workstation-manager-script-output-XXXXXX")" || {
		rm -rf "$runner_dir"
		return 1
	}
	tmp_output_file="$tmp_output_dir/typescript"

	if sudo \
		--preserve-env=BITWARDEN_EMAIL,BITWARDEN_CLIENT_ID,BITWARDEN_CLIENT_SECRET,BITWARDEN_PASSWORD \
		env \
		DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-}" \
		XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-}" \
		DISPLAY="${DISPLAY:-}" \
		WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-}" \
		GPG_TTY="${GPG_TTY:-}" \
		SSH_AUTH_SOCK="${SSH_AUTH_SOCK:-}" \
		script --quiet --return --command "$runner_command" "$tmp_output_file"; then
		exit_code=0
	else
		exit_code="$?"
	fi
	sudo cat "$tmp_output_file" >"$output_file" 2>/dev/null || :
	sudo rm -rf "$tmp_output_dir" 2>/dev/null || :

	rm -rf "$runner_dir"
	return "$exit_code"
}

run_ansible_pull_with_bitwarden_retry() {
	playbook_path="$1"
	dry_run="$2"
	shift 2

	if ! has_interactive_terminal; then
		run_ansible_pull "$playbook_path" "$dry_run" "$@"
		return
	fi

	while :; do
		output_file="$(mktemp "${TMPDIR:-/tmp}/workstation-manager-ansible-output-XXXXXX")"

		if [ "${WORKSTATION_MANAGER_DISABLE_SCRIPT_CAPTURE:-0}" != "1" ] && command -v script >/dev/null 2>&1; then
			if run_ansible_pull_captured_with_script "$playbook_path" "$dry_run" "$output_file" "$@"; then
				exit_code=0
			else
				exit_code="$?"
			fi
		else
			if run_ansible_pull_captured_with_fifo "$playbook_path" "$dry_run" "$output_file" "$@"; then
				exit_code=0
			else
				exit_code="$?"
			fi
		fi

		if [ "$exit_code" -eq 0 ]; then
			rm -f "$output_file"
			return 0
		fi

		failure_marker=""
		if grep -Fq "$BITWARDEN_EMAIL_PASSWORD_REJECTED_MARKER" "$output_file"; then
			failure_marker="$BITWARDEN_EMAIL_PASSWORD_REJECTED_MARKER"
		elif grep -Fq "$BITWARDEN_PASSWORD_REJECTED_MARKER" "$output_file"; then
			failure_marker="$BITWARDEN_PASSWORD_REJECTED_MARKER"
		fi
		rm -f "$output_file"

		if [ -n "$failure_marker" ] && reprompt_for_bitwarden_credentials "$failure_marker"; then
			continue
		fi

		return "$exit_code"
	done
}

run_setup() {
	dry_run="$1"
	prepare_action_dependencies setup
	prompt_for_bitwarden_credentials_if_needed "setup" "Bitwarden-backed secrets restore"

	info "Running workstation setup from $REPOSITORY_URL#$REPOSITORY_BRANCH"
	set --

	if [ -n "$RESTORE_ARCHIVE_PATH" ]; then
		set -- "$@" \
			WORKSTATION_MANAGER_RESTORE_ARCHIVE="$RESTORE_ARCHIVE_PATH"
	fi

	run_ansible_pull_with_bitwarden_retry ansible/setup.yml "$dry_run" "$@"
}

run_backup() {
	dry_run="$1"
	prompt_for_backup_output_dir_if_needed
	prepare_action_dependencies backup
	prompt_for_bitwarden_credentials_if_needed "backup" "Backup-time key and browser recovery synchronization"

	info "Running workstation backup from $REPOSITORY_URL#$REPOSITORY_BRANCH"
	run_ansible_pull_with_bitwarden_retry \
		ansible/backup.yml \
		"$dry_run" \
		WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR="$BACKUP_OUTPUT_DIR" \
		WORKSTATION_MANAGER_BACKUP_EXTRA_PATHS="${WORKSTATION_MANAGER_BACKUP_EXTRA_PATHS:-}" \
		WORKSTATION_MANAGER_BACKUP_ARCHIVE="${WORKSTATION_MANAGER_BACKUP_ARCHIVE:-}" \
		WORKSTATION_MANAGER_BACKUP_MANIFEST="${WORKSTATION_MANAGER_BACKUP_MANIFEST:-}" \
		WORKSTATION_MANAGER_BACKUP_GIT_INVENTORY="${WORKSTATION_MANAGER_BACKUP_GIT_INVENTORY:-}" \
		WORKSTATION_MANAGER_BACKUP_DRY_RUN="${WORKSTATION_MANAGER_BACKUP_DRY_RUN:-0}"
}

run_cleanup() {
	dry_run="$1"
	prepare_action_dependencies cleanup
	prompt_for_bitwarden_credentials_if_needed "cleanup" "Browser profile drift inspection"

	info "Running workstation cleanup from $REPOSITORY_URL#$REPOSITORY_BRANCH"
	run_ansible_pull_with_bitwarden_retry ansible/cleanup.yml "$dry_run"
}

main() {
	command_name="setup"
	dry_run=0

	case "${1:-}" in
	"") ;;
	setup | backup | cleanup)
		command_name="$1"
		shift
		;;
	help | -h | --help)
		usage
		exit 0
		;;
	--dry-run)
		dry_run=1
		shift
		;;
	*)
		fail "unsupported command: $1"
		;;
	esac

	case "${1:-}" in
	"") ;;
	--dry-run)
		dry_run=1
		shift
		;;
	*)
		fail "unsupported option for $command_name: $1"
		;;
	esac

	[ "$#" -eq 0 ] || fail "too many arguments for $command_name"

	case "$command_name" in
	setup)
		run_setup "$dry_run"
		;;
	backup)
		run_backup "$dry_run"
		;;
	cleanup)
		run_cleanup "$dry_run"
		;;
	esac

	info "Workstation command completed"
}

main "$@"
