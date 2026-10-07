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
run. Baseline home directories and browser setup preserve existing `.config`
permissions. Restored Git signing fingerprints and formats use
`~/.config/git/config`; static Git preferences belong to Chezmoi's `.gitconfig`. Bitwarden
collection reads use `community.general.bitwarden` with the shared managed-user
cache described in the [integration guide](../../../../../docs/development/README.md#bitwarden-integration).
Bitwarden email login prompts privately once per challenge, ignores terminal redraws, and
retries rejected codes with a fresh login attempt. Developer tool installation uses the GitHub credentials described in the
[configuration guide](../../../../../docs/usage/configuration.md#automated-runs).
Chezmoi owns the wallpaper asset and Clipboard Indicator preferences. Setup
installs and enables the checksum-pinned GNOME extension, applies the companion
profile, and removes CopyQ applications while preserving their history.
Setup always enables GNOME dark mode, dock Trash, and GNOME Software updates.
Browser automation discovers the managed user's live desktop environment,
including when setup runs through SSH. See the [browser adapter contract](../../../../../docs/development/browser-adapters.md).
Dock favorites use the public defaults; null preserves existing favorites.
Wallpaper settings are applied only when the dotfiles-managed image exists.
Setup installs native Simple Scan/SANE and removes duplicate scanner Flatpaks
without deleting their data. BleachBit runs saved presets weekly through a user timer and also
provides a manual command. Setup activates the timer in the current user session
or on the next graphical login, preserving saved cleaner preferences.
See [desktop configuration](../../../../../docs/usage/configuration.md#clipboard-and-personal-file-backup)
and [cleanup policy](../../../../../docs/usage/cleanup.md).
Developer tooling installs native Docker and GitHub CLI packages, a complete system
Node.js LTS runtime, and verified mise releases for remaining user tools. Setup
removes Snap after verified data preservation and rejects Snap-dependent boot or
encryption. See [application delivery](../../../../../docs/usage/configuration.md#application-delivery)
and [developer tools](../../../../../docs/usage/configuration.md#developer-tools-and-project-files)
for update ownership, recovery archives, and access verification.
Visual Studio Code uses Microsoft's native APT package and native Zsh. Setup
preserves unrelated editor settings and personal profiles.
PHP and Composer are mandatory mise tools with
pinned releases. Setup installs PHP build prerequisites; mise downloads and
verifies the official Composer release.
Setup always installs pinned Codex and GitHub Copilot CLIs, Orca, Helm, Dive,
gh-act, and gh-stack. The default GitHub extensions use published binary release tags.
The Starship launcher uses mise's resolved executable path for the configured release.
The Git project report provides a manual command and daily desktop notifications.
GitHub authentication must match the required `development.github.account` and
persist in the managed user's OS credential store. See the
[developer-tool configuration](../../../../../docs/usage/configuration.md#developer-tools-and-project-files)
for selections and sign-in steps.
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
