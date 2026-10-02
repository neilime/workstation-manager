# workstation-manager

Set up, maintain, and recover an Ubuntu workstation with Ansible.

The project installs applications and developer tools, configures GNOME, applies
Chezmoi dotfiles, restores SSH/GPG keys from Bitwarden, and creates Brave profiles.
Backup checks recovery sources before archiving project files and writes a
browser sidecar with bookmarks plus sanitized non-secret preferences when
profiles exist. Cleanup maintains
packages, removes unused artifacts, and reports configuration drift.

## Before you start

You need Ubuntu, internet access, `curl`, `sudo`, and:

- Access to your configured private configuration and dotfiles sources.
- Bitwarden credentials and configured SSH/GPG key collections.
- A browser profile collection if you want managed Brave profiles.

Set up your [private configuration](docs/usage/configuration.md) first. Run the
commands below from a terminal in your desktop session. Setup prompts for GitHub
authentication when needed; setup, backup, and cleanup prompt for Bitwarden access.
Password and emailed Bitwarden verification-code input are hidden. If Bitwarden
rejects the entered email, verification code, or vault password, the script asks
again. Press Ctrl-C to cancel a prompt.

## Set up or update the workstation

```sh
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- setup
```

Run the same command after changing your configuration. Setup installs its
dependencies and applies the configured packages, keys, dotfiles, and desktop
settings. Close Brave before applying profile changes. After setup, complete
[Brave Sync](docs/usage/browser.md) and editor sign-in when prompted.

To preview an action, append `--dry-run`:

```sh
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- setup --dry-run
```

A preview uses Ansible check mode. Bootstrap dependencies may still be installed,
repositories downloaded, and authentication performed. A fresh machine may need
a normal setup before all preview checks can run.

## Back up

```sh
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- backup
```

Choose the destination when prompted and resolve any synchronization differences.
See [backup and restore](docs/usage/backup-and-restore.md) for archive contents,
recovery checks, and restoring onto another computer.

## Clean up

Preview cleanup before applying it:

```sh
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- cleanup --dry-run
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- cleanup
```

Cleanup includes package upgrades, unused package removal, Docker pruning, and
log retention. Read [cleanup](docs/usage/cleanup.md) for the exact scope.

## Help and documentation

```sh
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- help
```

- [Configuration](docs/usage/configuration.md): private overrides, keys, dotfiles, and tools.
- [Browser profiles](docs/usage/browser.md): Bitwarden records, Sync, colors, and logos.
- [Backup and restore](docs/usage/backup-and-restore.md): recovery checks and archives.
- [Cleanup](docs/usage/cleanup.md): changes, preserved data, and reports.
- [Development](docs/development/README.md): repository layout, checks, and VM tests.

The [documentation index](docs/README.md) lists all guides.
