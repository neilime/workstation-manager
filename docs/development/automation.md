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

All paths invoke `run_action`; `run_ansible_pull` selects the local or remote
controller. Remote execution limits playbooks to `localhost` and ignores only
unmatched checkout hostname aliases. Real task warnings and failures remain visible.

The session helper forwards nonempty desktop, GPG terminal, and SSH agent values
across sudo without changing the caller's environment. Empty values stay unset.
Interactive Ansible capture uses `script` and assigns the terminal to the managed
user without loosening its permissions. Piped capture fetches the configured
entrypoint and validates its shell syntax. Cleanup traps remove temporary
manifests, capture files, source copies, and credentials on success or failure.

Exercise changes with isolated entrypoint tests in `e2e-tests/unit/`.
Never put credential values in examples, overrides, or Git.

## Bitwarden integration

Collection enumeration and key-backup reads use
`community.general.bitwarden` from the shared
[collection manifest](../../ansible/collections/requirements.yml).
`query(...) | first` preserves collection results as a list; individual item reads
require `result_count=1`. Missing records and lookup failures stop backup.

Lookups run on the controller without task `become` or `environment`.
The thin setup adapter selects the managed user's CLI cache for the call,
restores controller state, and replaces upstream exception text with a safe
failure. CLI stderr can contain secrets before Ansible applies `no_log`.

Keep login, unlock, server selection, collection metadata, attachments, vault
writes, and cache synchronization in managed-user CLI tasks. Browser recovery
and post-write verification require fresh reads in their execution context;
do not replace those reads with cached controller facts.
