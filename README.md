# workstation-manager

Set up, back up, and maintain an Ubuntu workstation. Setup installs applications
and developer tools, applies your dotfiles, restores keys, and configures the
desktop and Brave profiles.

## Before you start

You need the [supported Ubuntu release](ansible/ubuntu-version), internet access,
`wget`, `sudo`, access to your private configuration repository, and your Bitwarden
credentials. Prepare your [configuration and recovery sources](docs/usage/configuration.md)
first.

Run commands in your desktop session with its keyring unlocked. Complete sign-in
when prompted and close Brave before applying profile changes. Setup removes
Snap; check the [installation requirements](docs/usage/configuration.md#application-delivery)
if your boot or encryption depends on it.

## Set up or update the workstation

```sh
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- setup
```

Rerun setup after publishing configuration changes. To restore a backup during
setup, follow [backup and restore](docs/usage/backup-and-restore.md).

Append `--dry-run` to preview an action:

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
See [backup and restore](docs/usage/backup-and-restore.md) for recovery checks,
archive contents, and restoration.

## Clean up

Preview the changes, then apply them:

```sh
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- cleanup --dry-run
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- cleanup
```

See [cleanup](docs/usage/cleanup.md) for changes and preserved data.

## Help and documentation

```sh
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- help
```

- [Configuration](docs/usage/configuration.md): private settings, keys, dotfiles, and tools.
- [AI tools](docs/usage/ai-tools.md): accounts, MCP servers, and skills.
- [Browser profiles](docs/usage/browser.md): recovery, Sync, colors, and logos.
- [Documentation index](docs/README.md): all detailed guides.
