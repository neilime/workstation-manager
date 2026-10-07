# ADR 0001 Workstation software and setup toolchain

- Status: Implemented baseline; interactive desktop qualification, performance measurements, and personal backup verification remain manual requirements.
- Decision drivers: performance, low friction, and current supported software.

Retain Ubuntu with GNOME, Ansible, Chezmoi, Bitwarden, Brave, and mise. Simplify
their integration: use native packages for host services and development editors,
Flatpak for independent desktop applications, and mise for user development tools.
Remove Snap completely during setup and prevent its automatic reinstallation.
Give every component and background job an explicit owner. Keep the required desktop applications in the baseline. Use Ubuntu's current Python, terminal, command-line
utilities, and Wayland session. Mise owns PHP through a maintained backend.

Support only the latest stable Ubuntu release, including interim releases and
current point updates. Keep one Ubuntu test baseline and advance it through
Renovate proposals whenever a newer stable release becomes available.

Node.js LTS, npm, npx, Codex, Copilot, and an authenticated GitHub CLI are a mandatory
workstation baseline. They must be available in ordinary terminals, Visual Studio Code
terminals and tasks, and Copilot/Codex sessions without manual shell activation,
PATH repair, or repeated GitHub login while the stored credentials remain valid.

Setup installs native Visual Studio Code, standard agent CLIs, pinned extensions,
Simple Scan/SANE, and Clipboard Indicator, and verifies persistent GitHub
authentication. Installation checks do not establish live desktop, IDE/agent,
reboot, or performance acceptance. Déjà Dup policy selection and an encrypted
backup/restore drill require the user's configuration and verification.

## Context and scope

The review covers software explicitly installed, invoked, or configured by
`workstation.sh setup`, including dependencies embedded in roles, shell startup,
desktop integration, and recovery. It also covers the tools used to validate setup.
It groups transitive operating-system libraries by purpose rather than attempting
an inventory of every package on an existing machine.

The implementation sources below define the current baseline. The companion
`workstation-config` repository owns personal shell, Git, clipboard, and agent
preferences. Private identifiers and credentials are outside this ADR's scope.
The workload is software development with containers and cloud tooling. Hardware,
daily application usage, and benchmark results are acceptance inputs.

| Implementation evidence                                                                                                                                                                            | What it establishes                                                          |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| [Entrypoint](../../../workstation.sh) and [setup orchestration](../../../ansible/tasks/setup_action.yml)                                                                                           | Bootstrap dependencies, authentication, and unconditional setup stages.      |
| [Public defaults](../../../ansible/group_vars/all.yml) and [normalizers](../../../ansible/collections/ansible_collections/neilime/workstation_setup/plugins/module_utils/desired_state_support.py) | Declared software and configuration defaults.                                |
| [Setup roles](../../../ansible/collections/ansible_collections/neilime/workstation_setup/roles)                                                                                                    | Actual install methods, implicit packages, services, and integrations.       |
| [Production collections](../../../ansible/collections/requirements.yml), [tooling image](../../../docker/tooling/Dockerfile), and [tooling requirements](../../../docker/tooling/requirements.txt) | Runtime and test dependency selection.                                       |
| [VM definition](../../../e2e-tests/lima-ubuntu.yml)                                                                                                                                                | Ubuntu 26.04, amd64, and a Wayland desktop test session.                     |
| [Cleanup implementation](../../../ansible/collections/ansible_collections/neilime/workstation_cleanup/roles/cleanup/tasks/main.yml)                                                                | APT upgrade simulation, bounded Docker cache pruning, and journal retention. |
| [Renovate configuration](../../../.github/renovate/renovate-config.json5) and [Dependabot configuration](../../../.github/dependabot.yml)                                                          | Existing dependency-update coverage.                                         |

## Decision drivers

| Driver           | Meaning for this workstation                                                                            | Decision rule                                                                          |
| ---------------- | ------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Performance      | Responsive terminal/editor, bounded background CPU/RAM/I/O, quick setup reruns, useful build caches.    | Measure the affected workload. Installed disk size alone is not runtime overhead.      |
| Low friction     | Working host tools from terminals and IDEs, predictable updates, few manual repairs, recoverable state. | Prefer supported integrations and one owner per executable or configuration file.      |
| Current software | Supported OS/language branches, prompt security fixes, maintained installers, reproducible upgrades.    | Use stable releases with an update policy. A moving `latest` selector is insufficient. |

Data preservation and recovery correctness constrain all three drivers. Do not
reduce prompts by guessing reconciliation decisions, replace working applications
solely for novelty, or erase useful caches to improve a package-count metric.
When drivers conflict, retain supported behavior and choose the lowest ongoing
maintenance cost; benchmark performance before accepting a disruptive replacement.

## Findings that drive the decision

### Bootstrap and CI share one tested runtime

[The controller manifest](../../../ansible/requirements.txt) pins Ansible Core
for bootstrap and the tooling image. The entrypoint validates the selected
Ubuntu release, installs the controller into `/opt/workstation-manager/venv`,
checks its dependencies, and invokes its executables explicitly. Host modules
use `/usr/bin/python3` and Ubuntu's APT/dconf bindings. An unrelated installed
Ansible command cannot bypass this resolution.

Bootstrap and the image consume the exact pins in the
[collection manifest](../../../ansible/collections/requirements.yml).
First-party metadata requires the tested controller line. The tooling image uses
the selected Ubuntu base and an isolated test environment. Makefile collection
tests derive their interpreter version from the image.

### Use the current Ubuntu desktop and system utilities

Ubuntu's current desktop uses GNOME on Wayland and Ptyxis as its terminal. The VM
uses Wayland and verifies its actual session type. Lima/QEMU uses a read-only 9p
workspace mount, compatible with current AppArmor confinement. Capture the virtual
display through QMP/VNC;
that display transport does not require an Xorg guest session. Preserve XWayland
for applications that need it.
[Ubuntu desktop changes](https://github.com/ubuntu/ubuntu-release-notes/blob/main/docs/26.04/summary-for-lts-users.md).

Ptyxis is the managed desktop terminal in setup, dock favorites, and the VM.
Setup preserves personal terminal profiles and shortcuts.
Keep Zsh/Bash, Oh My Zsh, and Starship decisions tied to shell behavior and measured
startup cost; changing the terminal does not require changing the shell. Keep
the public POSIX `sh` bootstrap contract.
[Ubuntu terminal selection](https://documentation.ubuntu.com/desktop/en/26.04/how-to/change-the-default-terminal/).

Use Ubuntu's default `sudo-rs` and Rust coreutils providers. Exercise the public
piped bootstrap, restricted environment forwarding, ownership/mode changes,
temporary files, and archive recovery against those actual implementations.
Tests exercise the system utilities supplied by Ubuntu. The VM
also verifies the graphical session and native service integrations.
[Ubuntu system utility changes](https://ubuntu.com/blog/ubuntu-26-04-lts-security-updates).

Use Ubuntu's packaged desktop integrations where available. In 26.04,
`gnome-shell-extension-appindicator` is a virtual package provided by
`gnome-shell-ubuntu-extensions`; manage the current provider and required enabled
extensions for application tray support.
[Ubuntu extension provider](https://packages.ubuntu.com/resolute/gnome-shell-extension-appindicator).

### Installation and update ownership

APT and Flatpak tasks generally request `state: present`. Native Docker, gh, and
other APT packages use APT updates; cleanup only simulates pending upgrades.
GNOME Software owns Flatpak updates,
with automatic downloads enabled. Mise and Chezmoi are checksum-verified
and converge to their reviewed versions. Orca is installed on every workstation
and follows its configured release pin, as do managed GitHub CLI extensions.
Bitwarden CLI installs when missing; global mise tools run `install` for the
configured versions. Installation does not guarantee every application is current.
[Flatpak module states](https://docs.ansible.com/projects/ansible/latest/collections/community/general/flatpak_module.html),
[mise upgrades](https://mise.jdx.dev/cli/upgrade.html).

Setup converges on reviewed configuration. Repository dependency workflows
propose pin updates; rerunning setup applies them. Native package updates and
their service restarts are separate operations from cleanup. GNOME Software has
automatic downloads enabled for the managed account.

### Native packages own host integration

Docker uses the vendor APT engine, CLI, containerd, Compose, and Buildx, with
`docker.service` and Docker group access. Setup verifies daemon access as the
managed user. Visual Studio Code uses Microsoft's stable APT package and native
Zsh integration, preserving unrelated editor settings and personal profiles.

Docker recommends distribution packages over manually managed static binaries
where available. Native packages provide host integration for containers, editor
terminals, sign-in, and Git editor/diff commands.
[Docker binary guidance](https://docs.docker.com/engine/install/binaries/),
[Docker Ubuntu packages](https://docs.docker.com/engine/install/ubuntu/),
[Visual Studio Code Linux installation](https://code.visualstudio.com/docs/setup/linux).

Docker's official repository supports the current 26.04 target. Recheck the exact
Ubuntu suite and architecture at every OS release; use a vendor's supported
distribution-independent repository where it provides one. Never substitute a
previous Ubuntu codename into a vendor repository to conceal missing support.
If a required vendor lags a new stable Ubuntu release, qualify the current
Ubuntu package or another maintained delivery method, and report any remaining
blocker. Keep the latest Ubuntu target. Podman and rootless Docker remain workload
decisions because Docker API, Compose, and socket integration requirements still
exist on a new OS.

Retain Flatpak for selected independent GUI applications. A newer Ubuntu release
does not make its application packages track every upstream release, or remove
sandbox/portal trade-offs. Keep one delivery per app. Prefer native APT for
hardware integration such as Simple Scan/SANE; verify Flatpak screen sharing,
notifications, file access, and vault integration where those apps remain selected.
GNOME Software and its Flatpak plugin own desktop application management and
updates. The Snap exclusion policy below applies during setup.
[Ubuntu scanner package](https://packages.ubuntu.com/resolute/simple-scan).

### Remove Snap completely during setup

Setup removes Snap after installing the selected applications. The removal module
archives and compares application data and saved snapshot files before purging
Snap packages, Ubuntu Snap launchers, and residual state. Native Firefox or
Thunderbird packages without a snapd dependency are preserved. An APT policy
prevents automatic reinstallation. Snap is excluded from application delivery.

Before removal, inventory installed snaps, their services, application data, and
saved snapshots. Create and verify a recovery archive outside all Snap directories
before deleting originals. Cover system data and the actual homes of affected
local users, including root; preserve ownership and protect credentials. Existing snapshots must be exported and verified when needed for
recovery; a snapshot inside snapd's own state directory is not sufficient.
[Snapshot verification and export](https://snapcraft.io/docs/how-to-guides/manage-snaps/create-data-snapshots/).

Remove all installed snaps in dependency order, including application, integration,
content, and base snaps, then the snapd snap. Purge the `snapd` Debian package and
Snap-specific software-center integration. Remove remaining Snap services,
sockets, mounts, launchers, caches, saved snapshots, and state under `/snap`,
`/var/snap`, `/var/lib/snapd`, and `/var/cache/snapd`. After verified preservation,
remove residual `snap` and `.snap` directories from affected homes. Preserve shared
system logs and unrelated files. `snap remove --purge` avoids creating a new
automatic snapshot but does not remove existing snapshots.
[Snap decommissioning](https://snapcraft.io/docs/explanation/security/decommissioning/).

Manage an APT policy that prevents automatic installation of `snapd`, and reject
package choices that require it. Check this policy after package and Ubuntu
upgrades. Setup must fail with an actionable error if removal or preservation
is incomplete; it must not report successful setup with Snap still present.

Require a conventional Ubuntu installation whose boot and encryption do not
depend on Snap. Ubuntu's TPM-backed full-disk-encryption installation can use
kernel snaps and require snapd for recovery. Detect that dependency before any
removal and stop with instructions to migrate to a supported installation; never
remove essential boot or encryption components. This is an installation-mode
constraint within the latest stable Ubuntu policy.
[Ubuntu installation dependency](https://snapcraft.io/docs/explanation/security/decommissioning/#hybrid-classic-systems).

### Node.js availability must not depend on an interactive shell

Setup installs the complete pinned Node.js LTS distribution under `/opt/nodejs`
and exposes `node`, `npm`, and `npx` through `/usr/local/bin`. The companion shell
files return before mise activation in non-interactive shells. Neither those startup
files nor the editor's host terminal establishes command availability for an IDE
task, extension process, or agent subprocess. Mise documents separate integration
for these contexts; an installed runtime alone is insufficient.
[mise IDE integration](https://mise.jdx.dev/ide-integration.html).

Provide a machine-wide installation of the current Node.js LTS with its bundled
npm and npx. Use verified official binaries, root-owned versioned storage, and
stable `node`, `npm`, and `npx` entrypoints in `/usr/local/bin`. Manage the complete
distribution together so npm/npx can find their runtime and supporting files.
Verify that all managed launch environments include that directory in PATH.
This baseline must work without sourcing `.bashrc`/`.zshrc`, running `mise activate`,
opening an interactive terminal first, or downloading a runtime on first use.
[Official Node.js distributions](https://nodejs.org/en/download).

The selected baseline is the reviewed Node LTS pin in
[public configuration](../../../ansible/group_vars/all.yml). Keep its exact version there and
review the next LTS transition explicitly. Maintain npm and npx as the compatible
bundled pair; do not install the deprecated standalone `npx` package or update npm
independently without compatibility checks.
[Node.js release status](https://nodejs.org/en/about/previous-releases),
[npm npx documentation](https://docs.npmjs.com/cli/v11/commands/npx/).

Mise supports explicit project runtime overrides; the system distribution owns
the workstation-wide Node.js default. A project
override must supply a coherent Node.js/npm/npx toolchain; prepare a missing
project runtime before executing its tools instead of silently using an incompatible
version. Outside an explicit override, every managed context uses the LTS baseline.

The availability requirement includes desktop-launched Visual Studio Code, its
integrated terminal, tasks/debug adapters, and commands spawned by Copilot or
Codex, including non-interactive subprocesses. If an application sandbox or
container cannot see host executables, provision the same baseline inside its
managed execution environment and configure its PATH explicitly. A working host
terminal or `host-spawn` terminal alone does not satisfy that requirement. Preserve
the application's sandbox protections. Restart existing application/session
processes when required to adopt a changed environment, and repeat the checks
after logout/login and reboot.

### GitHub CLI authentication must persist across execution contexts

Bootstrap repository access and the managed user's persistent GitHub login are
separate checks. A successful clone or a supplied
`WORKSTATION_MANAGER_GITHUB_TOKEN` does not by itself establish persistent
authentication. Setup verifies the configured account's keyring login and Git
credential integration independently of bootstrap access.

Install one host `gh` through the official APT repository and make it available
in every execution context covered by the Node.js requirement. Establish and
verify authentication for the resolved workstation user during setup, independently
of bootstrap repository access. Reuse an existing valid login; otherwise perform
one initial login for the selected GitHub host/account and configure the Git
credential helper. Setup must report incomplete authentication when unattended
execution cannot establish it.
[GitHub CLI installation](https://github.com/cli/cli/blob/trunk/docs/install_linux.md),
[Git credential integration](https://cli.github.com/manual/gh_auth_setup-git).

Use the user's OS credential store and one canonical CLI configuration. Ensure
native terminals, desktop-launched editors, tasks, and agent subprocesses can
access that user session and credential store. GitHub CLI can fall back to a
plaintext token file when its credential store is unavailable; detect that
condition and repair the credential-store integration. Keep credentials out of
dotfiles, shell startup files, images, and logs.
[GitHub CLI authentication](https://cli.github.com/manual/gh_auth_login).

Align `HOME`, `XDG_CONFIG_HOME`, and any `GH_CONFIG_DIR` override with the managed
user's configuration. Inspect token-variable presence without printing values:
`GH_TOKEN` and `GITHUB_TOKEN` override stored credentials and can shadow a valid
login. Diagnose stale inherited overrides while preserving intentionally scoped
project or automation credentials. For managed sandboxes or containers, provision
`gh` and a supported credential handoff, such as a token supplied only to the
authorized process from the user's secret provider. Sharing a configuration path
alone is insufficient when its credential store is inaccessible. Preserve sandbox
protections and verify the actual command-execution environment.
[GitHub CLI environment precedence](https://cli.github.com/manual/gh_help_environment).

Authentication must survive terminal/editor restarts, setup reruns, CLI upgrades,
and logout/login or reboot after the user session unlocks. Require the non-secret
`development.github.account` in configuration; credentials belong in the OS
keyring, with bootstrap tokens supplied privately. Validate the active
account, keyring storage, and Git credential helper during setup and acceptance
checks, without adding a network probe to every shell startup. Expired or revoked
credentials, a locked credential store, and unavailable network access need distinct
diagnostics and a single recovery path. Reauthentication may require
the user; it must restore access across managed contexts instead of requiring a
separate login in each terminal or agent. Copilot/Codex product sign-in remains
separate from the `gh` authentication used by their commands.

### PHP is a mandatory mise runtime

PHP is a user development runtime, with one managed installation path through
`vfox:jdx/vfox-php`. Setup always installs the configured PHP release and its
required Ubuntu build tools and headers. There is no optional PHP workload or
APT runtime selection. Project versions remain in project mise configuration.
The current [mise registry](https://github.com/jdx/mise/blob/main/registry/php.toml)
selects the active [PHP backend](https://github.com/jdx/vfox-php), which compiles
PHP from source. Check its maintenance status and Ubuntu compatibility when
updating the toolchain. Source builds take time on installation and upgrades.

[Public configuration](../../../ansible/group_vars/all.yml) owns the PHP and
Composer pins. Renovate follows stable `php-*` tags and Composer releases.
Composer is a mandatory `github:composer/composer` mise tool. The built-in
[GitHub backend](https://mise.jdx.dev/dev-tools/backends/github.html) downloads
`composer.phar`, verifies the release asset checksum, and exposes it as `composer`.
Setup verifies both commands through mise; the configured Composer takes precedence
over the PHP plugin's bundled copy.
Existing projects and unmanaged runtimes remain intact. Validate required
extensions, shell selection, Composer, and project compatibility in the VM.
[PHP support](https://www.php.net/supported-versions.php),
[Composer downloads and checksums](https://getcomposer.org/download/).

### GNOME Clipboard Indicator

**Clipboard Indicator** (`clipboard-indicator@tudmotu.com`) is the managed
clipboard extension. It provides the required text and image history, search,
pins, and quick paste through GNOME Shell. Direct desktop integration motivates
the choice; lower CPU/RAM use has not been measured.
[Upstream features and limitations](https://github.com/Tudmotu/gnome-shell-extension-clipboard-indicator).

The reviewed version and archive digest live in
[public configuration](../../../ansible/group_vars/all.yml). Setup validates
the archive identity, version, and compatibility with the detected GNOME major.
Qualification targets the GNOME version shipped by the supported Ubuntu release.
GNOME version validation stays enabled; requalify whenever that version changes.
[Published versions](https://extensions.gnome.org/extension/779/clipboard-indicator/),
[upstream metadata](https://github.com/Tudmotu/gnome-shell-extension-clipboard-indicator/blob/master/metadata.json).

The managed profile sets a 200-entry history limit, enables image
caching, search, visible pins, and paste-on-select, and uses one conflict-free
global shortcut. Keep history across sessions and preserve code whitespace. Map
these choices to the selected artifact's GSettings schema; keep preferences in
the companion configuration and installation/version ownership in the manager.
The cache-size setting bounds the history registry, not all image files; measure
actual disk use before defining a storage budget.
[Settings schema](https://github.com/Tudmotu/gnome-shell-extension-clipboard-indicator/blob/master/schemas/org.gnome.shell.extensions.clipboard-indicator.gschema.xml).

Install a reviewed extension archive for the detected GNOME major, recording its
version and digest. Check updates weekly and test before advancing. Avoid installing
from a moving Git branch. Run one clipboard manager at a time. Setup installs
and enables Clipboard Indicator, closes and removes conflicting CopyQ applications,
and preserves their data. It does not import that data into Clipboard Indicator.

Upstream warns that large images can briefly freeze the shell and direct paste
does not work in every application. Acceptance therefore requires typical and
large screenshots, a populated history, and quick paste into Brave, Visual Studio
Code, its terminal, and Ptyxis. A manual paste fallback is useful
for diagnosis but does not satisfy the requested quick-paste behavior in those
applications. Test capture while the menu is closed, search, pin retention,
logout/login, reboot, and lock/unlock on Wayland, including XWayland source apps.
Measure shell responsiveness and reject the candidate if normal clipboard use
introduces noticeable stalls. The Wayland VM can exercise software behavior; scanner hardware and interactive
application acceptance still require the actual devices and accounts.
[Upstream known issues](https://github.com/Tudmotu/gnome-shell-extension-clipboard-indicator#known-issues).

## Software disposition

These tables explain the current selections and their ownership. Exact releases
and package identifiers belong in public configuration and dependency manifests.

### Operating system and delivery tools

Setup uses one Ubuntu/Python/Ansible baseline, shared collection pins, native
Docker and gh, system Node LTS with npm/npx, and verified mise and Chezmoi releases.
GNOME Software owns Flatpak updates; Ptyxis is the managed terminal. Snap removal
requires verified data preservation and prevents automatic reinstallation.
The [configuration guide](../../usage/configuration.md#application-delivery) describes
the operational behavior and recovery locations. Installation qualification does
not establish performance improvements or complete the IDE/agent authentication
acceptance matrix in the remaining sections.

| Component and current delivery                                                      | Current choice                          | Reason and condition                                                                                                                                |
| ----------------------------------------------------------------------------------- | --------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ubuntu/GNOME                                                                        | Latest stable release only              | The supported baseline selects the release for bootstrap, tooling, and the VM. Renovate coordinates updates; qualify desktop and recovery behavior. |
| POSIX `sh`, Bash for declared scripts, `wget`, `sudo`, CA certificates, Git         | Keep                                    | Preserve piped bootstrap and terminal prompts. Offer an immutable reviewed revision alongside the moving default branch.                            |
| Ansible Core and first-party Python collections                                     | Isolated controller                     | One compatible resolution across bootstrap, CI, and VM, with recovery and idempotence checks.                                                       |
| `community.general`, `ansible.posix`                                                | Shared exact pins                       | The shared manifest owns package, dconf, Bitwarden, and sysctl integration dependencies.                                                            |
| System Python, `python3-debian`, `python3-psutil`                                   | Ubuntu runtime                          | Use Ubuntu's interpreter and bindings for host modules; isolate controller and test dependencies.                                                   |
| APT and deb822 vendor repositories                                                  | Keep                                    | Own OS dependencies, services, browser, and host-integrated apps. Use scoped keys and a defined vendor update policy.                               |
| Flatpak, Flathub, `gnome-software`, `gnome-software-plugin-flatpak`                 | Keep Flatpak with GNOME Software        | GNOME Software and its Flatpak plugin own application management and updates. Verify current Wayland portals.                                       |
| Snap apps, snapd, and desktop integration                                           | Remove completely during setup          | Verify data preservation, purge packages and residual state, and prevent reinstallation. Require Ubuntu boot/encryption independent of Snap.        |
| mise, aqua/GitHub backends                                                          | Project versions and selected user CLIs | Mise owns user tools and explicit project overrides. APT owns Docker and gh; the system distribution owns default Node.                             |
| Chezmoi                                                                             | Pinned release artifact                 | Preserve conflict handling and verify the architecture-specific release archive checksum.                                                           |
| `locales`, `tzdata`, `xdg-utils`                                                    | Keep                                    | Locale, timezone, browser selection, and desktop launch are functional dependencies.                                                                |
| GNOME Shell, Ubuntu Dock, Nautilus, Ptyxis                                          | Ubuntu desktop; Ptyxis terminal         | The VM and managed favorites use Ptyxis. Personal terminal profiles remain intact.                                                                  |
| `dconf-cli`, `gnome-shell-common`, AppIndicator extension                           | Ubuntu integration packages             | The Ubuntu extension provider supplies required application tray support.                                                                           |
| systemd, D-Bus, desktop keyring, OpenSSH client, coreutils/findutils, archive tools | Ubuntu providers                        | Validate privilege escalation, file operations, session/keyring access, and recovery against the supplied implementations.                          |
| Role-installed `unzip`, `gpg`, `acl`, `iptables`                                    | Keep by verified consumer               | Preserve archive/signing requirements. Native Docker packaging owns its service dependencies.                                                       |

The [supported Ubuntu baseline](../../../ansible/ubuntu-version) selects one
stable release, whether LTS or interim. Development images and prereleases are
excluded. Renovate proposes coordinated baseline updates; each requires runtime,
desktop, and recovery qualification. Ubuntu's support dates do not imply equal
security coverage for every Universe package or third-party repository; track
each maintenance source.

### Development and shell tools

Implemented selections and update ownership live in
[public configuration](../../../ansible/group_vars/all.yml). Setup uses native
Visual Studio Code with verified data preservation, pinned Orca, Helm, Dive,
gh-act, gh-stack, mandatory mise PHP, pinned Composer, standard Codex/Copilot
CLIs, and persistent keyring-backed GitHub authentication. Git report
notifications run daily. The companion shell keeps history, loads integrations
only for available commands, and retains `cat='batcat -pp'` when `batcat` is available.

The table describes the current software and its ownership. The
[configuration guide](../../usage/configuration.md#developer-tools-and-project-files)
describes current operation. Live desktop/IDE validation, authentication across
restarts, project PHP/chart compatibility, and shell/prompt measurements remain
acceptance work; unit checks do not establish those results.

| Component and current delivery                               | Current choice                                        | Reason and condition                                                                                                                                                                                 |
| ------------------------------------------------------------ | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Visual Studio Code through official APT                      | Keep native application                               | Share host runtimes, Git, containers, terminals, and agent tooling.                                                                                                                                  |
| Orca, pinned GitHub `.deb`                                   | Required agent-workflow app                           | Orchestrates agents/worktrees. Always install the reviewed release; preserve settings/workspaces and keep Renovate coverage. [Upstream](https://github.com/stablyai/orca).                           |
| Codex/Copilot CLIs, preferences, and shared skills           | Mandatory workstation tools                           | Setup always installs the pinned npm releases and verifies both commands without shell activation. Companion dotfiles own preferences and shared guidance; product sign-in remains a first-use step. |
| Docker Engine/CLI and containerd through official APT        | Official APT packages                                 | System-owned executables and service integration; Docker group access grants root-level control.                                                                                                     |
| Compose and Buildx through Docker APT plugins                | Keep; use Docker APT plugins                          | One engine/client/plugin owner; verify package-managed commands.                                                                                                                                     |
| Node.js LTS system distribution; npm/npx bundled             | Mandatory machine-wide baseline                       | Stable host executables with IDE/agent environment coverage; mise supports explicit project overrides.                                                                                               |
| PHP and pinned Composer                                      | Mandatory user runtime through mise                   | Use the maintained PHP backend and required build dependencies. Keep PHP and Composer pins in public configuration with Renovate coverage.                                                           |
| Git and GitHub CLI                                           | Mandatory authenticated baseline; vendor APT for `gh` | Persist the managed user's authentication across terminals, IDEs, and agents, and verify Git credential integration.                                                                                 |
| `nektos/gh-act`                                              | Keep for CI debugging                                 | Its runner images/behavior do not replace hosted CI. Update the extension and budget its images separately. [Upstream](https://github.com/nektos/act).                                               |
| `github/gh-stack`                                            | Keep stacked-PR workflow                              | Pin the published binary release in public configuration and maintain it with Renovate. [Upstream](https://github.com/github/gh-stack).                                                              |
| Helm through mise                                            | Pinned release                                        | Validate chart/plugin compatibility and Kubernetes version skew. Helm does not install kubectl, a cluster, or credentials.                                                                           |
| Dive through mise                                            | Keep for image troubleshooting                        | Install the pinned mise tool for image-layer inspection. [Upstream](https://github.com/wagoodman/dive).                                                                                              |
| Zsh login shell, Bash fallback                               | Keep; use through Ptyxis and native IDE               | Shell preferences are independent of the Ubuntu support range. Preserve history and ensure non-interactive tools work without shell activation.                                                      |
| Oh My Zsh at a commit pin                                    | Managed shell framework                               | Setup owns the revision and updates; Chezmoi owns shell preferences. Measure startup and completion cost.                                                                                            |
| Oh My Zsh Git, command-not-found, Docker, Compose plugins    | Keep useful integrations                              | Measure completion/startup cost. Load Docker integrations when the command is available.                                                                                                             |
| Conditional Yarn, Composer, AWS, pre-commit, thefuck plugins | Explicit tool prerequisites                           | Shell hooks do not install these commands. Verify actual use before removing a conditional integration.                                                                                              |
| Starship through mise                                        | Managed shell prompt                                  | Oh My Zsh's theme is disabled. Measure prompt latency in representative repositories.                                                                                                                |
| `make`, `jq`, `bat`, `htop`, `fonts-firacode`                | Keep                                                  | Useful developer conveniences. Keep `bat` explicit and retain the preferred `cat='batcat -pp'` alias.                                                                                                |
| `libnotify-bin`                                              | Keep for daily report notifications                   | Required for the daily Git project report notifications.                                                                                                                                             |
| PHP build toolchain and required libraries                   | Required by the managed PHP backend                   | Install the build tools and headers listed in public defaults. Additional project-specific headers remain project requirements.                                                                      |
| `fs.inotify.max_user_watches=524288`                         | Keep configurable                                     | A ceiling, not an allocation request. Exclude generated trees from editor watching before raising it further.                                                                                        |

Do not add another runtime manager alongside mise. Provision missing commands
such as kubectl through the appropriate tool configuration when required,
with a version and verification step. Shell plugins are not dependency declarations.

### Desktop applications and recovery

Setup installs the required Flatpak applications and native Simple Scan/SANE.
Maintenance follows the policy below.
Clipboard Indicator is installed and enabled by default. Its version and SHA-256 live in public
configuration, with weekly Renovate proposals and manual digest/desktop review.
Déjà Dup destination, schedule, and retention require user configuration;
setup preserves existing backup settings.
Installing the app does not establish encrypted backup or restore coverage.

| Component and current delivery                                 | Current choice                               | Reason and condition                                                                                                                                                                                                 |
| -------------------------------------------------------------- | -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Brave via vendor APT, native profiles/Sync                     | Primary browser                              | The browser adapter owns setup, backup, and inspection, including verified Sync recovery.                                                                                                                            |
| Custom Brave Sync automation                                   | Keep guarantees; reduce unnecessary work     | Internal-page/UI coupling requires integration tests. Reuse verified session state where possible; never assume recovery succeeded.                                                                                  |
| Tor Browser Launcher, `org.torproject.torbrowser-launcher`     | Required privacy workflow                    | Distinct from the daily browser. Verify launcher delivery and the browser's own update path.                                                                                                                         |
| Slack, `com.slack.Slack`                                       | Required work app                            | Keep the Flatpak application and verify calls, notifications, and screen sharing.                                                                                                                                    |
| Bruno, `com.usebruno.Bruno`                                    | Required API development                     | Retain file-based collections; check certificates, filesystem access, and local endpoints. [Upstream](https://github.com/usebruno/bruno).                                                                            |
| Spotify, `com.spotify.Client`                                  | Required personal app                        | Keep the Flatpak application; avoid automatic startup.                                                                                                                                                               |
| VLC, `org.videolan.VLC`                                        | Required media app                           | Keep the Flatpak application for media playback.                                                                                                                                                                     |
| JDownloader, `org.jdownloader.JDownloader`                     | Required download workflow                   | Keep the Flatpak application and account for its runtime and own updater.                                                                                                                                            |
| Clipboard Indicator, `clipboard-indicator@tudmotu.com`         | Required GNOME clipboard extension           | Text/image history, search, pins, and quick paste. Validate GNOME compatibility and responsiveness with large images.                                                                                                |
| Simple Scan/SANE through Ubuntu APT                            | Required native scanner application          | Keep one installation and test actual scanner access.                                                                                                                                                                |
| Déjà Dup, `org.gnome.DejaDup`                                  | Keep with a configured, tested backup policy | Installing it does not configure backups. Complement manager archives with routine personal-file backup; define destination, encryption, retention, and a restore drill. [Purpose](https://apps.gnome.org/DejaDup/). |
| LibreOffice, `org.libreoffice.LibreOffice`                     | Required office app                          | Keep for offline work or document fidelity; no additional office suite is justified.                                                                                                                                 |
| Bitwarden desktop, `com.bitwarden.desktop`                     | Keep for daily vault use                     | Complements the CLI. Check unlock, browser integration if used, and keyring behavior after OS/packaging changes.                                                                                                     |
| Bitwarden CLI, downloaded ZIP                                  | Keep verified standalone CLI                 | Version, checksum, architecture, and vault checks remain required. A system Node installation alone is no reason to introduce npm runtime coupling.                                                                  |
| SSH restoration, GPG signing, Visual Studio Code Settings Sync | Keep identity/recovery behavior              | Preserve signing requirements. Sync needs sign-in; restored settings alone do not prove readiness.                                                                                                                   |
| Manager archive restore and managed-state checks               | Keep                                         | Preserve traversal/link validation and explicit skipped coverage. Reconstruction archives do not replace scheduled backup of all personal data.                                                                      |
| BleachBit and weekly preset timer                              | Keep weekly scheduling and manual command    | Run saved cleaner presets weekly, catch up missed runs, and preserve preferences. An empty preset performs no cleanup.                                                                                               |
| Daily Git project report/notification                          | Keep daily notifications                     | Enable daily notifications and retain the manual command for on-demand reports.                                                                                                                                      |
| Docker pruning, APT cleanup, journal vacuum                    | Fixed conservative maintenance               | Preserve volumes, containers, networks, and tagged images. Reclaim old dangling images/build cache and archived logs with fixed retention limits; keep package removal and upgrades outside cleanup.                 |

Give Chezmoi ownership of personal dotfiles and wallpaper, and Ansible ownership of
system configuration and generated machine data. Chezmoi owns the wallpaper and
Clipboard Indicator profile. Ansible
selects the existing wallpaper and applies the companion clipboard preferences;
it does not overwrite those source files. Preserve the separate Git signing configuration owned by key restore.

Cleanup prints drift findings, an APT upgrade simulation, and the reboot marker
in the terminal without writing a report file. It performs maintenance without
installing updates or restarting services. It prunes only old dangling Docker
images and build cache older than seven days, with a 10 GB retained-cache budget.
It preserves all Docker volumes and never runs APT autoremove. Journal vacuum
uses 14-day and 1024 MB limits; BleachBit runs saved presets weekly and remains
available for manual invocation. These are fixed behaviors, with no configuration
switches. See
[cleanup behavior](../../usage/cleanup.md).
[Docker pruning scope](https://docs.docker.com/reference/cli/docker/system/prune/).

### Tools used to build and validate setup

| Component                                                | Current choice                     | Reason and condition                                                                                                                                      |
| -------------------------------------------------------- | ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Make and Docker tooling image                            | Keep; use the selected Ubuntu base | Test the OS interpreter and utility implementations actually deployed. Keep an isolated test venv; measure image size/build time and reuse cached builds. |
| Ubuntu Python test runtime                               | Selected Ubuntu interpreter        | Keep Makefile, image, collection metadata, requirements, and CI aligned with the supported release.                                                       |
| pytest, pytest-xdist, ansible-test sanity/units          | Keep                               | Focused behavioral checks and bounded parallelism; not substitutes for desktop/restore tests.                                                             |
| pytest-testinfra                                         | Keep for VM assertions             | Tests the configured machine from outside its setup implementation; retain fixture isolation and teardown.                                                |
| Super-Linter, Ruff, Biome, shell/Ansible/Markdown checks | Keep checks; profile the wrapper   | Linter startup affects contributors, not workstation idle performance. Narrow local checks should preserve full CI coverage.                              |
| Lima, QEMU, Ubuntu desktop VM                            | Wayland desktop qualification      | Assert the session type and Ptyxis availability, with VM display capture for diagnostics.                                                                 |
| Renovate and Dependabot                                  | Keep with explicit ownership       | Renovate owns Ubuntu release selectors in VM/tooling together. Dependabot keeps other images, Actions, and Python; exclude duplicate Ubuntu ownership.    |

## Update ownership and target policy

| Software class                                 | Owner and update mechanism                            | Reproducibility and recovery                                                                                                                          |
| ---------------------------------------------- | ----------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ubuntu security packages                       | Ubuntu package updates                                | Review available updates and reboot requirements. Cleanup reports the transaction without applying upgrades.                                          |
| Tested Ubuntu release in Lima                  | Renovate weekly workflow                              | Coordinate bootstrap, VM, and tooling selectors, align Python, and qualify desktop behavior before merging.                                           |
| Vendor APT apps and Docker                     | APT package updates                                   | Coordinate service restarts and test recovery; cleanup does not upgrade packages.                                                                     |
| Flatpak apps/runtimes                          | GNOME Software; automatic downloads enabled           | Surface unsupported runtimes. Verify important workflows; retain app data. [Update mechanism](https://docs.flatpak.org/en/latest/using-flatpak.html). |
| Ansible, collections, Chezmoi, mise, Orca      | Repository pins and dependency proposals              | Validate artifacts and compatibility before applying reviewed versions through setup.                                                                 |
| Machine-wide Node.js LTS with npm/npx          | One managed release manifest; weekly reviewed patches | Update the verified distribution together; explicitly review LTS major transitions. Preserve command paths and test every managed execution context.  |
| GitHub CLI and authentication                  | Vendor APT updates; setup owns session integration    | Preserve the managed user's login across upgrades. Verify account/access and recover invalid credentials without per-terminal sign-in.                |
| Clipboard Indicator                            | Manager pins reviewed archive; weekly update review   | Match the GNOME major, record the artifact digest, test images/paste, and preserve history before extension upgrades.                                 |
| Global mise tools and GitHub extensions        | One version manifest; weekly reviewed updates         | Pin or lock compatible resolutions. Setup installs that state; automation proposes the next. Preserve project overrides.                              |
| Project runtimes/package managers/dependencies | Each project's manifests and lockfiles                | Match project/CI requirements. Workstation maintenance must not rewrite project versions.                                                             |

Repository workflows propose dependency updates; setup applies reviewed pins.
APT and GNOME Software own their respective package updates. Failed updates must
remain visible. Test restoration as well as version rollback: application data
formats may not support downgrades. See the canonical
[dependency update guide](../README.md#dependency-updates) for handler ownership.

### Renovate owns proposals for the tested Ubuntu release

Renovate's custom datasource reads Canonical's stable `meta-release` feed,
normalizes point releases to their Ubuntu series, and excludes prerelease labels.
The custom manager extracts `ansible/ubuntu-version`, the tooling Docker base,
and both release occurrences in the Lima cloud-image URL. One non-automerge PR
advances that baseline, including stable interim releases. Released cloud images
and Ubuntu APT updates supply current point/security updates within the series.
[Renovate custom managers](https://docs.renovatebot.com/modules/manager/regex/),
[custom datasources](https://docs.renovatebot.com/modules/datasource/custom/),
[Canonical release feed](https://changelogs.ubuntu.com/meta-release).

Dependabot excludes the Ubuntu Docker reference and retains other images,
Actions, and Python dependencies. The image build asserts agreement with the
bootstrap baseline, and VM setup checks its OS release. Qualify the selected
Ubuntu/Python/Ansible combination before merging; a hosted runner's
`ubuntu-latest` label does not establish the workstation release. OS upgrades on
the user's installed workstation remain separate from repository update proposals.

Node's official release index supplies only LTS versions to its custom datasource.
Mise and Chezmoi use upstream releases. Their configuration and factory defaults
advance together. Validation checks extraction at the configured paths and uses
synthetic release data to distinguish stable releases from prereleases.

## Consequences

Native Docker and Visual Studio Code share host tools with terminals, IDEs, and
background processes. Flatpak applications retain sandbox and portal constraints;
mise stays focused on user tooling and project runtimes. CPU/RAM improvements are
not assumed.

Native applications have broad host access, and Docker group membership grants
root-level control. PHP source builds require compiler dependencies and build
time. Release pins need timely updates, and Clipboard Indicator couples clipboard
availability to GNOME extension compatibility.

Snap exclusion requires verified data preservation. Snap-only applications and
Ubuntu installation modes that require Snap are outside the supported setup.
The single Ubuntu baseline requires qualifying Python, GNOME, vendor repositories,
and extensions at each release.

## Validation requirements

Validate clean installation, unchanged reruns, previews, and recovery through the
supported backup/restore workflow while preserving user data. The following are
acceptance requirements, not claims that interactive or performance checks have
passed:

- Verify that tooling and the VM use the selected Ubuntu release and matching
  Python major/minor. Run bootstrap, privilege escalation, archive validation,
  restore, and cleanup with Ubuntu's real utility providers. Assert a Wayland
  desktop session; successful boot or a QEMU screenshot alone is insufficient.
- Validate native vendor packages against the actual release and architecture,
  including the next stable interim release. Record blockers without selecting
  an older Ubuntu suite. Check the installed GNOME extension provider, Ptyxis
  launcher, screen sharing, notifications, and keyring behavior after setup.
- Exercise Snap removal in the VM with preinstalled snaps, saved snapshots, and
  representative user data. Verify replacements and recovery before deletion,
  absence of packages/services/mounts/residual state, and prevention of automatic
  reinstallation during package upgrades. An unchanged rerun must be idempotent;
  `--dry-run` must not remove snaps or data. Simulate preservation/removal failures
  and Snap-dependent boot/encryption detection; each must fail before unsafe
  deletion rather than silently leave an incomplete workstation.
- Measure 30 warm terminal launches, including a representative large repository:
  target p95 ready-to-prompt below 250 ms and ordinary prompt redraw below 100 ms.
  Report cold launches separately; use a prompt-ready signal, not only shell exit.
- Measure editor time to an editable project, build/test time, and idle CPU/RAM
  over a fixed ten-minute session with the same apps open. Investigate regressions
  above 10%; do not claim gains within measurement noise.
- Time fresh setup and unchanged reruns separately, recording downloads,
  compilation, and human wait time. An unchanged rerun should rebuild no runtime
  and require no repeated sign-in when cached authentication remains valid.
- Require `node --version`, `npm --version`, and `npx --version` to succeed in
  login and non-login Bash/Zsh, non-interactive `sh -c`, and direct process launches
  with a clean standard PATH. Test from the home directory, a non-project directory,
  and a prepared project override. No manual activation or first-use download.
- Repeat those checks in desktop-launched Visual Studio Code terminals, tasks,
  and actual Copilot/Codex command-execution environments, including sandboxed
  execution where configured. Test npm script execution and npx with a preinstalled
  local fixture package while network access is disabled; version output alone
  does not establish usable package execution.
- Recheck Node.js/npm/npx after fresh setup, rerun, an LTS patch update, logout/login,
  and reboot. Verify that project overrides remain coherent and the default LTS
  remains available elsewhere; stale links or command-not-found errors fail setup
  acceptance.
- Require `gh --version` and `gh auth status --active --hostname github.com` to
  succeed in the same shell, desktop IDE, and Copilot/Codex contexts. Substitute
  the configured host when different. Check the expected account and stored keyring
  login with token overrides removed. Avoid `--show-token` and do not treat `--json`'s zero
  exit status as proof of valid authentication.
  [GitHub CLI status behavior](https://cli.github.com/manual/gh_auth_status).
- Repeat GitHub authentication checks after setup/rerun, CLI upgrades, application
  restarts, logout/login, and reboot without repeating login while credentials
  remain valid. Use isolated fixtures to exercise invalid token overrides,
  inaccessible credential stores, missing permissions, and network failures.
  Verify actionable recovery and credential redaction without revoking real
  workstation credentials or opening interactive prompts inside agent commands.
- Verify `code`, `git`, `gh`, `docker`, Compose/Buildx, and selected runtimes from
  both a desktop-launched IDE and a terminal. Only required first-run sign-in,
  privilege, conflict, and recovery decisions should interrupt setup.
- Run the Clipboard Indicator acceptance checks above on the real Wayland desktop.
  Verify all five required features and history recovery with a populated 200-item
  history. Missing capture, broken quick paste in required apps, lost pins, or
  shell stalls fail desktop acceptance; X11-only verification is insufficient.
- Produce a version/update report with an owner for every managed tool. Allow no
  unsupported selected component without a concrete blocker and dated follow-up.
  Exercise a backup restore before calling recovery complete.

Run lint, Ansible checks, focused regression tests, and relevant Lima assertions
for implementation changes. Ensure the VM's repository/ref contain the candidate
changes. Hardware performance and Wayland need their own measurements; container
or X11 tests are insufficient.

Requalify at each supported Ubuntu release, when a delivery method or runtime
changes, or when a workload changes the integration requirements.
