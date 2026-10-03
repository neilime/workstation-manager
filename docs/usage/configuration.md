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

Choose the server that hosts your vault; the default is
`https://vault.bitwarden.eu`. Setup requires nonempty SSH and GPG collections.
Your account must be able to read them. Backup also needs write access when you
approve adding or updating keys.

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
and enables Git commit and tag signing with it.

The browser collection is optional. Leave its selector empty to create no managed
profiles, or follow [browser profiles](browser.md) to populate it. Backup reports
local browser profiles missing from the collection as drift.

## Dotfiles and application settings

`home_environment.chezmoi.source` selects the Git repository used to initialize
`~/.local/share/chezmoi`. Use a full HTTPS or SSH Git URL. Setup applies its
dotfiles to your home directory. An existing checkout is reused; changing the
source setting does not switch its remote.

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
install directories, keep the activation in its bootstrap form so each shell
refreshes the cached init script against the current binary:

```zsh
source "$HOME/.config/workstation-manager/mise.sh"
eval "$(deja init zsh)"
```

Do not enable `zsh-autosuggestions` at the same time; Déjà replaces it. For a
pinned Oh My Zsh installation, add
`zstyle ':omz:update' mode disabled` before sourcing `~/.oh-my-zsh/oh-my-zsh.sh`;
setup then owns framework updates. Setup leaves `.zshrc` ownership to Chezmoi and
does not change the account's login shell.

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

Set workstation-wide tool versions in `development.mise.tools`. They are
written to `~/.config/mise/config.toml`; project-specific versions belong in each
project's `mise.toml`.

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
