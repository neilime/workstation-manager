#!/usr/bin/env sh

set -eu

REPOSITORY_URL="${REPOSITORY_URL:-https://github.com/neilime/workstation-manager.git}"
REPOSITORY_BRANCH="${REPOSITORY_BRANCH:-main}"
ANSIBLE_CHECKOUT_DIR="/tmp/workstation-manager-v1"
TARGET_USER=""
TARGET_USER_HOME=""
COLLECTIONS_INSTALL_DIR=""
PRIVATE_OVERRIDE_LOCAL_FILE=""
PRIVATE_OVERRIDE_TEMP_DIR=""
GITHUB_TOKEN_VALUE="${WORKSTATION_MANAGER_GITHUB_TOKEN:-}"
BACKUP_OUTPUT_DIR="${WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR:-}"
PROMPTED_BACKUP_OUTPUT_DIR=""
PROMPTED_BITWARDEN_EMAIL=""
BITWARDEN_CLIENT_ID_VALUE="${BITWARDEN_CLIENT_ID:-}"
BITWARDEN_CLIENT_SECRET_VALUE="${BITWARDEN_CLIENT_SECRET:-}"
BITWARDEN_PASSWORD_VALUE="${BITWARDEN_PASSWORD:-}"

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

print_to_tty() {
	printf '%s' "$1" >/dev/tty
}

println_to_tty() {
	printf '%s\n' "$1" >/dev/tty
}

prompt_from_tty() {
	prompt_text="$1"
	secret_prompt="$2"
	prompt_value=""
	tty_state=""

	[ -c /dev/tty ] || return 1

	print_to_tty "$prompt_text"

	if [ "$secret_prompt" = "1" ]; then
		tty_state="$(stty -g </dev/tty)"
		stty -echo </dev/tty
		if ! IFS= read -r prompt_value </dev/tty; then
			stty "$tty_state" </dev/tty
			println_to_tty ""
			return 1
		fi
		stty "$tty_state" </dev/tty
		println_to_tty ""
	else
		IFS= read -r prompt_value </dev/tty || return 1
	fi

	printf '%s' "$prompt_value"
}

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
	WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR   Optional backup output directory for non-interactive runs.
	BITWARDEN_CLIENT_ID               Bitwarden API client ID for secret restore.
	BITWARDEN_CLIENT_SECRET           Bitwarden API client secret for secret restore.
	BITWARDEN_PASSWORD                Bitwarden vault password for secret restore.

Examples:
	curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- setup
	curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- setup --dry-run
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

run_as_target_user() {
	initialize_target_context

	if [ "$(id -un)" = "$TARGET_USER" ] && [ "${HOME:-}" = "$TARGET_USER_HOME" ]; then
		env "$@"
		return
	fi

	sudo -u "$TARGET_USER" env \
		HOME="$TARGET_USER_HOME" \
		USER="$TARGET_USER" \
		LOGNAME="$TARGET_USER" \
		"$@"
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

install_remote_collection_requirements() {
	repo_path="$(resolve_github_repository_path "$REPOSITORY_URL")" ||
		fail "REPOSITORY_URL must point to a GitHub repository"
	requirements_file="$(mktemp "${TMPDIR:-/tmp}/workstation-manager-requirements-XXXXXX.yml")"

	info "Installing Ansible collection dependencies"
	download_github_file "$repo_path" "$REPOSITORY_BRANCH" "ansible/collections/requirements.yml" "$requirements_file"
	ansible-galaxy collection install -r "$requirements_file" -p "$COLLECTIONS_INSTALL_DIR" >/dev/null
	rm -f "$requirements_file"
}

prepare_private_override_file() {
	if [ -n "$PRIVATE_OVERRIDE_LOCAL_FILE" ]; then
		return
	fi

	PRIVATE_OVERRIDE_TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/workstation-manager-private-override-XXXXXX")"
	private_override_checkout_dir="$PRIVATE_OVERRIDE_TEMP_DIR/repository"
	private_override_candidate="$private_override_checkout_dir/$PRIVATE_OVERRIDE_REPOSITORY_PATH"
	authenticated_private_override_repository_url="$(resolve_authenticated_repository_url "$PRIVATE_OVERRIDE_REPOSITORY_URL")"

	info "Fetching private override from $PRIVATE_OVERRIDE_REPOSITORY_URL#$PRIVATE_OVERRIDE_REPOSITORY_BRANCH"
	if ! GIT_TERMINAL_PROMPT=0 git clone --depth 1 --branch "$PRIVATE_OVERRIDE_REPOSITORY_BRANCH" \
		"$authenticated_private_override_repository_url" "$private_override_checkout_dir" >/dev/null 2>&1; then
		fail "Failed to fetch private override repository $PRIVATE_OVERRIDE_REPOSITORY_URL. Ensure Git can authenticate to this private repository or export WORKSTATION_MANAGER_GITHUB_TOKEN in CI."
	fi

	[ -f "$private_override_candidate" ] ||
		fail "Private override file $PRIVATE_OVERRIDE_REPOSITORY_PATH was not found in $PRIVATE_OVERRIDE_REPOSITORY_URL#$PRIVATE_OVERRIDE_REPOSITORY_BRANCH"

	PRIVATE_OVERRIDE_LOCAL_FILE="$private_override_candidate"
}

prompt_for_bitwarden_credentials_if_needed() {
	if [ -n "$BITWARDEN_CLIENT_ID_VALUE" ] &&
		[ -n "$BITWARDEN_CLIENT_SECRET_VALUE" ] &&
		[ -n "$BITWARDEN_PASSWORD_VALUE" ]; then
		return
	fi

	[ -c /dev/tty ] ||
		fail "setup requires interactive Bitwarden login for end users, or BITWARDEN_CLIENT_ID, BITWARDEN_CLIENT_SECRET, and BITWARDEN_PASSWORD in CI"

	info "Bitwarden-backed secrets restore is required; prompting for credentials"
	PROMPTED_BITWARDEN_EMAIL="$(prompt_for_required_value "BITWARDEN_EMAIL" "Bitwarden email: " 0)"
	BITWARDEN_PASSWORD_VALUE="$(prompt_for_required_value "BITWARDEN_PASSWORD" "Bitwarden vault password: " 1)"
	BITWARDEN_CLIENT_ID_VALUE=""
	BITWARDEN_CLIENT_SECRET_VALUE=""
	return
}

prompt_for_backup_output_dir_if_needed() {
	if [ -n "$BACKUP_OUTPUT_DIR" ]; then
		return
	fi

	[ -c /dev/tty ] ||
		fail "backup requires an interactive terminal for the output directory, or WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR in CI"

	PROMPTED_BACKUP_OUTPUT_DIR="$(prompt_for_required_value "WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR" "Backup output directory: " 0)"
	BACKUP_OUTPUT_DIR="$PROMPTED_BACKUP_OUTPUT_DIR"
}

prepare_action_dependencies() {
	initialize_target_context
	require_sudo
	install_ansible_packages
	install_git
	prepare_private_override_file
	install_remote_collection_requirements
}

run_ansible_pull() {
	runner_kind="$1"
	playbook_path="$2"
	dry_run="$3"
	include_private_override="$4"
	shift 4
	initialize_target_context
	authenticated_repository_url="$(resolve_authenticated_repository_url "$REPOSITORY_URL")"

	case "$runner_kind" in
	root)
		set -- \
			sudo env \
			WORKSTATION_MANAGER_USER="$TARGET_USER" \
			WORKSTATION_MANAGER_USER_HOME="$TARGET_USER_HOME" \
			ANSIBLE_COLLECTIONS_PATH="$COLLECTIONS_INSTALL_DIR:/usr/share/ansible/collections" \
			"$@"
		;;
	user)
		set -- \
			run_as_target_user \
			ANSIBLE_COLLECTIONS_PATH="$COLLECTIONS_INSTALL_DIR:/usr/share/ansible/collections" \
			"$@"
		;;
	*)
		fail "unsupported ansible runner: $runner_kind"
		;;
	esac

	set -- "$@" \
		ansible-pull \
		--purge \
		-U "$authenticated_repository_url" \
		-C "$REPOSITORY_BRANCH" \
		-d "$ANSIBLE_CHECKOUT_DIR" \
		-i "localhost," \
		-c local \
		"$playbook_path"

	if [ "$include_private_override" = "1" ] && [ -n "$PRIVATE_OVERRIDE_LOCAL_FILE" ]; then
		set -- "$@" -e "workstation_manager_private_override_file=$PRIVATE_OVERRIDE_LOCAL_FILE"
	fi

	if [ "$dry_run" = "1" ]; then
		if [ "$playbook_path" = "ansible/backup.yml" ]; then
			set -- "$@" -e "WORKSTATION_MANAGER_BACKUP_DRY_RUN=1"
		fi
		set -- "$@" --check --diff
	fi

	"$@"
}

run_setup() {
	dry_run="$1"
	prepare_action_dependencies
	prompt_for_bitwarden_credentials_if_needed

	info "Running workstation setup from $REPOSITORY_URL#$REPOSITORY_BRANCH"
	set --

	if [ -n "$BITWARDEN_CLIENT_ID_VALUE" ] &&
		[ -n "$BITWARDEN_CLIENT_SECRET_VALUE" ] &&
		[ -n "$BITWARDEN_PASSWORD_VALUE" ]; then
		set -- "$@" \
			BITWARDEN_CLIENT_ID="$BITWARDEN_CLIENT_ID_VALUE" \
			BITWARDEN_CLIENT_SECRET="$BITWARDEN_CLIENT_SECRET_VALUE" \
			BITWARDEN_PASSWORD="$BITWARDEN_PASSWORD_VALUE"
	else
		set -- "$@" \
			BITWARDEN_EMAIL="$PROMPTED_BITWARDEN_EMAIL" \
			BITWARDEN_PASSWORD="$BITWARDEN_PASSWORD_VALUE"
	fi

	run_ansible_pull root ansible/setup.yml "$dry_run" 1 "$@"
}

run_backup() {
	dry_run="$1"
	prompt_for_backup_output_dir_if_needed
	prepare_action_dependencies

	info "Running workstation backup from $REPOSITORY_URL#$REPOSITORY_BRANCH"
	run_ansible_pull \
		user \
		ansible/backup.yml \
		"$dry_run" \
		0 \
		WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR="$BACKUP_OUTPUT_DIR"
}

run_cleanup() {
	dry_run="$1"
	prepare_action_dependencies

	info "Running workstation cleanup from $REPOSITORY_URL#$REPOSITORY_BRANCH"
	run_ansible_pull root ansible/cleanup.yml "$dry_run" 1
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
