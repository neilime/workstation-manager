# workstation-manager

Ubuntu machine setup driven entirely from this repository.

The repository is the source of truth for the tools, packages, and machine
configuration applied during installation.

## Workstation Management

Fresh Ubuntu machine bootstrap requires only:

- internet access
- `sudo`
- Bitwarden credentials plus the vault password available for the interactive login prompt

The public entrypoint is `workstation.sh`. The user does not need a local checkout
to install, re-apply, preview, or back up the machine.

Use it like this:

```sh
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- setup
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- setup --dry-run
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- cleanup --dry-run
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- backup --dry-run
```

`sh -s --` tells `sh` to read the script from standard input and pass the
remaining arguments to it.

- no extra argument: run the `setup` action
- `setup`: bootstrap dependencies and converge the workstation
- `cleanup`: prune removable workstation artifacts, remove stale managed directories, and write a drift report under the managed user state directory
- `backup`: create a user-state backup archive and standalone Chrome bookmark exports instead of applying configuration; prompts for the output directory when run interactively
- `--dry-run`: preview the selected action in Ansible check mode

`setup` and `setup --dry-run` both require Bitwarden-backed SSH/GPG restore. The
playbook now always runs the SSH and GPG restore roles, so the resolved Ansible
configuration must define `secrets.bitwarden.ssh_collection_id` and
`secrets.bitwarden.gpg_collection_id`. `workstation.sh` uses API credentials when
`BITWARDEN_CLIENT_ID`, `BITWARDEN_CLIENT_SECRET`, and `BITWARDEN_PASSWORD` are
already provided in the environment, which is the intended CI and end-to-end
automation path. End users are prompted for the Bitwarden email and vault
password instead of exporting them in the shell.

The script bootstraps its own dependencies and applies the repository with
`ansible-pull`. Running it again later is the normal way to re-apply the managed
workstation state. It uses a hidden checkout internally; that repository clone
is purged after each run and is an implementation detail, not part of the user
workflow.

The public interface is intentionally small: setup, cleanup, backup, and help.

Setup and cleanup automatically fetch `ansible/private.override.yml` from the
fixed `neilime/workstation-config` repository with Git and merge it as the
private override layer.

The Chezmoi source is fixed to `neilime/workstation-config`.

Keep any non-secret workstation overrides you do not want in this public
repository in that tracked file inside `neilime/workstation-config`.

Suggested layout:

```text
workstation-config/
  ansible/private.override.yml
  dot_*
```

Keep actual secrets in Bitwarden rather than writing them into that local file.

Because `neilime/workstation-config` is private, the bootstrap machine must be
able to authenticate to that Git repository. CI and end-to-end automation can
provide `WORKSTATION_MANAGER_GITHUB_TOKEN` for private GitHub repository access.

If you want to run a backup interactively, the script prompts for the destination.
CI and other non-interactive runs can still provide only
`WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR=/path/to/output-dir`.

The backup output includes the main archive, its manifest, and any discovered
Chrome bookmark exports under `browser-bookmarks/` for selective restore.

To preview changes without applying them:

```sh
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- setup --dry-run
```

To preview cleanup drift and removable artifacts without applying changes:

```sh
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- cleanup --dry-run
```

To show the remote command help:

```sh
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | sh -s -- help
```

## Browser First Run

The repository installs Google Chrome, sets it as the default browser, creates
stable managed profile directories, and applies browser-wide policies such as
baseline extensions, password-manager behavior, and startup defaults.

The repository does not sign browser profiles in for you and does not restore
profile-private state such as sessions, cookies, or client bookmarks.

After a fresh install:

1. Launch Chrome.
2. Open each declared profile and authenticate it with the correct browser-sync
   or identity account.
3. Sign in to the Bitwarden extension for each profile that needs password
   access.
4. Let browser sync restore bookmarks, extensions, and settings where sync is
   approved.
5. For manual or client profiles, restore only reviewed material such as an
   encrypted bookmark export or approved onboarding notes.

Treat browser recovery material as a secret. If you keep recovery notes in
local notes, an encrypted export, or another private workflow that stays
outside this repository. Do not commit raw browser databases, cookies,
sessions, or client bookmark sets to this repository.

## Developer Toolchains

The workstation now manages ephemeral developer toolchains with `mise`.

- Common workstation defaults live in `development.mise.tools` and are rendered
  to `~/.config/mise/config.toml`.
- Project-specific overrides should live in each project's own `mise.toml`,
  restored with the rest of the home/project configuration rather than being
  generated from Ansible state.
- Shell activation is managed automatically for Bash and Zsh login and
  interactive startup files.

See `ansible/vars/private.override.example.yml` for a private override example
covering non-secret workstation data.

## Development

The `Makefile` is for repository development and validation only. It is not the
public workstation-management interface.

### Host Requirements

Required for normal repository work:

- Docker Engine
- Git
- Make

Required only for end-to-end validation:

- cURL
- Lima
- `qemu-img`
- `qemu-system-x86_64`

### Quick Start

```sh
make setup
make lint
make check-ansible
make test
```

### Static Validation

Repository-side validation is split into three layers:

- `make lint` runs the repository lint surface
- `make check-ansible` runs playbook syntax validation
- `make test` runs `ansible-test sanity` and `ansible-test units`

### End-to-End Validation

The end-to-end flow runs a real user-setup-like process inside an Ubuntu VM.
It fetches `workstation.sh` over HTTPS, executes the same remote setup path that a
user runs, then verifies the workstation in three action-scoped phases:
`backup`, `setup`, and `cleanup`. Each action runs first, then its matching
assertion set runs before the next action starts.

```sh
make e2e-up
make e2e-test
make e2e-down
```

### CI

CI uses the same repository entry points as local development:

- `make setup`
- `make lint`
- `make check-ansible`
- `make test`
- `make e2e-up`
- `make e2e-test`

The static and end-to-end layers stay separate in CI as well:

- static checks cover linting, Ansible syntax validation, and `ansible-test`
- end-to-end validation covers the remote `setup`, `backup`, and `cleanup` paths plus VM-level assertions
