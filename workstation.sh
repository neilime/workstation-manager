#!/usr/bin/env sh

set -eu

# Optional user inputs. Normal runs prompt for missing values; CI can prefill them.
BACKUP_OUTPUT_DIR="${WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR:-}"
RESTORE_ARCHIVE_PATH="${WORKSTATION_MANAGER_RESTORE_ARCHIVE:-}"

# Automation / CI credentials. Leave unset for normal interactive account sign-in.
# All three Bitwarden values are needed to replace the email/password prompts.
GITHUB_TOKEN_VALUE="${WORKSTATION_MANAGER_GITHUB_TOKEN:-}"
BITWARDEN_CLIENT_ID_VALUE="${BITWARDEN_CLIENT_ID:-}"
BITWARDEN_CLIENT_SECRET_VALUE="${BITWARDEN_CLIENT_SECRET:-}"
BITWARDEN_PASSWORD_VALUE="${BITWARDEN_PASSWORD:-}"

# Development / CI source overrides. Normal bootstrap uses the published defaults.
REPOSITORY_URL="${REPOSITORY_URL:-}"
REPOSITORY_BRANCH="${REPOSITORY_BRANCH:-}"
PRIVATE_OVERRIDE_LOCAL_FILE="${WORKSTATION_MANAGER_PRIVATE_OVERRIDE_FILE:-}"

# Internal runtime state, not environment configuration for users or CI.
ANSIBLE_CHECKOUT_DIR="/tmp/workstation-manager-v1"
TARGET_USER=""
TARGET_USER_HOME=""
COLLECTIONS_INSTALL_DIR=""
ANSIBLE_VENV_DIR="/opt/workstation-manager/venv"
DEFAULT_REPOSITORY_URL="https://github.com/neilime/workstation-manager.git"
DEFAULT_REPOSITORY_BRANCH="main"
PRIVATE_OVERRIDE_TEMP_DIR=""
PROMPTED_BITWARDEN_EMAIL=""
BITWARDEN_EMAIL_PASSWORD_REJECTED_MARKER="WORKSTATION_MANAGER_BITWARDEN_EMAIL_PASSWORD_REJECTED"
BITWARDEN_PASSWORD_REJECTED_MARKER="WORKSTATION_MANAGER_BITWARDEN_PASSWORD_REJECTED"
PRIVATE_OVERRIDE_REPOSITORY_URL="https://github.com/neilime/workstation-config.git"
PRIVATE_OVERRIDE_REPOSITORY_BRANCH="main"
PRIVATE_OVERRIDE_REPOSITORY_PATH="ansible/private.override.yml"

# Shared configuration and command help.

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

shell_quote() {
	printf '%s' "'"
	printf '%s' "$1" | sed "s/'/'\\\\''/g"
	printf '%s' "'"
}

usage() {
	cat <<EOF
Usage: workstation.sh [setup|backup|cleanup] [--dry-run]

Default behavior:
	Run setup; prompt for missing inputs in the terminal.

Commands:
	setup            Bootstrap dependencies and converge the workstation.
	cleanup          Clean removable workstation artifacts and report drift.
	backup           Create a workstation backup archive instead of converging state.
	help             Show this help message.

Options:
	--dry-run        Preview the selected action in Ansible check mode.
	--help           Show this help message.

Optional user inputs (normally supplied by prompts or only when needed):
	WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR   Backup destination; prompted if unset.
	WORKSTATION_MANAGER_RESTORE_ARCHIVE     Optional backup archive path to replay during setup.

Examples:
	wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- setup
	wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- setup --dry-run
	wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | WORKSTATION_MANAGER_RESTORE_ARCHIVE=/path/to/workstation-manager-backup.tar.gz sh -s -- setup
	wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- cleanup --dry-run
	wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- backup --dry-run
EOF
}

trap cleanup EXIT
trap 'exit 1' HUP INT TERM

# Interactive input: used whenever required values are missing and a terminal is available.

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

interactive_terminal_path() {
	has_interactive_terminal || return 1
	# When the terminal is already on stdin, `tty` reports its concrete device.
	if terminal_path="$(tty 2>/dev/null)" && [ "$terminal_path" != "/dev/tty" ]; then
		printf '%s\n' "$terminal_path"
		return 0
	fi
	# Opening /dev/tty resolves to the "/dev/tty" alias, which the relayed setup
	# process (sudo, script, and Ansible modules) cannot reliably reopen. Resolve
	# the controlling terminal's real device so Bitwarden prompts reach the caller.
	terminal_path="$(ps -o tty= -p "$$" 2>/dev/null | tr -d '[:space:]')"
	case "$terminal_path" in
	'' | '?') return 1 ;;
	/dev/*) printf '%s\n' "$terminal_path" ;;
	*) printf '/dev/%s\n' "$terminal_path" ;;
	esac
}

prepare_bitwarden_credentials() {
	action_name="$1"
	action_purpose="$2"

	if [ -n "$BITWARDEN_CLIENT_ID_VALUE" ] &&
		[ -n "$BITWARDEN_CLIENT_SECRET_VALUE" ] &&
		[ -n "$BITWARDEN_PASSWORD_VALUE" ]; then
		return
	fi
	has_interactive_terminal ||
		fail "$action_name requires a terminal for Bitwarden login or BITWARDEN_CLIENT_ID, BITWARDEN_CLIENT_SECRET, and BITWARDEN_PASSWORD for automation"

	info "$action_purpose requires Bitwarden access; prompting for credentials"
	prompt_for_bitwarden_login
}

prompt_for_bitwarden_login() {
	PROMPTED_BITWARDEN_EMAIL="$(prompt_for_required_value "BITWARDEN_EMAIL" "Bitwarden email: " 0)"
	BITWARDEN_PASSWORD_VALUE="$(prompt_for_required_value "BITWARDEN_PASSWORD" "Bitwarden vault password: " 1)"
	BITWARDEN_CLIENT_ID_VALUE=""
	BITWARDEN_CLIENT_SECRET_VALUE=""
}

reprompt_for_bitwarden_credentials() {
	failure_marker="$1"

	has_interactive_terminal || return 1

	case "$failure_marker" in
	"$BITWARDEN_EMAIL_PASSWORD_REJECTED_MARKER")
		info "Bitwarden rejected the supplied email or password; prompting again"
		prompt_for_bitwarden_login
		;;
	"$BITWARDEN_PASSWORD_REJECTED_MARKER")
		info "Bitwarden rejected the supplied vault password; prompting again"
		BITWARDEN_PASSWORD_VALUE="$(prompt_for_required_value "BITWARDEN_PASSWORD" "Bitwarden vault password: " 1)"
		;;
	*) return 1 ;;
	esac
}

prompt_for_backup_output_dir_if_needed() {
	if [ -n "$BACKUP_OUTPUT_DIR" ]; then
		return
	fi

	has_interactive_terminal ||
		fail "backup requires a terminal or WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR for its output directory"

	BACKUP_OUTPUT_DIR="$(prompt_for_required_value "WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR" "Backup output directory: " 0)"
}

prepare_entrypoint_definitions() {
	definitions_file="$1"
	if ! entrypoint_source="$(resolve_entrypoint_source)"; then
		initialize_repository_source
		entrypoint_source="${definitions_file}.source"
		download_repository_file workstation.sh "$entrypoint_source" || return 1
	fi

	grep -q '^run_ansible_pull() {' "$entrypoint_source" || return 1
	last_line="$(tail -n 1 "$entrypoint_source" 2>/dev/null || true)"

	if [ "$last_line" = 'main "$@"' ]; then
		sed '$d' "$entrypoint_source" >"$definitions_file" || return 1
	else
		cp "$entrypoint_source" "$definitions_file" || return 1
	fi

	/bin/sh -n "$definitions_file"
}

run_ansible_pull_captured_with_fifo() (
	playbook_path="$1"
	dry_run="$2"
	output_file="$3"
	shift 3

	output_dir="$(mktemp -d "${TMPDIR:-/tmp}/workstation-manager-ansible-XXXXXX")" || return 1
	trap 'rm -rf "$output_dir"' EXIT
	trap 'exit 1' HUP INT TERM
	output_pipe="$output_dir/output.pipe"
	mkfifo "$output_pipe" || fail "Failed to create a relay for Ansible output"
	tee "$output_file" <"$output_pipe" &
	tee_pid="$!"

	exit_code=0
	run_ansible_pull "$playbook_path" "$dry_run" "$@" >"$output_pipe" 2>&1 || exit_code=$?
	wait "$tee_pid" || fail "Failed to capture Ansible output"
	return "$exit_code"
)

prepare_ansible_prompt_terminal() {
	# script allocates this private relay after sudo, so its initial owner is root.
	# Keep its permissions and input forwarding while allowing managed-user prompts.
	[ -t 0 ] || fail "Interactive Ansible capture requires a terminal"
	relay_terminal="$(tty)" || fail "Failed to resolve the interactive relay terminal"
	chown -- "$TARGET_USER" "$relay_terminal" ||
		fail "Failed to make the interactive relay terminal accessible to $TARGET_USER"
}

run_ansible_pull_captured_with_script() (
	playbook_path="$1"
	dry_run="$2"
	output_file="$3"
	shift 3

	runner_dir="$(mktemp -d "${TMPDIR:-/tmp}/workstation-manager-script-XXXXXX")" || return 1
	tmp_output_dir=""
	trap 'rm -rf "$runner_dir"; if [ -n "$tmp_output_dir" ]; then sudo rm -rf "$tmp_output_dir"; fi' EXIT
	trap 'exit 1' HUP INT TERM
	definitions_file="$runner_dir/entrypoint-definitions.sh"
	runner_script="$runner_dir/run-ansible-pull.sh"

	prepare_entrypoint_definitions "$definitions_file" ||
		fail "Failed to prepare the entrypoint for interactive Ansible execution. Check repository access and workstation.sh at $REPOSITORY_URL#$REPOSITORY_BRANCH."

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
		printf 'ANSIBLE_VENV_DIR=%s\n' "$(shell_quote "$ANSIBLE_VENV_DIR")"
		printf 'set --'
		for extra_arg in "$@"; do
			printf ' %s' "$(shell_quote "$extra_arg")"
		done
		printf '\n'
		printf 'prepare_ansible_prompt_terminal\n'
		printf 'run_ansible_pull %s %s "$@"\n' \
			"$(shell_quote "$playbook_path")" \
			"$(shell_quote "$dry_run")"
	} >"$runner_script" || return 1
	chmod 700 "$runner_script" || return 1
	runner_command="/bin/sh $(shell_quote "$runner_script")"
	tmp_output_dir="$(sudo mktemp -d "${TMPDIR:-/tmp}/workstation-manager-script-output-XXXXXX")" || return 1
	tmp_output_file="$tmp_output_dir/typescript"

	# The invoking user's terminal supplies input before sudo starts the relay.
	exit_code=0
	run_with_session_environment script --quiet --return --command "$runner_command" "$tmp_output_file" </dev/tty || exit_code=$?
	# Redirection runs as the caller; only reading the root-owned log needs sudo.
	# shellcheck disable=SC2024
	sudo cat "$tmp_output_file" >"$output_file" || fail "Failed to read captured Ansible output"
	return "$exit_code"
)

run_ansible_pull_with_bitwarden_retry() (
	playbook_path="$1"
	dry_run="$2"
	shift 2

	if ! has_interactive_terminal; then
		run_ansible_pull "$playbook_path" "$dry_run" "$@"
		return
	fi

	output_file=""
	trap '[ -z "$output_file" ] || rm -f "$output_file"' EXIT
	trap 'exit 1' HUP INT TERM
	capture_function=run_ansible_pull_captured_with_fifo
	# Test harness override: exercise the FIFO relay without changing workstation actions.
	if [ "${WORKSTATION_MANAGER_DISABLE_SCRIPT_CAPTURE:-0}" != "1" ] && command -v script >/dev/null 2>&1; then
		capture_function=run_ansible_pull_captured_with_script
	fi
	while :; do
		output_file="$(mktemp "${TMPDIR:-/tmp}/workstation-manager-ansible-output-XXXXXX")" || return 1
		exit_code=0
		"$capture_function" "$playbook_path" "$dry_run" "$output_file" "$@" || exit_code=$?

		if [ "$exit_code" -eq 0 ]; then
			return 0
		fi

		failure_marker=""
		if grep -Fq "$BITWARDEN_EMAIL_PASSWORD_REJECTED_MARKER" "$output_file"; then
			failure_marker="$BITWARDEN_EMAIL_PASSWORD_REJECTED_MARKER"
		elif grep -Fq "$BITWARDEN_PASSWORD_REJECTED_MARKER" "$output_file"; then
			failure_marker="$BITWARDEN_PASSWORD_REJECTED_MARKER"
		fi
		rm -f "$output_file"
		output_file=""

		if [ -n "$failure_marker" ] && reprompt_for_bitwarden_credentials "$failure_marker"; then
			continue
		fi

		return "$exit_code"
	done
)

# Shared bootstrap and execution: interactive runs and CI use the same actions.

require_command() {
	command -v "$1" >/dev/null 2>&1 || fail "$1 is required"
}

require_sudo() {
	require_command sudo
	sudo -v || fail "sudo access is required"
}

install_bootstrap_packages() {
	require_sudo
	sudo apt-get update || return 1
	sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$@"
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

install_ansible_packages() (
	bootstrap_dir="$(mktemp -d "${TMPDIR:-/tmp}/workstation-manager-bootstrap-XXXXXX")" || return 1
	trap 'rm -rf "$bootstrap_dir"' EXIT
	trap 'exit 1' HUP INT TERM
	download_repository_file ansible/ubuntu-version "$bootstrap_dir/ubuntu-version" || return 1
	download_repository_file ansible/requirements.txt "$bootstrap_dir/requirements.txt" || return 1
	validate_supported_ubuntu "$bootstrap_dir/ubuntu-version" || return 1
	info "Installing bootstrap packages"
	install_bootstrap_packages python3 python3-venv python3-debian ca-certificates || return 1
	# Use the OS interpreter for host modules and an isolated, shared controller pin.
	# The managed user runs ansible-galaxy from this root-owned environment.
	# Scope the public permissions to this subshell, preserving private callers' umask.
	umask 022
	sudo python3 -m venv "$ANSIBLE_VENV_DIR" || return 1
	sudo "$ANSIBLE_VENV_DIR/bin/python" -m pip install --disable-pip-version-check \
		-r "$bootstrap_dir/requirements.txt" || return 1
	sudo "$ANSIBLE_VENV_DIR/bin/python" -m pip check
)

validate_supported_ubuntu() (
	expected_ubuntu="$(cat "$1")"
	case "$expected_ubuntu" in
	[0-9][0-9].[0-9][0-9]) ;;
	*) fail "Invalid supported Ubuntu release in ansible/ubuntu-version" ;;
	esac
	# The operating system owns this file; do not source downloaded shell fragments.
	. /etc/os-release
	[ "${ID:-}" = ubuntu ] && [ "${VERSION_ID:-}" = "$expected_ubuntu" ] ||
		fail "This revision requires Ubuntu $expected_ubuntu. Upgrade Ubuntu before running setup, backup, or cleanup."
)

download_repository_file() (
	requested_file="$1"
	requested_destination="$2"
	if source_path="$(resolve_github_repository_path "$REPOSITORY_URL")"; then
		download_github_file "$source_path" "$REPOSITORY_BRANCH" "$requested_file" "$requested_destination"
	else
		source_root="$(resolve_local_repository_path "$REPOSITORY_URL")" ||
			fail "REPOSITORY_URL must point to a GitHub repository or local checkout"
		cp "$source_root/$requested_file" "$requested_destination"
	fi
)

install_git() {
	if command -v git >/dev/null 2>&1; then
		return
	fi

	info "Installing git (required for ansible-pull)"
	install_bootstrap_packages git
}

prepare_github_authentication() {
	info "Checking GitHub sign-in before loading private configuration"
	run_ansible_pull_with_bitwarden_retry ansible/github_bootstrap.yml 0 ||
		fail "GitHub sign-in did not complete; check your account access and desktop credential store"
	# Reuse the verified managed-user login for authenticated bootstrap downloads.
	# Ignore inherited gh overrides so they cannot mask missing persistent credentials.
	target_user_id="$(id -u "$TARGET_USER")"
	GITHUB_TOKEN_VALUE="$(sudo -u "$TARGET_USER" env \
		-u GH_TOKEN -u GITHUB_TOKEN -u GH_ENTERPRISE_TOKEN -u GITHUB_ENTERPRISE_TOKEN -u GH_DEBUG \
		HOME="$TARGET_USER_HOME" XDG_CONFIG_HOME="$TARGET_USER_HOME/.config" \
		GH_CONFIG_DIR="$TARGET_USER_HOME/.config/gh" \
		XDG_RUNTIME_DIR="/run/user/$target_user_id" \
		DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$target_user_id/bus" \
		gh auth token --hostname github.com 2>/dev/null)" ||
		fail "Cannot read the saved GitHub login from the desktop credential store"
	[ -n "$GITHUB_TOKEN_VALUE" ] || fail "The saved GitHub login has no usable token"
}

clone_private_override_repository() {
	repository_url="$1"
	destination_dir="$2"

	GIT_TERMINAL_PROMPT=0 \
		GIT_CONFIG_COUNT=1 \
		GIT_CONFIG_KEY_0=http.https://github.com/.extraheader \
		GIT_CONFIG_VALUE_0="$(github_git_authorization)" \
		git clone --depth 1 --branch "$PRIVATE_OVERRIDE_REPOSITORY_BRANCH" \
		"$repository_url" "$destination_dir" >/dev/null 2>&1
}

github_git_authorization() {
	printf 'Authorization: Basic '
	printf 'x-access-token:%s' "$GITHUB_TOKEN_VALUE" | base64 | tr -d '\n'
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

resolve_repository_clone_url() {
	repository_url="$1"

	if [ -n "$GITHUB_TOKEN_VALUE" ] &&
		repository_path="$(resolve_github_repository_path "$repository_url")"; then
		printf 'https://github.com/%s.git\n' "$repository_path"
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
	if [ -f "$repository_path/HEAD" ] && [ -d "$repository_path/objects" ] && [ -d "$repository_path/refs" ] &&
		[ ! -d "$repository_path/.git" ]; then
		return 1
	fi
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

download_github_file() (
	repository_path="$1"
	ref_name="$2"
	repository_file="$3"
	destination="$4"

	if command -v wget >/dev/null 2>&1; then
		set -- wget -q -O "$destination"
	elif command -v curl >/dev/null 2>&1; then
		set -- curl -fsSL -o "$destination"
	else
		fail "wget or curl is required"
	fi

	if [ -n "$GITHUB_TOKEN_VALUE" ]; then
		set -- "$@" \
			--header "Authorization: Bearer $GITHUB_TOKEN_VALUE" \
			--header "Accept: application/vnd.github.raw" \
			"https://api.github.com/repos/${repository_path}/contents/${repository_file}?ref=${ref_name}"
	else
		set -- "$@" "https://raw.githubusercontent.com/${repository_path}/${ref_name}/${repository_file}"
	fi
	"$@"
)

install_collection_requirements_file() (
	collection_requirements_file="$1"
	collection_install_attempt=1
	collection_install_max_attempts=3

	while ! "$ANSIBLE_VENV_DIR/bin/ansible-galaxy" collection install -r "$collection_requirements_file" -p "$COLLECTIONS_INSTALL_DIR" >/dev/null; do
		if [ "$collection_install_attempt" -ge "$collection_install_max_attempts" ]; then
			return 1
		fi
		collection_install_attempt=$((collection_install_attempt + 1))
		info "Ansible collection install failed; retrying (attempt $collection_install_attempt/$collection_install_max_attempts)"
		sleep 5
	done
)

install_collection_requirements() (
	info "Installing Ansible collection dependencies"
	if repository_root="$(resolve_local_repository_path "$REPOSITORY_URL")"; then
		requirements_file="$repository_root/ansible/collections/requirements.yml"
		[ -f "$requirements_file" ] || fail "Collection requirements were not found in $repository_root"
	else
		requirements_file="$(mktemp "${TMPDIR:-/tmp}/workstation-manager-requirements-XXXXXX.yml")" || return 1
		trap 'rm -f "$requirements_file"' EXIT
		trap 'exit 1' HUP INT TERM
		download_repository_file ansible/collections/requirements.yml "$requirements_file" || return 1
	fi
	install_collection_requirements_file "$requirements_file"
)

prepare_private_override_file() {
	if [ -n "$PRIVATE_OVERRIDE_LOCAL_FILE" ]; then
		return
	fi

	PRIVATE_OVERRIDE_TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/workstation-manager-private-override-XXXXXX")"
	private_override_checkout_dir="$PRIVATE_OVERRIDE_TEMP_DIR/repository"
	private_override_candidate="$private_override_checkout_dir/$PRIVATE_OVERRIDE_REPOSITORY_PATH"
	info "Fetching private override from $PRIVATE_OVERRIDE_REPOSITORY_URL#$PRIVATE_OVERRIDE_REPOSITORY_BRANCH"
	clone_private_override_repository \
		"$PRIVATE_OVERRIDE_REPOSITORY_URL" \
		"$private_override_checkout_dir" ||
		fail "Failed to fetch private override repository $PRIVATE_OVERRIDE_REPOSITORY_URL; check that your signed-in GitHub account has access."

	[ -f "$private_override_candidate" ] ||
		fail "Private override file $PRIVATE_OVERRIDE_REPOSITORY_PATH was not found in $PRIVATE_OVERRIDE_REPOSITORY_URL#$PRIVATE_OVERRIDE_REPOSITORY_BRANCH"

	PRIVATE_OVERRIDE_LOCAL_FILE="$private_override_candidate"
}

prepare_action_dependencies() {
	initialize_target_context
	require_sudo
	install_git
	initialize_repository_source
	install_ansible_packages
	install_collection_requirements
	prepare_github_authentication
	prepare_private_override_file
}

run_with_session_environment() (
	# Empty DISPLAY/GPG_TTY values make GPGME construct invalid GnuPG options.
	# Isolate unsets so the caller retains its original session environment.
	for session_assignment in \
		"DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-}" \
		"XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-}" \
		"DISPLAY=${DISPLAY:-}" \
		"WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-}" \
		"GPG_TTY=${GPG_TTY:-}" \
		"SSH_AUTH_SOCK=${SSH_AUTH_SOCK:-}"; do
		if [ -n "${session_assignment#*=}" ]; then
			set -- "$session_assignment" "$@"
		else
			unset "${session_assignment%%=*}"
		fi
	done
	set -- env "$@"
	# Internal relay state: script capture has already elevated its child process.
	if [ "${WORKSTATION_MANAGER_SKIP_SUDO:-0}" != "1" ]; then
		set -- sudo --preserve-env=BITWARDEN_EMAIL,BITWARDEN_CLIENT_ID,BITWARDEN_CLIENT_SECRET,BITWARDEN_PASSWORD "$@"
	fi
	"$@"
)

run_ansible_pull() {
	playbook_path="$1"
	dry_run="$2"
	shift 2
	initialize_repository_source
	initialize_target_context
	local_repository_root="$(resolve_local_repository_path "$REPOSITORY_URL" 2>/dev/null || true)"
	repository_clone_url="$(resolve_repository_clone_url "$REPOSITORY_URL")"

	# Share credentials through the environment, including across sudo.
	export BITWARDEN_EMAIL="$PROMPTED_BITWARDEN_EMAIL"
	export BITWARDEN_CLIENT_ID="$BITWARDEN_CLIENT_ID_VALUE"
	export BITWARDEN_CLIENT_SECRET="$BITWARDEN_CLIENT_SECRET_VALUE"
	export BITWARDEN_PASSWORD="$BITWARDEN_PASSWORD_VALUE"

	if [ -n "$GITHUB_TOKEN_VALUE" ]; then
		# ansible-pull prints its arguments, so Git credentials must stay out of URLs.
		set -- "WORKSTATION_MANAGER_GITHUB_TOKEN=$GITHUB_TOKEN_VALUE" \
			GIT_CONFIG_COUNT=1 \
			GIT_CONFIG_KEY_0=http.https://github.com/.extraheader \
			"GIT_CONFIG_VALUE_0=$(github_git_authorization)" "$@"
	fi

	interactive_tty_path="$(interactive_terminal_path || true)"
	set -- "WORKSTATION_MANAGER_TTY=$interactive_tty_path" "$@"

	# ansible-pull relays playbook output; flush prompts before waiting for input.
	set -- env \
		PYTHONUNBUFFERED=1 \
		ANSIBLE_COLLECTIONS_PATH="$COLLECTIONS_INSTALL_DIR:/usr/share/ansible/collections" \
		"WORKSTATION_MANAGER_USER=$TARGET_USER" \
		"WORKSTATION_MANAGER_USER_HOME=$TARGET_USER_HOME" \
		"WORKSTATION_MANAGER_PRIVATE_OVERRIDE_FILE=$PRIVATE_OVERRIDE_LOCAL_FILE" \
		"WORKSTATION_MANAGER_INTERACTIVE=$(interactive_terminal_flag)" "$@"

	if [ -n "$local_repository_root" ]; then
		set -- "$@" "$ANSIBLE_VENV_DIR/bin/ansible-playbook"
		playbook_file="$local_repository_root/$playbook_path"
	else
		if is_full_git_commit_sha "$REPOSITORY_BRANCH"; then
			# Fetch exact commits, including PR merge commits outside branches/tags.
			run_with_session_environment "$@" env ANSIBLE_NO_LOG=true "$ANSIBLE_VENV_DIR/bin/ansible" localhost -i "localhost," -c local \
				-m ansible.builtin.git \
				-a "repo=$repository_clone_url dest=$ANSIBLE_CHECKOUT_DIR version=$REPOSITORY_BRANCH refspec=$REPOSITORY_BRANCH" \
				>/dev/null || fail "Failed to fetch the pinned repository commit. Check repository access and the commit SHA."
		fi
		set -- "$@" "$ANSIBLE_VENV_DIR/bin/ansible-pull" \
			--purge -U "$repository_clone_url" -C "$REPOSITORY_BRANCH" -d "$ANSIBLE_CHECKOUT_DIR"
		if is_full_git_commit_sha "$REPOSITORY_BRANCH"; then
			set -- "$@" --full
		fi
		playbook_file="$playbook_path"
	fi
	set -- "$@" \
		-i "localhost," \
		-c local \
		-e ansible_python_interpreter=/usr/bin/python3 \
		"$playbook_file"
	if [ "$dry_run" = "1" ]; then
		set -- "$@" --check --diff
	fi

	(
		if [ -n "$local_repository_root" ]; then
			cd "$local_repository_root" || exit 1
		fi
		if has_interactive_terminal; then
			run_with_session_environment "$@" </dev/tty
		else
			run_with_session_environment "$@"
		fi
	)
}

resolve_entrypoint_source() {
	# Internal source handoff for capture fixtures; normal execution resolves $0.
	for entrypoint_candidate in \
		"${WORKSTATION_MANAGER_ENTRYPOINT_SOURCE:-}" \
		"$0" \
		"$(command -v "$0" 2>/dev/null || true)"; do
		# With wget ... | sh, $0 resolves to the shell executable, not this source.
		if [ -f "$entrypoint_candidate" ] && grep -q '^run_ansible_pull() {' "$entrypoint_candidate"; then
			printf '%s\n' "$entrypoint_candidate"
			return 0
		fi
	done

	return 1
}

run_action() {
	action_name="$1"
	dry_run="$2"
	if [ "$action_name" = backup ]; then
		prompt_for_backup_output_dir_if_needed
	fi
	set --
	case "$action_name" in
	setup)
		if [ -n "$RESTORE_ARCHIVE_PATH" ]; then
			set -- WORKSTATION_MANAGER_RESTORE_ARCHIVE="$RESTORE_ARCHIVE_PATH"
		fi
		;;
	backup)
		set -- \
			WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR="$BACKUP_OUTPUT_DIR" \
			WORKSTATION_MANAGER_BACKUP_EXTRA_PATHS="${WORKSTATION_MANAGER_BACKUP_EXTRA_PATHS:-}" \
			WORKSTATION_MANAGER_BACKUP_ARCHIVE="${WORKSTATION_MANAGER_BACKUP_ARCHIVE:-}" \
			WORKSTATION_MANAGER_BACKUP_MANIFEST="${WORKSTATION_MANAGER_BACKUP_MANIFEST:-}" \
			WORKSTATION_MANAGER_BACKUP_GIT_INVENTORY="${WORKSTATION_MANAGER_BACKUP_GIT_INVENTORY:-}" \
			WORKSTATION_MANAGER_BACKUP_DRY_RUN="${WORKSTATION_MANAGER_BACKUP_DRY_RUN:-0}"
		;;
	cleanup) ;;
	*) fail "unsupported command: $action_name" ;;
	esac
	prepare_action_dependencies
	prepare_bitwarden_credentials "$action_name" "Workstation $action_name"
	info "Running workstation $action_name from $REPOSITORY_URL#$REPOSITORY_BRANCH"
	run_ansible_pull_with_bitwarden_retry "ansible/$action_name.yml" "$dry_run" "$@"
}

main() {
	command_name="setup"
	dry_run=0

	case "${1:-}" in
	setup | backup | cleanup)
		command_name="$1"
		shift
		;;
	help)
		usage
		return
		;;
	"" | -*) ;;
	*) fail "unsupported command: $1" ;;
	esac

	while [ "$#" -gt 0 ]; do
		case "$1" in
		--dry-run) dry_run=1 ;;
		-h | --help)
			usage
			return
			;;
		*) fail "unsupported option for $command_name: $1" ;;
		esac
		shift
	done

	run_action "$command_name" "$dry_run"

	info "Workstation command completed"
}

main "$@"
