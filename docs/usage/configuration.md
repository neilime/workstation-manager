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
    context7-api-key: "<your-context7-item-uuid>"
```

Set your GitHub username and replace the item and collection placeholders with
your Bitwarden UUIDs. Commit and push the file, then run `setup` using the
[Readme command](../../README.md#set-up-or-update-the-workstation).
Setup, backup, and cleanup fetch that published override.
Nested mappings are merged with the defaults; lists replace the
corresponding default list. See [AI tools](ai-tools.md) for AI application
and extension configuration.

The GitHub account is required: missing or blank `development.github.account`
stops configuration validation before Ansible applies workstation roles. The
username is not a secret; it identifies the account whose persistent login setup
must verify.

Keep passwords, tokens, private keys, and browser recovery words in Bitwarden. Only
non-secret settings, item selectors, and collection identifiers belong in Git.

`secrets.bitwarden.context7-api-key` is required, including for dry runs. Missing,
blank, or invalid UUIDs stop configuration validation. Store the Context7 API key
in its item's password field; see [MCP configuration](ai-tools.md#mcp-servers).

GitHub authentication runs before downloading private configuration. Bootstrap
installs or updates GitHub CLI from its official APT repository and reuses a valid login
saved in your desktop keyring. If sign-in is needed, it starts
[`gh auth login --web`](https://cli.github.com/manual/gh_auth_login); approve access
in your browser. Keep your desktop keyring unlocked so the login can be saved.
Git then uses this login to download the latest `main` revision of
`workstation-config` into a fresh temporary checkout for each run. An explicitly
supplied `WORKSTATION_MANAGER_PRIVATE_OVERRIDE_FILE` is used as provided.

After downloading configuration, the entrypoint reuses an already-unlocked
Bitwarden CLI session when one is available (for example after you run `bw unlock`
and export `BW_SESSION`); otherwise it asks for your Bitwarden email and password.
Bitwarden uses the configured server to retrieve keys and application
secrets. Setup verifies that the GitHub login matches `development.github.account`
after loading configuration and reuses it throughout installation. GitHub
bootstrap authentication also runs when needed during `--dry-run`.

Password and emailed verification-code input are hidden. If Bitwarden rejects
the email, code, or password, the entrypoint asks again. Press Ctrl-C to cancel.

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
automatic downloads enabled for the managed account. Setup retries failed Flatpak
remote configuration and application installation up to three times, waiting ten
seconds between attempts. Persistent failures stop setup; rerunning setup resumes
installation of missing applications. Setup installs Ptyxis and
includes it in the default dock favorites while preserving existing terminal profiles.

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
`~/.local/share/chezmoi`. Use a full HTTPS or SSH Git URL. Every normal setup
fetches the checkout's tracking branch and fast-forwards to its latest published
revision before inspecting and applying dotfiles. When the source has local edits,
interactive setup offers three actions:

- `stash`: save tracked and untracked source edits in a Git stash, then update and
  apply the published dotfiles. The stash remains available; setup prints its
  recovery command and does not reapply it automatically. Ignored files stay in
  place. Recovery can require resolving conflicts with published changes.
- `skip`: preserve source edits and continue setup without updating the source or
  applying Chezmoi dotfiles or scripts for this run.
- `abort` (also an empty answer): stop setup so you can review, commit and publish,
  or move source edits aside manually.

A run without an interactive terminal stops with a command to inspect the source.
Unpublished commits, rewritten upstream history, unfinished Git operations, or
failed fetches still stop setup before dotfile application. Reconcile the checkout
manually, then rerun setup. An existing checkout keeps its remote and tracking branch;
changing the source setting does not switch its remote. Setup uses the managed source,
configured `home_environment.chezmoi.config_path`, and target home explicitly,
including when your terminal or IDE sets a different `XDG_DATA_HOME`. Existing
baseline directory permissions are preserved, including private `.config`
permissions applied by your dotfiles.
The generated Chezmoi config uses permission mask `022`, keeping ordinary files
at `0644` regardless of the calling shell's mask. Private source attributes retain
their restricted permissions.

Every normal setup checks pending changes with `chezmoi status` and applies them.
Dry runs do not fetch, update the source checkout, or apply dotfiles. If local
changes conflict with the source, setup lists the affected paths and prompts
before replacing them.
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
`bat` invokes it directly and `cat` invokes `batcat -pp`.
Setup preserves existing shell history.

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

For Orca, Codex/Copilot CLIs, shared MCP servers, credentials and skills, see
[AI tool configuration](ai-tools.md).

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
JSONC settings and personal profiles. When run on the desktop, setup turns on
Settings Sync, opens Visual Studio Code, and pauses for a one-time interactive
sign-in (reusing an existing GitHub account from Copilot without re-entering
credentials); it then continues automatically once sign-in completes. This
sign-in cannot be automated. If it is skipped or times out, setup prints the
manual sign-in steps. Project settings may override the selected terminal.
Settings Sync uses the native configuration directory.

Public [development defaults](../../ansible/group_vars/all.yml) own software
selection and release pins. AI applications and extensions are configured together
in `development.ai_tools`; see [AI applications](ai-tools.md#applications).

Setup installs Skillshare globally and applies each `.skillshare/config.yaml`
under `user.projects_directory` after archive restoration and GitHub login.
See [project skills](../development/project-skills.md) for the small
per-project config and update commands.

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

`development.node.version` pins the complete system Node.js LTS distribution,
including npm and npx, exposed through `/usr/local/bin`. Project-local mise
versions may override it inside a project. Update native vendor packages through
APT; cleanup only previews pending upgrades. Rerun setup after merging release
pin updates.

Setup requires a persistent GitHub CLI login matching `development.github.account`.
It verifies the login again after applying dotfiles and ensures Git uses the saved
credentials. An unavailable keyring, failed authentication, or unexpected account
stops setup. See the [initial sign-in sequence](#edit-your-private-override)
above. This verification does not log in or change credentials during a dry run.

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

For `development.github.host: github.com`, setup also logs Docker into `ghcr.io`
with the configured GitHub account. It reuses the GitHub CLI token and requests
`write:packages` through browser authorization when that permission is missing.
The authorization code and prompts appear in your terminal. Browser diagnostic
output is suppressed; GitHub CLI still reports a browser launch failure and the
URL to open manually.
This supports pulling and pushing images allowed by your account's package and
organization permissions; organization SSO authorization may also be required.

The token is passed to Docker through standard input and stored by Docker's
Secret Service helper in the desktop keyring. Setup preserves unrelated Docker
settings, verifies login before replacing inline GHCR credentials, and refreshes
Docker's saved credential when the GitHub token changes. Rerun setup after
changing GitHub accounts or credentials. Dry runs inspect configuration and saved
credentials without authorizing permissions or logging into the registry.

Unattended setup requires a saved login with `write:packages` already granted,
or a separate `WORKSTATION_MANAGER_GHCR_TOKEN` with pull/push permission. A separate
registry token leaves the GitHub CLI login intact; see
[automation credentials](../development/automation.md#automated-runs).
To grant it interactively as the managed user, run
`gh auth refresh --hostname github.com --scopes write:packages`, then rerun setup.
Keep the desktop keyring unlocked. Setup does not publish or delete any images.

Setup creates `user.projects_directory` (`~/Documents/dev-projects` by default)
and adds it to the Files sidebar bookmarks. Existing bookmarks and custom labels
are preserved.

The default backup includes `~/Documents/dev-projects`. Keep project files there
or include another location through the [backup options](backup-and-restore.md).
Changing `user.projects_directory` changes setup paths; backup still uses its
fixed default directory and any explicitly added paths.

Setup also installs `workstation-manager-git-project-report`. Run it manually to
print the Git repositories under `user.projects_directory` that still have local
work in progress. Setup always enables daily desktop notifications. Click the
notification or **Open full report** to open the latest complete report in your
default text viewer, even after the scheduled job has finished. Run
`workstation-manager-git-project-report --notify` to refresh it on demand.
The report is saved privately in
`~/.local/state/workstation-manager/git-project-report/latest.txt`, or under
`$XDG_STATE_HOME` when set.
The timer starts in the active user session, or at the next graphical login when
no session is available.

Setup always enables dark mode and shows Trash in Ubuntu Dock. The
[public defaults](../../ansible/group_vars/all.yml) select Brave and define the
ordered dock favorites, including Orca (`orca-ide.desktop`). Set
`desktop.gnome.favorites: null` to preserve existing
favorites or `favorites: []` to clear the dock.
Use `browser` in the favorites list for the selected browser adapter's desktop entry.
Log out and back in after the first setup: the running GNOME session predates the
Flatpak installation, so Flatpak favorites such as Bitwarden, Slack, and Spotify
only appear in the dock once a fresh login searches their launcher directory.

Manage the wallpaper through Chezmoi at
`~/.local/share/backgrounds/wallpaper.jpg`. Setup selects that image for both light
and dark modes with zoom scaling when it exists; it preserves the current
wallpaper settings when the file is absent.

### Clipboard and personal-file backup

Setup installs and enables Clipboard Indicator as the managed clipboard history
extension. Inherit its version and checksum pins from public configuration.
The companion repository owns `~/.config/clipboard-indicator/settings.ini`.

Setup verifies the archive digest, identity, and detected GNOME version before
installation and compiles missing settings schemas. It preserves unrelated
extensions and keeps GNOME compatibility validation enabled. Log out and back in
after installation or an update.
The companion profile retains 200 entries, images, search, pins, whitespace, and
`Super+Shift+V` as its only global shortcut. Select a history entry to make it the
current clipboard value, then paste in the destination app. The profile disables
automatic paste and the separate paste button so selecting history keeps that
value current for subsequent pastes.

Setup maps `Ctrl+V`, `Ctrl+Shift+V`, and `Shift+Insert` to regular clipboard paste
in Ptyxis. It adds `Ctrl+V` and `Shift+Insert` overrides for the native Visual Studio Code
terminal; its existing `Ctrl+Shift+V` and Paste menu use the same clipboard.
The terminal `Ctrl+V` binding takes precedence over the shell's literal-next-key
function. Copy explicitly with `Ctrl+C` in desktop apps or `Ctrl+Shift+C` in a
terminal. Highlighting text alone does not replace the copied value.

These bindings cover the managed terminals. Other terminal emulators, editor
profiles, and applications with custom shortcuts need their own regular-clipboard
paste bindings. Linux's primary selection still exists; middle-click or a
separate Paste Selection action can use it. Check clipboard consistency during the
[Wayland acceptance checks](../development/adr/adr-0001-workstation-toolchain.md#gnome-clipboard-indicator).

Setup preserves existing `~/.config` permissions, including Chezmoi's private mode.

### Desktop system monitor

Setup installs and enables the [Vitals](https://github.com/corecoding/Vitals)
GNOME top-bar system monitor, showing live CPU, memory, temperature, network, and
storage. Inherit its version and checksum pins from public configuration
(`desktop.system_monitor`).

Setup verifies the archive digest, identity, and detected GNOME version before
installation, compiles missing settings schemas, preserves unrelated extensions,
and keeps GNOME compatibility validation enabled. When the companion repository provides
`~/.config/vitals/settings.ini` (a `[vitals]` section), setup applies those
preferences through `dconf`; otherwise the indicator uses upstream defaults. Log
out and back in after installation or an update. See
[ADR 0003](../development/adr/adr-0003-desktop-system-monitor.md).

Simple Scan uses Ubuntu's native `simple-scan` and `sane-utils` packages. Setup
removes duplicate system and user Flatpak installations without deleting their
data. Use `scanimage -L` and Simple Scan with the actual scanner to confirm device
access; a package check cannot establish hardware compatibility.

Setup installs Déjà Dup. Configure its destination, included folders,
encryption, schedule, and retention before relying on routine personal-file
backups. Keep the backup password in Bitwarden and complete a restore to a
separate directory, comparing the restored files with their originals.
Manager archives and application installation do not prove this coverage.
