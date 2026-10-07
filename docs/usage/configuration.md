# Configuration

## Edit your private override

[Public defaults](../../ansible/group_vars/all.yml) define the installed packages
and workstation settings. Put personal overrides in
`ansible/private.override.yml` in the private `neilime/workstation-config`
repository, on its `main` branch.

Start from the [example override](../../ansible/vars/private.override.example.yml).
The example contains `development`, `home_environment`, and `secrets`; do not wrap
them in `workstation_manager`. General workstation settings inherit the public defaults.

For example:

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
```

Set your GitHub username and replace the collection placeholders with your
Bitwarden collection UUIDs. Commit and push the file, then run `setup` using the
[Readme command](../../README.md#set-up-or-update-the-workstation).
Setup, backup, and cleanup fetch that published override unless you select a local
file. Nested mappings are merged with the defaults; lists replace the
corresponding default list.

The GitHub account is required: missing or blank `development.github.account`
stops configuration validation before Ansible applies workstation roles. The
username is not a secret; it identifies the account whose persistent login setup
must verify.

Keep passwords, tokens, private keys, and browser recovery words in Bitwarden. Only
non-secret settings and collection identifiers belong in Git.

To use a local override instead:

```sh
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | \
  WORKSTATION_MANAGER_PRIVATE_OVERRIDE_FILE=/absolute/path/private.override.yml sh -s -- setup
```

## Application delivery

Setup supports one Ubuntu release, recorded in
[the baseline](../../ansible/ubuntu-version). Update Ubuntu before using a revision
that selects a newer release. Setup uses the system Python for host modules and
an isolated Ansible controller shared with the test image.

After installing the selected applications, setup removes all Snap applications,
snapd, and residual Snap directories. Close Snap applications before running setup.
Boot or encryption that depends on Snap blocks setup before removal; use a
conventional Ubuntu installation for this workstation.

Before removal, setup stops Snap services and saves application data, existing
snapshots, and affected accounts' Snap directories in a root-only archive under
`/var/backups/workstation-manager/snap`. It compares the archive with the originals
before deleting them. The printed archive path is retained after setup. Copy it to
protected external storage if needed; the normal project backup does not include
this directory automatically. Restore individual application files into the
replacement's data location; setup does not convert application profile formats.
An archive failure, mounted data, or an unexpected package dependency stops
removal. A dry run inventories the planned removal without stopping services or
removing data; archive integrity is checked when setup applies the plan.
An APT preference prevents automatic snapd reinstallation.

GNOME Software and its Flatpak plugin manage applications and updates, with
automatic downloads enabled for the managed account. Setup installs Ptyxis and
includes it in the default dock favorites while preserving existing terminal profiles.

To run a reviewed immutable revision, use the same full commit for the entrypoint
and its Ansible checkout:

```sh
revision="<reviewed-40-character-commit>"
wget -qO- "https://raw.githubusercontent.com/neilime/workstation-manager/${revision}/workstation.sh" | \
  REPOSITORY_BRANCH="$revision" sh -s -- setup
```

## Prepare Bitwarden collections

Setup, backup, and cleanup share the managed user's Bitwarden CLI cache at
`~/.config/Bitwarden CLI`, including when launched through sudo. Authentication
and vault synchronization happen before collection reads; a failed read stops
the action.

Choose the server that hosts your vault; the default is
`https://vault.bitwarden.eu`. Setup requires nonempty SSH and GPG collections.
Your account must be able to read them. Backup also needs write access when you
approve adding or updating keys.

When the CLI uses a different server, normal runs check that login credentials
are available, log out of the current CLI account, select the configured server,
and authenticate again. This invalidates existing CLI sessions. Dry runs stop on
a server mismatch without logging out or changing the server; run normally to
select the configured server first.

Create one item per SSH key. Use these fields:

| Item property              | Value                                                    |
| -------------------------- | -------------------------------------------------------- |
| Name                       | Key filename, such as `id_ed25519`, without a directory. |
| Custom field `private_key` | Complete private key text.                               |
| Custom field `public_key`  | Complete public key text.                                |

Setup writes the pair to `~/.ssh/<name>` and `~/.ssh/<name>.pub`.

The GPG collection must contain exactly one key for Git signing:

| Item property              | Value                                   |
| -------------------------- | --------------------------------------- |
| Name                       | A descriptive key name.                 |
| Custom field `private_key` | ASCII-armored secret key.               |
| Custom field `public_key`  | ASCII-armored public key.               |
| Custom field `fingerprint` | The key fingerprint.                    |
| Optional `ownertrust`      | GPG ownertrust record.                  |
| Optional `sub_private_key` | Additional ASCII-armored secret subkey. |

The last two entries are custom fields. A fingerprint can also be read from an
ownertrust record when no `fingerprint` field is provided. Setup imports the key
and writes its Git signing fingerprint and OpenPGP format to
`~/.config/git/config`, preserving other entries and the Chezmoi-managed
`~/.gitconfig`. Choose automatic commit and tag signing in your Chezmoi Git
configuration. Git reads both files; settings in `.gitconfig` take precedence.
Keep `.config/git/config` outside Chezmoi's managed source.

The browser collection is optional. Leave its selector empty to create no managed
profiles, or follow [browser profiles](browser.md) to populate it. Backup reports
local browser profiles missing from the collection as drift.

## Dotfiles and application settings

`home_environment.chezmoi.source` selects the Git repository used to initialize
`~/.local/share/chezmoi`. Use a full HTTPS or SSH Git URL. Setup applies its
dotfiles to your home directory. An existing checkout is reused; changing the
source setting does not switch its remote. Setup uses the managed source,
configured `home_environment.chezmoi.config_path`, and target home explicitly,
including when your terminal or IDE sets a different `XDG_DATA_HOME`. Existing
baseline directory permissions are preserved, including private `.config`
permissions applied by your dotfiles.

Every normal setup checks pending changes with `chezmoi status` and applies them.
Dry runs do not apply dotfiles. If local changes conflict with the source, setup
lists the affected paths and prompts before replacing them.
Choose `apply` to use the source versions and permissions for those paths,
`skip` to keep your local changes and continue setup without applying any Chezmoi
dotfiles or scripts for this run, or `abort` to stop setup and reconcile your
changes with the printed interactive Chezmoi command. An empty answer aborts.
Approved replacements are checked before setup applies the remaining dotfiles
and runs their scripts. A run without an
interactive terminal stops at conflicts without replacing them. If inspection or
application fails, setup prints a command to diagnose the error locally as the
target user. Command output stays private because templates and scripts may
contain sensitive data. Application
errors use an actual `apply` command for diagnosis: a dry run does not run scripts
and can exit without an error message on conflicts.

Setup installs [Oh My Zsh](https://github.com/ohmyzsh/ohmyzsh) into `~/.oh-my-zsh`
before applying dotfiles. The framework revision is pinned in
[public configuration](../../ansible/group_vars/all.yml) and maintained by
Renovate. This is an internal setup dependency, with no private
override setting. Setup updates the checkout to that revision and refuses to
overwrite tracked local edits. Put personal plugins and themes in its `custom/`
directory or manage them through Chezmoi.

The companion shell files select Oh My Zsh plugins, activate mise, and use
Starship for the prompt. Docker plugins load only when Docker is available;
Yarn, Composer, AWS, pre-commit, and thefuck integrations also require their
commands. These shell hooks do not install software. When `batcat` is available,
`bat` invokes it directly and `cat` invokes `batcat -pp`. Déjà is outside the
default selection, and setup preserves existing shell history.

Setup owns the pinned framework updates; keep `zstyle ':omz:update' mode disabled`
in `.zshrc`. Chezmoi owns shell preferences. Setup selects `/usr/bin/zsh` as the
login shell; log out and back in to use it in new terminals. Existing terminals
keep their current shell.

Maintain dotfiles in that source repository. Before backup, review local changes;
the [backup workflow](backup-and-restore.md) offers to capture or reapply managed
files and requires the source checkout to be published to its Git remote.

The companion repository can contain both configuration and dotfiles:

```text
workstation-config/
├── .chezmoiroot
├── ansible/
│   └── private.override.yml
└── home/
    └── dot_*
```

Set `.chezmoiroot` to `home` for this layout. Application credentials belong in
their secret manager; sign in to Visual Studio Code Settings Sync to recover editor settings
and extensions. Brave recovery is covered in the [browser guide](browser.md).

## Developer tools and project files

Manage Git preferences, including `gc.auto`, `commit.gpgsign`, and `tag.gpgsign`,
in your Chezmoi `~/.gitconfig`. The companion repository enables automatic garbage
collection with `gc.auto = 6700` and enables commit and tag signing. Repository-local
settings and conditional includes can override those preferences.

`development.editor_packages` selects native APT packages. The default `code`
comes from [Microsoft's stable repository](https://code.visualstudio.com/docs/setup/linux),
with `/usr/bin/code` available to terminals, Git, and agents:

```sh
code .
code --wait path/to/file
```

The integrated terminal uses native `/usr/bin/zsh`. Setup preserves unrelated
JSONC settings and personal profiles. Open Visual Studio Code after setup, check
your profiles and extensions, and complete sign-in if requested. Project settings
may override the selected terminal. Settings Sync uses the native configuration
directory.

Public [development defaults](../../ansible/group_vars/all.yml) own software
selection and release pins. Setup always installs Codex and GitHub Copilot as
system-wide npm commands. Their reviewed versions live in `development.npm_packages`
and are maintained by Renovate. Both commands are verified without shell activation;
complete each product's sign-in when first using it.

Setup always installs PHP through mise's `vfox:jdx/vfox-php` backend. The exact PHP
release lives in `development.mise.tools`; there is no PHP enable switch or APT
runtime alternative. The backend compiles PHP, so setup installs its compiler and
required library headers. Initial installation and PHP upgrades can take several
minutes. Project PHP versions belong in each project's `mise.toml`.

Composer is also always installed through mise. Its `github:composer/composer`
entry in `development.mise.tools` pins the official release; mise verifies the
release asset checksum and exposes the `composer` command. Setup checks both
executables through mise. Use `mise exec -- php` or `mise exec -- composer` from
other shell contexts.
Renovate maintains both release pins. Existing project files and PHP installations
are preserved.

Setup always installs Helm and Dive through `development.mise.tools`, and gh-act
and gh-stack through `development.github.extensions`. Their versions remain in
public configuration and are maintained by Renovate.

Helm supplies neither kubectl nor cluster credentials.
Check the [Helm/Kubernetes compatibility policy](https://helm.sh/docs/topics/version_skew/)
against the target cluster and test project charts/plugins before using it.
Project runtime overrides belong in each project's `mise.toml`. Global mise tools
use exact releases and must not take ownership of system Node, GitHub CLI, or Docker.
Renovate maintains the selected tool versions, including optional pins.

Setup always installs and configures the release pinned by `development.orca.version`.
It checks the architecture-specific package digest and seeds only missing settings.
Existing workspaces and preferences remain intact. Renovate maintains the release pin.

The agents workload installs pinned [Codex](https://learn.chatgpt.com/docs/codex/cli)
and [Copilot](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli)
commands through system npm and verifies them without shell activation. Their
preferences and shared skills remain in Chezmoi. Product sign-in and access to a
subscription remain separate first-use steps.

`development.node.version` pins the complete system Node.js LTS distribution,
including npm and npx, exposed through `/usr/local/bin`. Project-local mise
versions may override it inside a project. Update native vendor packages through
APT; cleanup only previews pending upgrades. Rerun setup after merging release
pin updates.

GitHub CLI comes from its official APT repository. Setup requires a persistent
login for `development.github.host` matching `development.github.account`, after
applying dotfiles. It reuses a valid OS-keyring login, can save a supplied bootstrap
token in an unlocked credential store, or opens one browser login from the managed
user's terminal. An unavailable keyring, failed authentication, or unexpected
account stops setup. Unattended runs need usable stored credentials or a token
plus an unlocked credential store.

Provide a bootstrap token through `WORKSTATION_MANAGER_GITHUB_TOKEN`, never through
the private override. A token is unnecessary when the configured account already
has a working keyring login or you complete the interactive browser login.

Git credential settings are stored alongside restored signing settings in
`~/.config/git/config`; existing working helpers are reused. Token
values stay out of configuration templates and logs. If authentication fails,
unlock the desktop keyring, inspect `gh auth status --active`, and rerun setup.
Agent product sign-in does not replace this GitHub CLI login.

GitHub binary extensions, including gh-act and gh-stack, require exact release
versions in the public configuration. Full commit revisions are supported only
for script extensions. Setup verifies installed revisions and replaces outdated pins;
modified script-extension checkouts stop the update for reconciliation. Unselected
extensions are retained. `gh-act` remains a local CI debugging tool; its runner
images and behavior do not replace hosted CI qualification.

Docker Engine, its CLI, containerd, Compose, and Buildx come from Docker's official
APT repository for the actual Ubuntu release. Setup enables `docker.service` and
adds the managed user to the `docker` group. Log out and back in once if an existing
desktop session does not yet have that group. Verify with `docker info`,
`docker compose version`, and `docker buildx version`.
Docker group access grants root-level control; see
[Docker's post-installation guide](https://docs.docker.com/engine/install/linux-postinstall/).

Setup creates `user.projects_directory` (`~/Documents/dev-projects` by default)
and adds it to the Files sidebar bookmarks. Existing bookmarks and custom labels
are preserved.

The default backup includes `~/Documents/dev-projects`. Keep project files there
or include another location through the [backup options](backup-and-restore.md).
Changing `user.projects_directory` changes setup paths; backup still uses its
fixed default directory and any explicitly added paths.

Setup also installs `workstation-manager-git-project-report`. Run it manually to
print the Git repositories under `user.projects_directory` that still have local
work in progress. Setup always enables daily desktop notifications and installs
`libnotify-bin`. The timer starts in the active user session, or at the next
graphical login when no session is available.

Setup always enables dark mode and shows Trash in Ubuntu Dock. The
[public defaults](../../ansible/group_vars/all.yml) select Brave and define the
ordered dock favorites. Set `desktop.gnome.favorites: null` to preserve existing
favorites or `favorites: []` to clear the dock.
Use `browser` in the favorites list for the selected browser adapter's desktop entry.

Manage the wallpaper through Chezmoi at
`~/.local/share/backgrounds/wallpaper.jpg`. Setup selects that image for both light
and dark modes with zoom scaling when it exists; it preserves the current
wallpaper settings when the file is absent.

### Clipboard and personal-file backup

Setup installs and enables Clipboard Indicator as the managed clipboard history
extension. Inherit its version and checksum pins from public configuration.
The companion repository owns `~/.config/clipboard-indicator/settings.ini`.

Setup verifies the archive digest, identity, and detected GNOME version before
installation. It preserves unrelated extensions and keeps GNOME compatibility
validation enabled. Log out and back in after installation or an update.
The companion profile retains 200 entries, images, search, pins, whitespace, and
paste-on-select, with `Super+Shift+V` as its only global shortcut. Check that this
shortcut is free in your desktop and apps during the
[Wayland acceptance checks](../development/adr/adr-0001-workstation-toolchain.md#gnome-clipboard-indicator).

Setup closes CopyQ and removes its system and user Flatpak installations.
`~/.var/app/com.github.hluk.copyq` and `~/.config/copyq` remain intact for recovery;
existing history is not imported into Clipboard Indicator. Setup preserves
existing `~/.config` permissions, including Chezmoi's private mode.

Simple Scan uses Ubuntu's native `simple-scan` and `sane-utils` packages. Setup
removes duplicate system and user Flatpak installations without deleting their
data. Use `scanimage -L` and Simple Scan with the actual scanner to confirm device
access; a package check cannot establish hardware compatibility.

Setup installs Déjà Dup. Configure its destination, included folders,
encryption, schedule, and retention before relying on routine personal-file
backups. Keep the backup password in Bitwarden and complete a restore to a
separate directory, comparing the restored files with their originals.
Manager archives and application installation do not prove this coverage.

## Automated runs

Provide credentials through your automation's secret store:

| Environment variable               | Purpose                                                                                                    |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `WORKSTATION_MANAGER_GITHUB_TOKEN` | Access private repositories, authenticate downloads, and establish the configured account's keyring login. |
| `BITWARDEN_CLIENT_ID`              | Bitwarden API client ID.                                                                                   |
| `BITWARDEN_CLIENT_SECRET`          | Bitwarden API client secret.                                                                               |
| `BITWARDEN_PASSWORD`               | Unlock the Bitwarden vault.                                                                                |

Setup passes the GitHub token to mise and GitHub CLI extension commands through
their environment and uses it for the Orca release lookup, including previews.
The Orca request keeps the token out of logs and redirected requests. Setup does
not write it to application configuration or shell activation files.

All three Bitwarden values must be present to skip interactive credential prompts.
Automation must also supply `WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR` for backup.
Recovery checks that require a human decision stop noninteractive backup; browser
Sync completion requires interactive confirmation.

Do not put credential values in command examples, configuration files, or Git.
