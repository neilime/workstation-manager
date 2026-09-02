# workstation-manager

Ubuntu machine setup driven entirely from this repository.

The repository is the source of truth for the tools, packages, and machine
configuration applied during installation.

## Workstation Management

Fresh Ubuntu machine bootstrap requires only:

- internet access
- `sudo`
- Bitwarden credentials plus the vault password available for the interactive login prompt

The public entrypoint is `workstation.sh`. The user does not need a local checkout
to install, re-apply, preview, or back up the machine state.

Recommended interactive setup command:

```sh
WORKSTATION_MANAGER_RESTORE_ARCHIVE=/path/to/workstation-manager-backup-<timestamp>.tar.gz \
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- setup
```

`sh -s --` tells `sh` to read the script from standard input and pass the
remaining arguments to it.

- no extra argument: run the `setup` action
- `--dry-run`: preview the selected action in Ansible check mode

When run interactively, the script prompts for required action-specific
inputs such as the backup output directory.

The script bootstraps its own dependencies and applies the repository with
`ansible-pull`. Running it again later is the normal way to re-apply the managed
workstation state. It uses a hidden checkout internally; that repository clone
is purged after each run and is an implementation detail, not part of the user
workflow.

The public interface is intentionally small: setup, cleanup, backup, and help.

### Secrets

`setup`, `setup --dry-run`, `backup`, and `backup --dry-run` all require
Bitwarden-backed SSH/GPG access.

- Setup always restores SSH and GPG keys from the declared collections.
- Backup checks the local SSH and GPG key material against those same Bitwarden
  collections before creating the archive.
- If backup finds key drift, it asks whether to add, update, or ignore each
  mismatch.
- The resolved Ansible configuration must define
  `secrets.bitwarden.ssh_collection_id` and
  `secrets.bitwarden.gpg_collection_id`.
- `workstation.sh` uses API credentials when `BITWARDEN_CLIENT_ID`,
  `BITWARDEN_CLIENT_SECRET`, and `BITWARDEN_PASSWORD` are already present in the
  environment, which is the intended CI and end-to-end automation path.
- End users are prompted for the Bitwarden email and vault password instead of
  exporting them in the shell.

### Private Overrides

Setup, cleanup, and backup automatically fetch `ansible/private.override.yml`
from the fixed `neilime/workstation-config` repository with Git and merge it as
the private override layer.

The Chezmoi source is fixed to `neilime/workstation-config`.

Keep any non-secret workstation overrides you do not want in this public
repository in that tracked file inside `neilime/workstation-config`.

Suggested layout:

```text
workstation-config/
   ansible/private.override.yml
   dot_*
```

Keep actual secrets in Bitwarden rather than writing them into that local file.

Because `neilime/workstation-config` is private, the bootstrap machine must be
able to authenticate to that Git repository.

- Interactive setup bootstraps `gh`, prompts for `gh auth login`, and runs
  `gh auth setup-git` automatically when private repository access is missing.
- CI and end-to-end automation can provide `WORKSTATION_MANAGER_GITHUB_TOKEN`
  for private GitHub repository access.

### Examples

To preview changes without applying them:

```sh
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- setup --dry-run
```

To preview cleanup drift and removable artifacts without applying changes:

```sh
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- cleanup --dry-run
```

To run setup and replay a previously created backup archive:

```sh
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | WORKSTATION_MANAGER_RESTORE_ARCHIVE=/path/to/workstation-manager-backup.tar.gz sh -s -- setup
```

To show the remote command help:

```sh
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- help
```

### Setup

Bootstrap dependencies and converge the workstation.

Setup also fetches `ansible/private.override.yml` from the fixed
`neilime/workstation-config` repository.

On a fresh Ubuntu machine, if access to the private
`neilime/workstation-config` repository is not already configured, the setup
bootstrap installs `gh`, prompts for `gh auth login`, runs
`gh auth setup-git`, and then continues automatically.

If you want setup to replay a backup, provide
`WORKSTATION_MANAGER_RESTORE_ARCHIVE=/path/to/workstation-manager-backup-<timestamp>.tar.gz`.

If `WORKSTATION_MANAGER_RESTORE_ARCHIVE` is also present during `setup`, the
setup flow replays that backup archive after the managed workstation baseline is
applied.

#### Chezmoi

For the home environment, setup installs a pinned `chezmoi` binary, writes the
managed Chezmoi machine-data config, initializes the fixed
`neilime/workstation-config` dotfiles source, and applies it to the user home.

#### Bitwarden

Setup restores SSH and GPG material from Bitwarden.

Interactive runs prompt for the Bitwarden login details. CI and other
automated runs can provide the Bitwarden API credentials through environment
variables.

### GNOME Desktop

Setup installs the bundled wallpaper in the managed user's local data
directory and selects it for both light and dark GNOME color schemes.

### Browser First Run

The repository installs Google Chrome, sets it as the default browser, creates
stable managed profile directories, and applies browser-wide policies such as
baseline extensions, password-manager behavior, and startup defaults.

The repository does not sign browser profiles in for you and does not restore
profile-private state such as sessions, cookies, or client bookmarks.

After a fresh install:

1. Launch Chrome.
2. Open each declared profile and authenticate it with the correct browser-sync
   or identity account.
3. Sign in to the Bitwarden extension for each profile that needs password
   access.
4. Let browser sync restore bookmarks, extensions, and settings where sync is
   approved.
5. For manual or client profiles, restore only reviewed material such as an
   encrypted bookmark export or approved onboarding notes.

Treat browser recovery material as a secret. If you keep recovery notes in
local notes, an encrypted export, or another private workflow that stays
outside this repository. Do not commit raw browser databases, cookies,
sessions, or client bookmark sets to this repository.

### Developer Toolchains

The workstation now manages ephemeral developer toolchains with `mise`.

- Common workstation defaults live in `development.mise.tools` and are rendered
  to `~/.config/mise/config.toml`.
- Project-specific overrides should live in each project's own `mise.toml`,
  restored with the rest of the home/project configuration rather than being
  generated from Ansible state.
- Shell activation is managed automatically for Bash and Zsh login and
  interactive startup files.

See `ansible/vars/private.override.example.yml` for a private override example
covering non-secret workstation data.

### Development Projects Layout

`~/Documents/dev-projects` is the expected home for user-maintained project data.
The backup includes that directory as-is so both active work and long-lived local
material are preserved.

Suggested layout:

```text
~/Documents/dev-projects/
   _0_backup/
   notes/
   workspaces/
   client-a/
   side-project-b/
```

- `_0_backup`: non-Git legacy material such as archived former-client work or older side projects that still need to be kept.
- `notes`: personal notes, working documents, and other reference material that should stay with the development archive.
- `workspaces`: Visual Studio Code workspace definitions and related local workspace configuration.
- Other top-level directories: live projects. These are the current client or side-project folders and may themselves contain one or more Git repositories.

Treat this directory as the canonical location for project state you want the
workstation backup to preserve. The repository does not attempt to classify or
filter project folders beyond archiving the full `~/Documents/dev-projects`
tree.

For Git-backed live projects, the backup keeps the checked-out working tree but
excludes nested `.git` directories. This avoids inflating the archive with Git
object storage and clone metadata that can be recovered from the remote when
needed. The trade-off is that local-only Git state such as branch metadata,
stashes, reflogs, and custom remotes is not preserved by the backup.

### Cleanup

Prune removable workstation artifacts, remove stale managed directories, and
write a drift report under the managed user state directory.

### Restore During Setup

When `setup` receives `WORKSTATION_MANAGER_RESTORE_ARCHIVE`, it replays the
backup archive after package installation, browser/profile setup, and
home-environment bootstrap. That gives the machine its managed baseline first,
then restores backed-up user data on top.

- The archive path comes from `WORKSTATION_MANAGER_RESTORE_ARCHIVE`.
- Setup extracts the backup tarball back into `/`, which recreates the backed-up home-directory paths in place.
- If a paired `*.git-repositories.json` sidecar is present, setup reattaches restored Git-backed project directories by cloning their recorded primary remote and overlaying the backed-up working tree onto that clone.
- If the paired manifest file and `browser-bookmarks/` directory are still present next to the archive, the restore role reports them so the operator can inspect the manifest and manually import bookmark exports if needed.
- If a recorded remote cannot be cloned, the restore step keeps the plain restored worktree in place rather than discarding project files.

### Backup

Create a user-state backup, not a full-system image or bare-metal snapshot.

Interactive backup prompts for the destination, any chezmoi synchronization
decisions, and any Bitwarden key-sync decisions.

CI and other non-interactive runs can still provide
`WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR=/path/to/output-dir`, but a backup run
that detects unsynchronized chezmoi state or unsynchronized SSH/GPG keys fails
instead of guessing how to modify them.

The backup does the following:

- Managed chezmoi state: checks managed chezmoi drift before archiving and asks
  whether to `re-add`, `apply`, or ignore any drift it finds.
- Chrome configuration: archives `~/.config/google-chrome` as part of the main backup tarball.
- Managed browser profiles: archives `~/.local/share/workstation-manager/browser-profiles` from the workstation-managed profile store.
- Development projects: archives `~/Documents/dev-projects` so user project work is included in the backup, while excluding nested `.git` directories.
- Git repository inventory: writes `*.git-repositories.json` beside the archive so setup can reattach restored project directories to their remotes.
- Workstation-manager user config: archives `~/.config/workstation-manager`.
- Chrome bookmark export: copies discovered Chrome bookmark files to `browser-bookmarks/*.json` for selective restore without restoring the full browser data directory.
- Backup manifest: writes a `.manifest.txt` file that records the generated archive, included or missing paths, and exported bookmark files.

## Development

The `Makefile` is for repository development and validation only. It is not the
public workstation-management interface.

### Host Requirements

Required for normal repository work:

- Docker Engine
- Git
- Make

Required only for end-to-end validation:

- cURL
- Lima
- `qemu-img`
- `qemu-system-x86_64`

### Quick Start

```sh
make setup
make lint
make check-ansible
make test
```

### Static Validation

Repository-side validation is split into three layers:

- `make lint` runs the repository lint surface
- `make check-ansible` runs playbook syntax validation
- `make test` runs `ansible-test sanity` and `ansible-test units`

### End-to-End Validation

The end-to-end flow runs a real user-setup-like process inside an Ubuntu VM.
It fetches `workstation.sh` over HTTPS, executes the same remote setup path that a
user runs, then verifies the workstation in three action-scoped phases:
`backup`, `setup`, and `cleanup`. Each action runs first, then its matching
assertion set runs before the next action starts.

After setup, the QEMU desktop is captured to
`.reports/screenshots/e2e-setup-desktop.png`. Set `SCREENSHOTS_DIR` to override
that location. CI uploads the screenshot and its capture log as an artifact.

```sh
make e2e-up
make e2e-test
make e2e-down
```

### CI

CI uses the same repository entry points as local development:

- `make setup`
- `make lint`
- `make check-ansible`
- `make test`
- `make e2e-up`
- `make e2e-test`

The static and end-to-end layers stay separate in CI as well:

- static checks cover linting, Ansible syntax validation, and `ansible-test`
- end-to-end validation covers the remote `setup`, `backup`, and `cleanup` paths plus VM-level assertions
