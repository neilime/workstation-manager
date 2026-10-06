# neilime.workstation_setup

Owns configuration normalization, system and application setup, secrets retrieval,
home-environment setup (including the Zsh login shell, Oh My Zsh, and Chezmoi),
developer tooling, and browser adapters. GNOME setup bookmarks the configured
projects directory in Files while preserving existing bookmarks and labels.
Chezmoi initialization and application use the managed source, configuration file,
and target home explicitly. Setup
requests approval before replacing conflicting local dotfiles, then checks the
approved paths before continuing application. An explicit skip preserves local
changes and continues setup without applying Chezmoi dotfiles or scripts for that
run. Baseline home directories retain their permissions, and Git signing for restored keys uses
`~/.config/git/config` to leave Chezmoi's `.gitconfig` untouched. Bitwarden
collection reads use `community.general.bitwarden` with the shared managed-user
cache described in the [integration guide](../../../../../docs/development/README.md#bitwarden-integration).
Bitwarden email login prompts privately once per challenge, ignores terminal redraws, and
retries rejected codes with a fresh login attempt. Developer tool installation uses the GitHub credentials described in the
[configuration guide](../../../../../docs/usage/configuration.md#automated-runs).
CopyQ is configured for graphical login and started hidden during setup when a
GNOME session is active. Its Flatpak uses the XWayland clipboard workaround; an
already running instance needs a restart after that setting changes. See the
[configuration guide](../../../../../docs/usage/configuration.md) for verification
and limitations.
Developer tooling configures a system service for mise's Docker runtime bundle
on fresh installations and reruns, and grants the managed user immediate socket
access through a per-user ACL that is reapplied on every service start.
Compose and Buildx use mise-managed
CLI plugin binaries linked under Docker's expected plugin filenames. See
[developer tools](../../../../../docs/usage/configuration.md#developer-tools-and-project-files)
for access verification and version updates.
The managed Visual Studio Code Flatpak also exposes a `code` terminal launcher, preserving
an existing `/usr/local/bin/code`. Its integrated terminal uses host Zsh through
`host-spawn`; setup preserves unrelated JSONC settings and terminal profiles,
and excludes Linux terminal profiles and their default selection from Settings
Sync so cloud preferences cannot replace the host-shell configuration.
SSH restoration rejects private-key material in a Bitwarden `public_key` field
before writing the key pair. Browser inspection uses registered profile names
before falling back to saved per-profile names. Browser backup can explicitly
restore the required Sync everything setting. The live adapter then runs Sync,
compares recovery codes privately with Bitwarden, and verifies approved save or
restore actions automatically. Setup also enables Sync everything, joins
configured profiles to their stored chains, and requires verified synchronization.

See the [development guide](../../../../../docs/development/README.md) for
structure and checks, and the
[browser adapter contract](../../../../../docs/development/browser-adapters.md)
for adding a browser. User workflows live in the
[documentation index](../../../../../docs/README.md).
