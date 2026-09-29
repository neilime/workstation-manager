#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=e2e-common.sh
source "$script_dir/e2e-common.sh"

resolve_e2e_workstation_context "${1:-workstation-manager-v1}"
require_e2e_env_vars \
	BITWARDEN_CLIENT_ID \
	BITWARDEN_CLIENT_SECRET \
	BITWARDEN_PASSWORD

backup_root="/tmp/workstation-manager-e2e-backup"
target_user_home="$(resolve_e2e_target_user_home)"
projects_dir="${target_user_home}/Documents/dev-projects/client-restore"
managed_config_dir="${target_user_home}/.config/workstation-manager"
git_remote_dir="/tmp/workstation-manager-e2e-origin-client-restore.git"
git_seed_dir="/tmp/workstation-manager-e2e-seed-client-restore"

run_e2e_vm_shell "rm -rf '$backup_root' '$git_remote_dir' '$git_seed_dir'"

run_e2e_vm_shell "$(
	cat <<EOF
mkdir -p '$managed_config_dir'
git init --bare '$git_remote_dir'
git init --initial-branch main '$git_seed_dir'
git -C '$git_seed_dir' config user.name 'E2E User'
git -C '$git_seed_dir' config user.email 'e2e@example.com'
printf '%s\n' 'remote-base' >'$git_seed_dir/tracked.txt'
git -C '$git_seed_dir' add tracked.txt
git -C '$git_seed_dir' commit -m 'initial commit'
git -C '$git_seed_dir' remote add origin '$git_remote_dir'
git -C '$git_seed_dir' push origin main
git --git-dir='$git_remote_dir' symbolic-ref HEAD refs/heads/main
git clone '$git_remote_dir' '$projects_dir'
printf '%s\n' 'restored-project' >'$projects_dir/project.txt'
printf '%s\n' 'local-untracked' >'$projects_dir/local-note.txt'
printf '%s\n' 'local-change' >>'$projects_dir/tracked.txt'
printf '%s\n' 'managed-config-fixture' >'$managed_config_dir/restore-fixture.txt'
EOF
)"

# Build a published, empty Chezmoi state before exercising the real remote backup
# wrapper. Do not replace an existing workstation's dotfiles checkout or config.
recovery_fixture_dir="$(run_e2e_vm_shell 'mktemp -d /tmp/workstation-manager-e2e-recovery.XXXXXX')"
cleanup_recovery_fixture() {
	run_e2e_vm_shell "
		set -eu
		if [ -f '$recovery_fixture_dir/source-created' ]; then
			rm -rf '$target_user_home/.local/share/chezmoi'
		fi
		if [ -f '$recovery_fixture_dir/config-created' ]; then
			rm -f '$target_user_home/.config/chezmoi/chezmoi.yaml'
		fi
		rm -rf '$recovery_fixture_dir'
	"
}
trap cleanup_recovery_fixture EXIT

stream_e2e_entrypoint_script | sed '$d' |
	run_e2e_lima_shell sh -c "umask 077; cat >'$recovery_fixture_dir/wrapper-definitions.sh'"

run_e2e_lima_shell env \
	E2E_RECOVERY_FIXTURE_DIR="$recovery_fixture_dir" \
	E2E_REPOSITORY_PATH="$E2E_REPOSITORY_PATH" \
	REPOSITORY_URL="$E2E_REPOSITORY_URL" \
	REPOSITORY_BRANCH="$E2E_BRANCH_NAME" \
	WORKSTATION_MANAGER_GITHUB_TOKEN="${WORKSTATION_MANAGER_GITHUB_TOKEN:-}" \
	BITWARDEN_CLIENT_ID="$BITWARDEN_CLIENT_ID" \
	BITWARDEN_CLIENT_SECRET="$BITWARDEN_CLIENT_SECRET" \
	BITWARDEN_PASSWORD="$BITWARDEN_PASSWORD" \
	bash -s <<'FIXTURE'
set -euo pipefail
umask 077
fixture_dir="$E2E_RECOVERY_FIXTURE_DIR"
source_dir="$HOME/.local/share/chezmoi"
config_path="$HOME/.config/chezmoi/chezmoi.yaml"
# This fixture clears browser profile management in the published override, so
# an existing local Brave tree must not block the backup smoke test.
for existing_path in "$source_dir" "$config_path"; do
	if [[ -e "$existing_path" || -L "$existing_path" ]]; then
		printf 'Backup fixture requires absent Chezmoi state: %s\n' "$existing_path" >&2
		exit 1
	fi
done

# shellcheck disable=SC1091
source "$fixture_dir/wrapper-definitions.sh"
prepare_action_dependencies backup
download_github_file "$E2E_REPOSITORY_PATH" "$REPOSITORY_BRANCH" \
	ansible/group_vars/all.yml "$fixture_dir/public.yml"
mkdir -p "$fixture_dir/seed" "$(dirname "$config_path")"
touch "$fixture_dir/config-created"
chezmoi_version="$(python3 - "$PRIVATE_OVERRIDE_LOCAL_FILE" "$fixture_dir" "$source_dir" "$config_path" <<'PYTHON'
import pathlib
import sys
import yaml

private_path, fixture_path, source_path, config_path = sys.argv[1:]
fixture = pathlib.Path(fixture_path)
config = yaml.safe_load(pathlib.Path(private_path).read_text())
public = yaml.safe_load((fixture / "public.yml").read_text())["workstation_manager"]
config.setdefault("secrets", {}).setdefault("bitwarden", {})["browser_profiles_collection_id"] = ""
chezmoi = config.setdefault("home_environment", {}).setdefault("chezmoi", {})
version = chezmoi.get("version") or public["home_environment"]["chezmoi"]["version"]
chezmoi.update(source=str(fixture / "origin.git"), bin_path=str(fixture / "chezmoi"), config_path=config_path)
(fixture / "seed" / "private.override.yml").write_text(yaml.safe_dump(config))
pathlib.Path(config_path).write_text(yaml.safe_dump({"sourceDir": source_path}))
print(version)
PYTHON
)"
printf '*\n' >"$fixture_dir/seed/.chezmoiignore"
git init --initial-branch main "$fixture_dir/seed"
git -C "$fixture_dir/seed" config user.name 'E2E User'
git -C "$fixture_dir/seed" config user.email 'e2e@example.com'
git -C "$fixture_dir/seed" add .chezmoiignore private.override.yml
git -C "$fixture_dir/seed" commit -m 'published backup recovery fixture'
git init --bare "$fixture_dir/origin.git"
git -C "$fixture_dir/seed" remote add origin "$fixture_dir/origin.git"
git -C "$fixture_dir/seed" push --set-upstream origin main
git --git-dir="$fixture_dir/origin.git" symbolic-ref HEAD refs/heads/main
curl -fsSL "https://github.com/twpayne/chezmoi/releases/download/v${chezmoi_version}/chezmoi-linux-$(dpkg --print-architecture)" \
	-o "$fixture_dir/chezmoi"
chmod 0755 "$fixture_dir/chezmoi"
touch "$fixture_dir/source-created"
CHEZMOI_CONFIG_FILE="$config_path" "$fixture_dir/chezmoi" init "$fixture_dir/origin.git"
test -z "$(CHEZMOI_CONFIG_FILE="$config_path" "$fixture_dir/chezmoi" status)"

# A fresh VM has no local keys. Restore them before backup so its recovery
# checks can verify the configured collections without an interactive decision.
PRIVATE_OVERRIDE_LOCAL_FILE="$source_dir/private.override.yml"
run_ansible_pull ansible/prepare_e2e_backup.yml 0
FIXTURE

run_e2e_workstation_action \
	backup \
	"WORKSTATION_MANAGER_PRIVATE_OVERRIDE_FILE=$target_user_home/.local/share/chezmoi/private.override.yml" \
	"BITWARDEN_CLIENT_ID=${BITWARDEN_CLIENT_ID}" \
	"BITWARDEN_CLIENT_SECRET=${BITWARDEN_CLIENT_SECRET}" \
	"BITWARDEN_PASSWORD=${BITWARDEN_PASSWORD}" \
	"WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR=$backup_root"
