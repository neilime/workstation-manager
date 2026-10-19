# neilime.workstation_setup

Owns configuration normalization, system and application setup, secrets retrieval,
home-environment setup (including the Zsh login shell, Oh My Zsh, and Chezmoi),
developer tooling, and browser adapters. GNOME setup bookmarks the configured
projects directory in Files while preserving existing bookmarks and labels.
Chezmoi initialization and application use the managed source, configuration file,
and target home explicitly. The generated configuration keeps
[dotfile permissions](../../../../../docs/usage/configuration.md#dotfiles-and-application-settings)
consistent between setup and user commands. Setup
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
[configuration guide](../../../../../docs/usage/configuration.md#edit-your-private-override).
Chezmoi owns the wallpaper asset and Clipboard Indicator preferences. Setup
installs and enables the checksum-pinned GNOME extension and applies the companion
profile.
Setup always enables GNOME dark mode, dock Trash, and GNOME Software updates.
Browser automation discovers the managed user's live desktop environment,
including when setup runs through SSH. It reuses matching Sync chains and verifies
duplicate-device cleanup according to the [browser guide](../../../../../docs/usage/browser.md).
Backup can save per-profile bookmark-bar visibility and close-tabs confirmation
in Bitwarden; setup restores and verifies the saved choices after Sync.
See the [browser adapter contract](../../../../../docs/development/browser-adapters.md).
Dock favorites use the public defaults, including Orca; null preserves existing favorites.
Wallpaper settings are applied only when the dotfiles-managed image exists.
Setup installs native Simple Scan/SANE and removes duplicate scanner Flatpaks
without deleting their data. BleachBit runs saved presets weekly through a user timer and also
provides a manual command. Setup activates the timer in the current user session
or on the next graphical login, preserving saved cleaner preferences.
See [desktop configuration](../../../../../docs/usage/configuration.md#clipboard-and-personal-file-backup)
and [cleanup policy](../../../../../docs/usage/cleanup.md).
Developer tooling installs native Docker and GitHub CLI packages, a complete system
Node.js LTS runtime, and verified mise releases for remaining user tools. Flatpak
remote configuration and application installation use bounded retries for download
failures. Setup
removes Snap after verified data preservation and rejects Snap-dependent boot or
encryption. See [application delivery](../../../../../docs/usage/configuration.md#application-delivery)
and [developer tools](../../../../../docs/usage/configuration.md#developer-tools-and-project-files)
for update ownership, recovery archives, and access verification.
Visual Studio Code uses Microsoft's native APT package and native Zsh. Setup
preserves unrelated editor settings and personal profiles.
The `ai_tools` role owns Orca, the baseline AI CLIs, pinned MCP packages, browser
prerequisites and declared skills under `development.ai_tools` in the public
`all.yml`. Codex and Copilot adapters
merge private native configuration. Each `providers` entry defines its CLI
installation and selects its adapter together. Setup reuses native provider
ChatGPT and Copilot sessions or starts native sign-in, resolves MCP keys from
Bitwarden and runs declared read-only access checks. Installation-only runs can
explicitly defer provider login; setup reports that authentication is unverified.
See [AI tool configuration](../../../../../docs/usage/ai-tools.md) and the
[adapter contract](../../../../../docs/development/ai-tools.md).
PHP and Composer are mandatory mise tools with
pinned releases. Setup installs PHP build prerequisites; mise downloads and
verifies the official Composer release.
The default providers install pinned Codex and GitHub Copilot CLIs. Setup also
installs Orca, Helm, Dive, Skillshare, gh-act, and gh-stack.
Setup provisions declared [project skills](../../../../../docs/development/README.md#project-skills)
after restoring projects and establishing GitHub authentication. The default GitHub extensions use published binary release tags.
The Starship launcher uses mise's resolved executable path for the configured release.
The Git project report provides a manual command and daily desktop notifications.
GitHub authentication runs before private-repository access through
`ansible/github_bootstrap.yml`, which installs or updates GitHub CLI from its
official APT repository. It reuses a saved login or performs native browser
sign-in, with token input for automation. The login persists in the managed user's
OS credential store and must match `development.github.account` once configuration
is loaded. Context7 requires a Bitwarden API-key item selector. See the
[developer-tool configuration](../../../../../docs/usage/configuration.md#developer-tools-and-project-files)
for selections and sign-in steps.
SSH restoration rejects private-key material in a Bitwarden `public_key` field
before writing the key pair. Browser inspection uses registered profile names
before falling back to saved per-profile names. Setup restores the required
Sync everything setting. The live adapter then runs Sync,
compares recovery codes privately with Bitwarden, and verifies approved save or
restore actions automatically. Setup also enables Sync everything, joins
configured profiles to their stored chains, and requires verified synchronization.

See the [development guide](../../../../../docs/development/README.md) for
structure and checks, and the
[browser adapter contract](../../../../../docs/development/browser-adapters.md)
for adding a browser. User workflows live in the
[documentation index](../../../../../docs/README.md).
