# Entrypoint and automation

Keep [`workstation.sh`](../../workstation.sh) self-contained and POSIX-compatible
for piped execution. Local execution uses the checkout, including uncommitted
changes; piped execution uses the published repository unless overridden.

## Source selection

| Variable                                    | Purpose                                  |
| ------------------------------------------- | ---------------------------------------- |
| `REPOSITORY_URL`                            | GitHub repository URL or local checkout. |
| `REPOSITORY_BRANCH`                         | Branch, tag, or full commit SHA.         |
| `WORKSTATION_MANAGER_PRIVATE_OVERRIDE_FILE` | Absolute path to a local override.       |

Local example:

```sh
WORKSTATION_MANAGER_PRIVATE_OVERRIDE_FILE=/absolute/path/private.override.yml ./workstation.sh setup
```

For an immutable remote run, replace the placeholder with a reviewed commit and
use it for both the entrypoint and checkout:

```sh
revision="<reviewed-40-character-commit>"
wget -qO- "https://raw.githubusercontent.com/neilime/workstation-manager/${revision}/workstation.sh" | \
  REPOSITORY_BRANCH="$revision" sh -s -- setup
```

## Automated runs

Automation uses the public `setup`, `backup`, and `cleanup` commands.
Supply credentials through a secret store and ensure sudo can run unattended.

| Variable                                                               | Purpose                                              |
| ---------------------------------------------------------------------- | ---------------------------------------------------- |
| `WORKSTATION_MANAGER_GITHUB_TOKEN`                                     | GitHub CLI sign-in when no valid saved login exists. |
| `WORKSTATION_MANAGER_GHCR_TOKEN`                                       | Optional separate registry credential.               |
| `BW_SESSION`                                                           | Reuse an unlocked Bitwarden CLI session.             |
| `BITWARDEN_CLIENT_ID`, `BITWARDEN_CLIENT_SECRET`, `BITWARDEN_PASSWORD` | Bitwarden API login and vault unlock.                |
| `WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR`                                | Required destination for unattended backup.          |

Without a reusable session, provide all three Bitwarden values.
Missing credentials or a required human recovery decision stop noninteractive
runs. Terminal availability controls prompting and retries; `CI` and
`GITHUB_ACTIONS` do not change workstation behavior.

Keep the desktop keyring unlocked. GitHub login must match
`development.github.account`. For github.com, Docker uses that login with
`write:packages` by default. Unattended runs cannot grant missing scopes; supply
a saved authorized login or a separate GHCR credential with the required image
access. CI supplies its short-lived job token with `packages: write`.
Registry authentication and keyring checks do not establish access to every image.

Bootstrap authenticates before reading private configuration. Setup passes the
verified GitHub token to mise, extension installation, and Orca release lookup
through private environments; logs and redirected requests must not expose it.
Selected AI providers need [native logins](../usage/ai-tools.md#authentication)
unless explicitly deferred. Browser Sync decisions still require interaction.

## Execution and credential safety

The entrypoint enables Ansible pipelining for local module execution, including
remote bootstrap and interactive capture. Set `ANSIBLE_PIPELINING=false` when a
custom sudo policy requires a terminal for every operation. The explicit override
survives privilege escalation.

Setup starts one Flatpak application transaction after configuring its prerequisites
and overlaps it with development tooling installation. It waits for completion,
including retries, before restoring keys, dotfiles, or archives. A development
failure still waits for the pending transaction before returning failure. APT
operations stay serial; direct Flatpak role calls and previews stay synchronous.
Native scanner cleanup runs after application installation completes.

Preserve these entrypoint contracts:

- Local and remote execution share `run_action`; remote playbooks target only
  `localhost`. Suppress only unmatched checkout hostname aliases, not task warnings.
- Forward nonempty desktop, GPG terminal, and SSH agent values across sudo
  without changing the caller's environment.
- Keep `/dev/tty` prompting usable during piped execution. Interactive capture
  assigns the terminal to the managed user without loosening its permissions.
- Validate downloaded shell source before capture and remove temporary manifests,
  capture files, source copies, and credentials on success or failure.

Run the entrypoint coverage in `tests/unit/` and `tests/integration/` through the
[development checks](README.md). Keep credentials out of examples, overrides and Git.

## Bitwarden integration

Collection enumeration and key-backup reads use the setup collection's
[Bitwarden lookup adapter](../../ansible/collections/ansible_collections/neilime/workstation_setup/plugins/lookup/bitwarden.py),
which delegates to `community.general.bitwarden`. Use `query(...) | first` for
collection lists and `result_count=1` for individual items. Missing records and
lookup failures stop backup.

Controller lookups do not inherit task `become` or `environment`. The adapter
selects the managed user's CLI cache, restores controller state, and sanitizes
upstream exceptions before Ansible applies `no_log`.

Keep login, unlock, server selection, collection metadata, attachments, vault
writes, and cache synchronization in managed-user CLI tasks. Browser recovery
and post-write verification require fresh reads in their execution context;
do not replace those reads with cached controller facts.

Collection reads reuse an unlocked session only within the same action, managed
user, home, CLI cache, server, and configured account context. Each reuse runs a
live status check; locked or expired sessions must unlock again, and an unexpected
account change stops recovery. These facts remain in memory for the current
Ansible run. Every collection read still synchronizes the vault, and writes keep
their explicit synchronization and read-back verification.

Authentication uses the internal `neilime.workstation_setup.bitwarden_cli` module
for credential-bearing status, login, unlock, and sync calls. It passes credentials
inside the managed process so verbose connection tracing cannot expose task
environment values. Its callers retain `no_log`, and failed CLI output is discarded
before returning the status used for diagnostics and retries.

## Recovery decisions

`neilime.workstation_backup.recovery_decision` owns prompts, input retries,
noninteractive and preview handling, aborts, and explicit skips for the manifest.
Source roles inspect state, offer safe actions, execute the selected action, and
verify its result. See [backup and restore](../usage/backup-and-restore.md) for
the user workflow.

Pass these variables at each decision point:

- `workstation_backup_recovery_id`: stable lowercase identifier.
- `workstation_backup_recovery_needed`: whether a decision is required; defaults
  to `true`.
- `workstation_backup_recovery_request`: `scope`, `summary`, `actions` (names
  mapped to descriptions), `skip` (skipped coverage), and `abort_message`.
  Include display metadata only, never complete secret records.

Callers declare their actions; the role adds `skip` and `abort`. Use `save` to copy
local values into recovery storage and `restore` for the reverse direction. Offer
only directions with usable source data. Destructive actions and publication need
their own approvals.

Read the result from `workstation_backup_recovery_choices[id]`. Every invocation
resets that entry, including previews and unnecessary checks, so an earlier
approval cannot authorize another action. Previews report pending work without
selecting an action or recording a skip. Required noninteractive decisions fail;
unnecessary requests are not evaluated.

Decision IDs distinguish stages such as `chezmoi-files`, `chezmoi-publish`,
`browser-recovery`, and `browser-sync`; `key` is reset for each SSH/GPG item.
Manifest scopes group coverage under `chezmoi`, `ssh-keys`, `gpg-keys`,
`browser-recovery`, and `browser-sync`. Recording a skipped scope does not skip
other decisions: callers control continuation, including later keys.

A `retry` must reload and inspect state. A mutation must pass verification before
continuing. Neither a retry nor an approved action counts as verified recovery.
