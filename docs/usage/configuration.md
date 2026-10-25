# Configuration

## Edit your private override

[Public defaults](../../ansible/group_vars/all.yml) define workstation settings
and installed software. Put non-secret personal settings in
`ansible/private.override.yml` on the `main` branch of the private
`neilime/workstation-config` repository.

Start from the [example override](../../ansible/vars/private.override.example.yml).
Use its top-level sections directly; do not wrap them in `workstation_manager`:

```yaml
development:
  github:
    account: "<your-github-username>"

home_environment:
  chezmoi:
    source: "https://github.com/neilime/workstation-config.git"

secrets:
  bitwarden:
    server: "https://vault.bitwarden.eu"
    ssh_collection_id: "<your-ssh-collection-uuid>"
    gpg_collection_id: "<your-gpg-collection-uuid>"
    browser_profiles_collection_id: "<your-browser-profiles-collection-uuid>"
    context7-api-key: "<your-context7-item-uuid>"
```

Replace the placeholders, commit and push, then run
[setup](../../README.md#set-up-or-update-the-workstation). Setup, backup, and
cleanup fetch the published override. Nested mappings merge with defaults; lists
replace the corresponding default list. Inherit software versions from public
configuration instead of copying them into the override.

`development.github.account` must identify the GitHub account setup will verify.
The Context7 item UUID is also required, including for dry runs; see
[MCP credentials](ai-tools.md#mcp-servers). Passwords, tokens, private keys, and
browser recovery words belong in Bitwarden, never Git.

Before downloading private configuration, bootstrap installs or updates GitHub CLI
and reuses its saved login. If needed, approve the browser sign-in prompt. Keep
your desktop keyring unlocked so the login can be saved. Each run downloads a
fresh checkout of the configuration repository. An explicit
`WORKSTATION_MANAGER_PRIVATE_OVERRIDE_FILE` is used as provided; see
[automation](../development/automation.md#automated-runs).

The entrypoint then reuses an unlocked Bitwarden CLI session, including an
exported `BW_SESSION`, or asks for your email and vault password. Password and
verification-code input are hidden. Rejected credentials prompt again; Ctrl+C
cancels. Bootstrap authentication can also occur during `--dry-run`.

## Application delivery

Use the [supported Ubuntu release](../../ansible/ubuntu-version). Setup installs
native APT applications and Flatpaks from the configured remote and updates them
on subsequent runs. GNOME Software also manages application updates between
setup runs, with automatic downloads enabled. Failed Flatpak operations are
retried; persistent errors stop setup. Rerun setup after resolving them to finish
installing or updating applications.

Setup removes Snap applications, snapd, and residual Snap directories. Close Snap
applications first. Snap-dependent boot or encryption blocks removal; use a
conventional Ubuntu installation.

Before removal, setup saves application data, snapshots, and affected users' Snap
directories to a root-only archive under `/var/backups/workstation-manager/snap`
and verifies it against the originals. Keep the printed archive path and copy it
to protected external storage if needed; the normal project backup does not
include it. Restore individual application files into the replacement's data
location yourself; setup does not convert profile formats. Archive failures,
mounted data, or unexpected package dependencies stop removal. Dry runs inventory
changes without stopping services, archiving, or deleting data.

### Software updates

Each setup run refreshes APT metadata and installs or updates managed APT
packages, including native vendor applications. APT preferences and explicit
package versions still apply. An update that would change a held package or
remove an installed package stops setup; resolve the reported conflict before
rerunning. Full-system upgrades remain a separate maintenance action.

Setup also updates declared system Flatpak applications and their required
runtimes. Other installed applications remain outside this update scope, except
for dependencies needed by managed packages. Package updates can restart services;
finish work in Docker containers before running setup.

Tools with configured versions use those pins. Publish pin changes before
rerunning setup; see [dependency updates](../development/dependencies.md) for
update ownership. Setup does not update project dependency manifests or lockfiles.

Use `setup --dry-run` to preview changes. Package tasks do not apply updates in
check mode, and APT previews use existing metadata. Flatpak previews report a
potential change even when an application is current. Bootstrap downloads,
installation, and authentication can still occur as described in the
[entrypoint guide](../../README.md#set-up-or-update-the-workstation).

## Prepare Bitwarden collections

Choose your vault's server; the default is `https://vault.bitwarden.eu`. Setup
requires nonempty, readable SSH and GPG collections. Backup also needs write
access for approved key saves. All actions use the managed user's cache at
`~/.config/Bitwarden CLI`, including under sudo. Failed vault reads stop the action.

A normal run switches a mismatched CLI server by logging out and authenticating
again, invalidating existing CLI sessions. Dry runs stop on a server mismatch
without changing it; run normally to select the configured server first.

Create one item per SSH key:

| Item property              | Value                                                   |
| -------------------------- | ------------------------------------------------------- |
| Name                       | Key filename, such as `id_ed25519`, without a directory |
| Custom field `private_key` | Complete private key text                               |
| Custom field `public_key`  | Complete matching public key text                       |

Setup writes `~/.ssh/<name>` and `~/.ssh/<name>.pub`. Private-key material in a
`public_key` field is rejected.

The GPG collection must contain exactly one key for Git signing:

| Item property                    | Value                                  |
| -------------------------------- | -------------------------------------- |
| Name                             | A descriptive key name                 |
| Custom field `private_key`       | ASCII-armored secret key               |
| Custom field `public_key`        | ASCII-armored public key               |
| Custom field `fingerprint`       | The key fingerprint                    |
| Optional field `ownertrust`      | GPG ownertrust record                  |
| Optional field `sub_private_key` | Additional ASCII-armored secret subkey |

The fingerprint can instead come from the ownertrust record. Setup imports the
key and writes the Git signing fingerprint and OpenPGP format to
`~/.config/git/config`, preserving other entries. Keep this file outside Chezmoi;
manage signing preferences in `~/.gitconfig`, whose settings take precedence.

The browser collection is optional. Leave its selector empty to create no managed
profiles, or follow [browser profiles](browser.md). Backup reports local profiles
missing from the collection as drift.

## Dotfiles and application settings

`home_environment.chezmoi.source` is the HTTPS or SSH repository used to initialize
`~/.local/share/chezmoi`. The companion repository can hold both overrides and
dotfiles:

```text
workstation-config/
├── .chezmoiroot
├── ansible/
│   └── private.override.yml
└── home/
    └── dot_*
```

Set `.chezmoiroot` to `home` for this layout. Keep application credentials in their
secret managers. Manage personal files in the source repository and publish changes
before relying on [backup](backup-and-restore.md).

Normal setup fetches and fast-forwards the checkout's tracking branch before
applying dotfiles. For uncommitted source edits it offers:

- `stash`: save tracked and untracked edits, update, and apply published dotfiles.
  Ignored files stay in place. Setup prints the stash recovery command; it does
  not reapply the stash automatically, and recovery can require conflict resolution.
- `skip`: keep local edits and skip all Chezmoi updates, dotfiles, and scripts for
  this run.
- `abort`, also the empty answer: stop so you can reconcile the source manually.

Unpublished commits, rewritten upstream history, unfinished Git operations, or
failed fetches stop setup. An existing checkout keeps its remote and tracking
branch; changing the source setting does not switch them.

If local managed files conflict with source state, setup lists the paths and
prompts separately: `apply` replaces them with source versions and permissions,
`skip` skips all Chezmoi dotfiles and scripts, and `abort` stops. Empty answers
abort. Unattended runs stop on either kind of conflict without replacing files.

Chezmoi `modify_` files transform the current file contents, so their pending
transformations follow normal Chezmoi application without a replacement prompt.
Use these templates for shared configuration such as [Codex settings](ai-tools.md#configuration-ownership-and-reruns)
that must preserve values managed by other tools. Ordinary file replacements
still require the conflict decision above.
Deleting a managed modifier target or replacing it with a symlink or directory
also retains the conflict guard.

Dry runs do not fetch, update the checkout, apply dotfiles, or run their scripts.
Failures print a diagnostic command to run as the managed user. Keep its output
private because templates and scripts can contain sensitive data. Existing
baseline directory permissions, including private `.config` permissions, are
preserved; private Chezmoi attributes retain restricted permissions.

Setup installs Oh My Zsh at `~/.oh-my-zsh` and selects `/usr/bin/zsh` as the login
shell. Log out and back in to use it in new terminals. Chezmoi owns shell
preferences; keep `zstyle ':omz:update' mode disabled` in `.zshrc` so setup owns
framework updates. Tracked framework edits stop updates; keep personal plugins
and themes in `custom/` or Chezmoi. Existing shell history is preserved.

## Developer tools and project files

[Public configuration](../../ansible/group_vars/all.yml) selects software and
versions. Rerun setup to apply [software updates](#software-updates), including
published pin changes. Project-specific runtimes belong in each project's `mise.toml`.
See [AI tools](ai-tools.md) for Orca, Codex, Copilot, skills, and MCP servers.

Setup installs PHP and Composer through mise. PHP compiles from source, so initial
installation and upgrades can take several minutes. In other shell contexts use
`mise exec -- php` and `mise exec -- composer`. Helm and Dive are also managed
through mise; Helm requires separately provisioned cluster access. System Node,
npm, and npx are available through `/usr/local/bin`; project mise versions can
override them inside a project.

Setup installs Skillshare and applies project `.skillshare/config.yaml` files
under `user.projects_directory` after archive restoration and GitHub login. See
[project skills](../development/project-skills.md) for declarations and updates.

### Git and GitHub

Setup requires a persistent GitHub CLI login matching `development.github.account`
and verifies it again after applying dotfiles. An unavailable keyring or mismatched
account stops setup. Unlock the keyring, inspect `gh auth status --active`, and
rerun setup. AI provider sign-in does not replace this login. Bootstrap can still
establish GitHub authentication during dry runs.

Git credentials and restored signing settings use `~/.config/git/config`.
Manage personal preferences, automatic commit/tag signing, and conditional
includes in the Chezmoi-managed `~/.gitconfig`.

`development.github.extensions` selects GitHub CLI extensions, including gh-act
and gh-stack. Binary extensions require exact releases; script extensions can
use full commit revisions. Modified script-extension checkouts stop updates.
Unselected extensions are retained.

### Visual Studio Code

`development.editor_packages` selects native APT packages. The default `code`
provides `/usr/bin/code`:

```sh
code .
code --wait path/to/file
```

Setup selects native `/usr/bin/zsh` for the integrated terminal and preserves
unrelated JSONC settings and personal profiles. Project settings may override it.
On the desktop, setup opens Visual Studio Code and waits for Settings Sync
sign-in, reusing an available Copilot GitHub account. Complete any browser approval;
if sign-in is skipped or times out, follow the printed manual steps.

### Docker

Setup installs Docker Engine, Compose, and Buildx, enables the service, and adds
the managed user to the `docker` group. Log out and back in for group membership
to take effect. Verify with `docker info`, `docker compose version`, and
`docker buildx version`. Docker group access grants root-level control.

Setup also provides `docker-compose` as an executable alias for `docker compose`,
available in terminals and scripts. Both commands use the installed Compose plugin.

For `development.github.host: github.com`, setup logs Docker into `ghcr.io` using
the GitHub CLI account and requests `write:packages` through browser authorization
when needed. Package permissions and organization SSO still control access.
Credentials use the desktop keyring; keep it unlocked and rerun setup after
changing accounts or tokens. Dry runs do not authorize permissions or log in.

Unattended setup needs a saved login with `write:packages`, or a separate
`WORKSTATION_MANAGER_GHCR_TOKEN`; see
[automation credentials](../development/automation.md#automated-runs). To grant
the scope interactively, run
`gh auth refresh --hostname github.com --scopes write:packages`, then rerun setup.

### Projects and daily reports

Setup creates `user.projects_directory` (`~/Documents/dev-projects` by default)
and adds it to the Files sidebar, preserving existing bookmarks and labels.
Changing this setting does not change the fixed default backup directory; add
other locations through the [backup options](backup-and-restore.md).

Setup enables daily notifications for repositories with local work in progress.
Run `workstation-manager-git-project-report` for a summary: one line per repository
with local changes, showing its path, branch, and number of changed files. Use
`git -C /path/to/repository status --short` for file details.

Add `--notify` to refresh the notification. Clicking it opens the saved summary at
`~/.local/state/workstation-manager/git-project-report/latest.txt`, or under
`$XDG_STATE_HOME` when set. The timer starts in the active session or at the next
graphical login.

## Desktop preferences

Setup enables dark mode and Trash in the dock. Configure ordered favorites with
`desktop.gnome.favorites`: `null` preserves the current list and `[]` clears it.
Use `browser` for the selected browser's launcher. Log out and back in after the
first setup so new Flatpak launchers appear in the dock.

Manage `~/.local/share/backgrounds/wallpaper.jpg` through Chezmoi. When present,
setup uses it in light and dark modes with zoom scaling; otherwise it preserves
the current wallpaper.

### Clipboard

Setup enables Clipboard Indicator and applies companion preferences from
`~/.config/clipboard-indicator/settings.ini`. Use `Super+Shift+V` to select a
history entry, then paste in the destination app. The companion profile disables
automatic paste so the selected entry stays current for subsequent pastes.

Ptyxis and the native Visual Studio Code terminal use the regular clipboard for
`Ctrl+V`, `Ctrl+Shift+V`, and `Shift+Insert`. This overrides the shell's literal-next-key
binding for `Ctrl+V`. Copy explicitly with `Ctrl+C` in desktop apps or `Ctrl+Shift+C`
in terminals; highlighting text alone does not replace the clipboard. Other apps
and terminal profiles may need their own bindings. Middle-click can still use
Linux's separate primary selection.

### System monitor and personal-file backups

Setup enables Vitals in the GNOME top bar. Manage its preferences through
`~/.config/vitals/settings.ini`, with a `[vitals]` section. Without that file,
Vitals uses its defaults. Log out and back in after installing or updating GNOME
extensions; setup preserves unrelated extensions.

Use Simple Scan for scanning. Verify actual device access with `scanimage -L` and
a scan; package installation cannot establish hardware compatibility.

Setup installs Déjà Dup. Configure its destination, included folders, encryption,
schedule, and retention before relying on it. Store the password in Bitwarden and
test restoration into a separate directory. Workstation-manager archives do not
establish personal-file backup coverage.
