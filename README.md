# workstation-manager

Set up, maintain, and recover an Ubuntu workstation with Ansible. Setup installs
applications and developer tools, applies personal dotfiles, restores keys, and
configures the desktop and Brave profiles.

## Before you start

You need the [supported Ubuntu release](ansible/ubuntu-version), internet access,
`wget`, `sudo`, access to your private configuration repository, and your Bitwarden
credentials. Prepare your [configuration and recovery sources](docs/usage/configuration.md)
first.

Run commands in your desktop session with its keyring unlocked. Complete GitHub,
Bitwarden, and application sign-in when prompted. Close Brave before applying
profile changes. Setup removes Snap; boot or encryption that depends on Snap
requires a [supported installation](docs/usage/configuration.md#application-delivery).

## Set up or update the workstation

```sh
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- setup
```

Rerun setup after publishing configuration changes. It applies the configured
tools, dotfiles, desktop settings, keys, and browser recovery.

To preview an action, append `--dry-run`:

```sh
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- setup --dry-run
```

Previews use Ansible check mode. Bootstrap installation, downloads, and
authentication can still occur. A fresh machine may need normal setup first.

## Back up

```sh
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- backup
```

Choose a destination and resolve synchronization differences when prompted.
Read [backup and restore](docs/usage/backup-and-restore.md) for recovery checks,
archive contents, and restoration onto another computer.

## Clean up

Preview cleanup, then apply it:

```sh
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- cleanup --dry-run
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- cleanup
```

See [cleanup](docs/usage/cleanup.md) for changes, preserved data, and preview limits.

## Help and documentation

```sh
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- help
```

- [Configuration](docs/usage/configuration.md): private settings, keys, dotfiles, and tools.
- [AI tools](docs/usage/ai-tools.md): accounts, MCP servers, and skills.
- [Browser profiles](docs/usage/browser.md): recovery, Sync, colors, and logos.
- [Documentation index](docs/README.md): all detailed guides.
