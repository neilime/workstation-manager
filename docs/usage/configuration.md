# Configuration

## Edit your private override

[Public defaults](../../ansible/group_vars/all.yml) define the installed packages
and workstation settings. Put personal overrides in
`ansible/private.override.yml` in the private `neilime/workstation-config`
repository, on its `main` branch.

Start from the [example override](../../ansible/vars/private.override.example.yml).
The override starts with sections such as `desktop`, `home_environment`, and
`secrets`; do not wrap them in `workstation_manager`.

For example:

```yaml
desktop:
  browser: brave

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

Replace the collection placeholders with your Bitwarden collection UUIDs. Commit
and push the file, then run `setup` using the [Readme command](../../README.md#set-up-or-update-the-workstation).
Setup, backup, and cleanup fetch that published override unless you select a local
file. Nested mappings are merged with the defaults; lists replace the
corresponding default list.

Keep passwords, private keys, and browser recovery words in Bitwarden. Only
non-secret settings and collection identifiers belong in Git.

To use a local override instead:

```sh
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | \
  WORKSTATION_MANAGER_PRIVATE_OVERRIDE_FILE=/absolute/path/private.override.yml sh -s -- setup
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
and configures Git commit and tag signing in `~/.config/git/config`, preserving
other entries in that file and leaving the
Chezmoi-managed `~/.gitconfig` unchanged. Git reads both files; signing settings
in `.gitconfig` take precedence, so remove conflicting settings there to use the
restored key. Keep `.config/git/config` outside Chezmoi's managed source.

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

Setup checks pending changes with `chezmoi status`. If local changes conflict
with the source, it lists the affected paths and prompts before replacing them.
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
before applying dotfiles. The installation task pins the framework revision,
maintained by Renovate. This is an internal setup dependency, with no private
override setting. Setup updates the checkout to that revision and refuses to
overwrite tracked local edits. Put personal plugins and themes in its `custom/`
directory or manage them through Chezmoi.

Enable Oh My Zsh and select plugins in your Chezmoi-managed `.zshrc`. The framework
supplies aliases and completion; Starship can supply the prompt and mise can
manage runtimes alongside it. Setup also installs Déjà through mise; enable it
immediately after sourcing the managed `~/.config/workstation-manager/mise.sh`
helper in your Chezmoi-managed `.zshrc`. That helper runs `mise activate zsh`,
which puts `deja` on `PATH`. Run `deja import` once to seed it from your
existing shell history. Because mise upgrades move Déjà between versioned
install directories, keep the `eval "$(deja init zsh)"` line in your `.zshrc`
instead of caching its output so each shell refreshes the init script against
the current binary:

```zsh
source "$HOME/.config/workstation-manager/mise.sh"
eval "$(deja init zsh)"
```

Do not enable `zsh-autosuggestions` at the same time; Déjà replaces it. For a
pinned Oh My Zsh installation, add this before sourcing
`~/.oh-my-zsh/oh-my-zsh.sh`:

```zsh
zstyle ':omz:update' mode disabled
```

Setup then owns framework updates. Setup leaves `.zshrc` ownership to Chezmoi
and sets the target user's login shell to `/usr/bin/zsh`. Log out of your desktop
session and log back in after setup to use Zsh in new terminals. Existing
terminals keep their current shell.

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

When `development.editor_packages` includes `com.visualstudio.code`, setup
installs a `code` launcher on your terminal's `PATH`, preserving any existing
`/usr/local/bin/code`. Open a project or file with:

```sh
code .
code --wait path/to/file
```

Setup also selects `zsh (host)` as the Visual Studio Code integrated terminal's
default Linux profile. It uses the Flatpak package's
[host-spawn bridge](https://github.com/flathub/com.visualstudio.code#use-host-shell-in-the-integrated-terminal)
to run `/usr/bin/zsh` on the workstation, where your `.zshrc`, mise tools, and
project files are available. Setup preserves other editor settings, terminal
profiles, and comments in `settings.json`. Restart Visual Studio Code after setup
and open a new terminal; existing terminals keep their current shell. Workspace settings
can override the default; select `zsh (host)` through
**Terminal: Select Default Profile** in that case.

Setup adds `terminal.integrated.profiles.linux` and
`terminal.integrated.defaultProfile.linux` to
[`settingsSync.ignoredSettings`](https://code.visualstudio.com/docs/configure/settings-sync#configure-synced-data).
These Linux terminal settings stay local to the workstation so Settings Sync
cannot replace the Flatpak host bridge. Other sync exclusions are preserved;
explicit sync opt-ins for these two settings are removed.

If Settings Sync has already removed `zsh (host)`, rerun setup or open
**Preferences: Open User Settings (JSON)** and merge these entries into the
existing settings, keeping any other terminal profiles and sync exclusions:

```json
{
  "terminal.integrated.profiles.linux": {
    "zsh (host)": {
      "path": "/app/bin/host-spawn",
      "args": ["/usr/bin/zsh", "-l"],
      "overrideName": true
    }
  },
  "terminal.integrated.defaultProfile.linux": "zsh (host)",
  "settingsSync.ignoredSettings": [
    "terminal.integrated.profiles.linux",
    "terminal.integrated.defaultProfile.linux"
  ]
}
```

Open a new terminal after saving. Zsh is installed on the workstation; selecting
`/usr/bin/zsh` directly inside the Flatpak does not use the host installation.

Set workstation-wide tool versions in `development.mise.tools`. They are
written to `~/.config/mise/config.toml`; project-specific versions belong in each
project's `mise.toml`.

Setup always configures the local Docker daemon.
Mise installs the Docker client and runtime binaries through `aqua:docker/cli`,
with Compose and Buildx installed as Docker CLI plugins. Setup creates and starts
`workstation-manager-docker.service`, and adds the managed user to the `docker`
group. The daemon uses the containerd and runc binaries from the same mise
installation. Setup also grants the managed user direct socket access, so
existing terminals and IDE sessions can use Docker without `sudo` or a logout.
The service reapplies this permission whenever it starts. Check access after
setup with `docker info`.
Docker access grants root-level control of the workstation; see
[Docker's post-installation guide](https://docs.docker.com/engine/install/linux-postinstall/).

The [public defaults](../../ansible/group_vars/all.yml) provide the Compose and
Buildx plugin mappings. Setup links their mise-managed binaries automatically.

Rerun setup after changing the workstation's Docker version in
`development.mise.tools` or upgrading Docker through mise. Setup updates the
service's binary path and restarts the daemon when its service configuration
changes. Running containers can be interrupted by that restart.

Setup supports fresh installations without existing Docker service units. If
another installation provides `docker.service` or `docker.socket`, setup stops.
Reconcile that installation before continuing with the mise-managed daemon.
A dry run previews available configuration without starting or verifying the
daemon. If mise cannot resolve installed Docker binaries or plugins yet, their
configuration is deferred until a normal setup run.

The default backup includes `~/Documents/dev-projects`. Keep project files there
or include another location through the [backup options](backup-and-restore.md).
Changing `user.projects_directory` changes setup paths; backup still uses its
fixed default directory and any explicitly added paths.

Setup also installs `workstation-manager-git-project-report`. Run it manually to
print the Git repositories under `user.projects_directory` that still have local
work in progress. A user-level daily timer is installed alongside it, and the
desktop session activates that timer so the same summary appears as a
notification once per day.

Review the public defaults for package lists, GNOME preferences, and application
settings. Override only the values you need to change.

CopyQ starts hidden at graphical login by default. Setup also starts it in an
active GNOME session if it is not already running. When setup runs without a
graphical session, CopyQ starts at the next login. Set `desktop.gnome.autostart`
to `[]` in your private override to skip startup configuration and activation;
remove any previously installed startup entry in `~/.config/autostart/` yourself.

Setup configures the CopyQ Flatpak to use XWayland (`QT_QPA_PLATFORM=xcb`) for
clipboard monitoring on GNOME. The setting applies to graphical login and manual
launches. After setup changes this setting, quit CopyQ from its menu and reopen
it, or log out and back in. Closing its window leaves the existing process running.

If an existing installation does not record copied text, run this from your
desktop terminal, then quit and reopen CopyQ:

```sh
flatpak override --user --env=QT_QPA_PLATFORM=xcb com.github.hluk.copyq
```

Copy two different pieces of ordinary text while CopyQ's window is hidden, then
open it and check that both appear. GNOME's native CopyQ clipboard extension is
unavailable to the Flatpak build. The
[upstream XWayland workaround](https://copyq.readthedocs.io/en/latest/known-issues.html#workaround-running-under-xwayland)
depends on the compositor and may still miss clipboard changes on some systems.

## Automated runs

Provide credentials through your automation's secret store:

| Environment variable               | Purpose                                                                       |
| ---------------------------------- | ----------------------------------------------------------------------------- |
| `WORKSTATION_MANAGER_GITHUB_TOKEN` | Access private GitHub repositories and authenticate developer tool downloads. |
| `BITWARDEN_CLIENT_ID`              | Bitwarden API client ID.                                                      |
| `BITWARDEN_CLIENT_SECRET`          | Bitwarden API client secret.                                                  |
| `BITWARDEN_PASSWORD`               | Unlock the Bitwarden vault.                                                   |

Setup passes the GitHub token to mise and GitHub CLI extension commands through
their environment and uses it for the Orca release lookup, including previews.
The Orca request keeps the token out of logs and redirected requests. Setup does
not write it to application configuration or shell activation files.

All three Bitwarden values must be present to skip interactive credential prompts.
Automation must also supply `WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR` for backup.
Recovery checks that require a human decision stop noninteractive backup; browser
Sync completion requires interactive confirmation.

Do not put credential values in command examples, configuration files, or Git.
