# Development

Use Git, Make, and Docker Engine for repository work. Run workstation-changing
tests in the Lima VM.

See [ADR 0001](adr/adr-0001-workstation-toolchain.md) for the current workstation
software choices, their rationale, and validation criteria.

## Repository layout

```text
workstation.sh                    Public setup, backup, cleanup, and help commands
ansible/
  setup.yml, backup.yml, cleanup.yml
  group_vars/all.yml             Public configuration defaults
  vars/private.override.example.yml
  tasks/                         Configuration resolution and setup orchestration
  collections/ansible_collections/neilime/
docs/
  usage/                         User workflows and configuration
  development/                   Implementation and validation
docker/tooling/                  Ansible and Python test image
e2e-tests/                       Lima workflows, VM assertions, and host-tool tests
ci/                             Report helpers
```

The five first-party collections own these responsibilities:

- `workstation_setup`: configuration normalization, system and application setup,
  secrets retrieval, and browser adapters.
- `workstation_backup`: recovery checks, synchronization, archive creation, and
  Git inventory.
- `workstation_restore`: archive validation, extraction, and Git repository
  reattachment during setup.
- `workstation_cleanup`: cleanup, managed-state comparison, and terminal drift summaries.
- `workstation_state`: shared state serialization and baseline markers.

Keep orchestration in playbooks and roles, reusable Python in
`plugins/module_utils/`, and Ansible adapters in `plugins/modules/` or
`plugins/filter/`. Roles consume `workstation_manager_resolved`. Configuration
changes must update the defaults, normalizers, private override example, tests,
and relevant guide together.

Backup source roles use the shared
[recovery decision contract](../../ansible/collections/ansible_collections/neilime/workstation_backup/roles/recovery_decision)
for prompting and recording explicit choices. Keep source inspection, mutations,
and verification in their owning roles. Each decision starts with an empty result;
callers must execute only the currently approved action and recheck its outcome.

See [browser adapters](browser-adapters.md) for that extension contract and
[AGENTS.md](../../AGENTS.md) for repository-wide contribution rules. Record
significant architectural decisions as [decision records](adr/README.md).

## Documentation and test contract

Documentation and tests describe the current codebase. This includes ADRs,
collection readmes, usage guides, examples, test names, docstrings, and fixtures.
Write the supported behavior directly. Do not preserve implementation history,
completed migration steps, obsolete alternatives, or tests for retired behavior.

ADRs explain the current architecture and its trade-offs. Link to maintained
configuration for versions and selections. Describe manual acceptance requirements
as requirements, and report validation only when it has actually run; an installed
application does not prove desktop usability or recovery coverage.

Review each change with these checks:

1. Trace affected documentation claims to the current entrypoint, normalized
   configuration, owning role, or helper. Check commands, paths, defaults, ownership,
   and stated guarantees; update local links and section anchors together.
2. Identify the current contract protected by each affected test. Cover supported
   inputs, outputs, errors, and side effects through behavior. Remove obsolete
   scenarios, fixtures, and helpers rather than renaming historical tests.
3. Read test expectations from maintained configuration where appropriate and use
   synthetic inputs for isolated validation. Do not snapshot past versions,
   package inventories, removed flags, or deleted filenames.
4. Preserve meaningful checks for clean setup, reruns, previews, permissions,
   credentials, recovery, and unmanaged data. Existing application data and saved
   state exercise current safety contracts; they are not project history.
5. Run affected tests and applicable lint and local link checks. Report the checks
   actually run and any limitations without turning documentation into a work log.

Keep implementation and verification instructions aligned with this contract in
[`AGENTS.md`](../../AGENTS.md). The companion repository owns the shared personal
instructions under `home/dot_agents/`; update their source files there when the
same rule applies across repositories.

## Project skills

Workstation setup installs [Skillshare](https://skillshare.runkids.cc) globally.
Each project needs one hand-maintained file:
[`.skillshare/config.yaml`](../../.skillshare/config.yaml).

```yaml
targets: [universal]
skills:
  - name: example
    source: owner/repository/path/to/skill
```

Workstation setup discovers these configs under `user.projects_directory`
after restoring project files and verifying GitHub authentication. It installs
missing skills and syncs each project's configured targets as the managed user.
Add a skill to the config and run your normal workstation setup; no project
installer or task file is needed. Dry runs list the projects without running
Skillshare. Configs in dependency/cache directories are ignored, and discovery
does not follow symlinked directories.

For immediate application to a single project, or a project outside that
directory, you can also run:

```sh
skillshare install -p && skillshare sync -p
```

Skillshare downloads standard [Agent Skills](https://agentskills.io/home) and
links them into `.agents/skills/`. The `universal` target serves both Codex and
Copilot from this one directory. This repository selects Ansible Community's
`write-content` for Ansible YAML and `write-module` for Python modules. Existing
installed skills are preserved; setup does not upgrade their revisions.

For a project used with Claude Code, change the same config's target list to:

```yaml
targets: [universal, claude]
```

Skillshare then also links the same skills into `.claude/skills/`, Claude Code's
supported project location. No separate skill content or plugin package is
needed. Ignore those generated links as well. Target selection does not install
an assistant or configure its account.

Commit the config and the generated `.skillshare/skills.lock.json`, which pins
exact Git commits. Skillshare ignores its downloaded sources automatically;
keep generated `.agents/skills/` links ignored as in this repository's
[`.gitignore`](../../.gitignore). Let Skillshare manage lockfile hashes.

To update, run `skillshare update --all -p && skillshare sync -p` and review the
lockfile diff. To remove a skill, run
`skillshare uninstall NAME -p && skillshare sync -p`.
The CLI version is maintained in the public
[workstation defaults](../../ansible/group_vars/all.yml) with Renovate coverage.

For private GitHub sources, use `gh auth login` and `gh auth setup-git`.
Global skills remain managed by [workstation setup](../usage/ai-tools.md#skills).

## Local checks

```sh
make setup
make lint
make check-ansible
make check-collections
make test
```

- `make setup` builds the tooling image, reusing Docker layers when its inputs
  are unchanged. CI pulls the image published by its build job.
- `make lint` builds and runs the separate repository linter image, including
  Ansible Lint.
- `make check-ansible` checks all top-level playbooks against the local inventory.
- `make check-collections` runs `ansible-test sanity` for first-party collections.
- `make test-unit` runs fast host and collection unit tests together in one pytest
  process, using the tooling image's Python.
- `make test-integration` runs isolated local Ansible and terminal integration tests
  with two workers. Set `HOST_TEST_WORKERS=1` for sequential execution.
- `make test` runs both test suites. VM tests remain a separate, explicit command.
- `make test-host` selects all tests in `e2e-tests/unit/`; `make test-collections`
  selects collection sanity and unit checks. These are alternatives for focused work.

For a focused iteration, use `make test-unit TEST_ARGS="-k desired_state"` or
`make test-integration TEST_ARGS="-k clipboard"`. `TEST_ARGS` accepts pytest selection
and reporting options. Both suites report their slowest tests. Plain pytest uses
the same default test paths and never discovers VM assertions implicitly.

Keep each assertion at the cheapest useful layer. Unit tests cover parsing,
normalization, and failure cases with synthetic inputs. Tests marked `integration`
cover real Ansible wiring, permissions, check mode, prompts, and error propagation
using disposable fixtures. VM assertions cover installed behavior and external
integration. Keep archive safety, recovery decisions, secret redaction, and user
data preservation covered even when simplifying scenarios.

Use the shared playbook and environment helpers in `e2e-tests/unit/ansible_test_helpers.py`.
Load public defaults for configuration integration checks; use synthetic releases
for version validation. VM package and version assertions compare the maintained
configuration with observed guest state. Avoid package-list snapshots, source-text
assertions, and repeating parser cases through Ansible or the VM. Combine assertions
that require the same expensive setup, and use scenario tables instead of Cartesian
products unless the interaction itself needs testing.

The tooling image includes Python dependencies for host and end-to-end assertions and
Ansible collections from [its versioned requirements](../../ansible/collections/requirements.yml).
Syntax checks and tests use these installed dependencies without downloading them
again. Bootstrap and the image use the same collection manifest and
[controller requirements](../../ansible/requirements.txt). The image verifies its
Ubuntu release against [the supported baseline](../../ansible/ubuntu-version).
Run `make setup` after changing these manifests.

CI runs Super-Linter, including Ansible Lint, independently. Ansible syntax and
sanity checks, unit/integration tests, and end-to-end tests run in parallel once
the tooling image is available. Each job publishes its own result.
The Ansible job caches only sanity virtual environments in `.cache/ansible-test`,
keyed by runner architecture and tooling image filesystem layers. Changes to the
runtime invalidate that cache; changes to image labels alone do not.

Do not edit generated caches, reports, vendored collections, or test output.

Tooling containers run with the host UID and GID. The launcher supplies temporary,
read-only account files with `/tmp` as the tooling account's home, so account
lookups and Ansible temporary files work independently of the image's built-in
user and the host home directory.

Use `make tool-shell` for an interactive tooling container. `make lint-fix`
rewrites files; `make ci` runs it before syntax, collection sanity, and test checks. Review its diff.
Documentation-only changes need applicable lint and local link checks.

## Entrypoint and automation

Running `./workstation.sh` from a local checkout defaults to that checkout and
its current branch or detached commit. Direct local runs execute Ansible from
the local working tree, including uncommitted changes. The piped `curl ... | sh`
bootstrap still uses the published GitHub repository unless you override
`REPOSITORY_URL`.

Keep the public entrypoint self-contained for piped execution. Its environment
inputs are grouped at the top as optional user inputs, automation credentials,
and development/CI source overrides. Internal runtime state and test handoffs are
labeled separately. Keep CI input preparation distinct from workstation behavior:
`main` always calls `run_action`, and the VM runners use the same public commands.
Bootstrap establishes a GitHub CLI keyring login before fetching private
configuration. `run_action` then reuses an unlocked Bitwarden CLI session when one
is available or collects Bitwarden credentials;
`run_ansible_pull` selects the local or remote controller command. Remote runs
explicitly limit playbook execution to `localhost` and ignore unmatched hostname
aliases added by `ansible-pull` during checkout. This setting applies only to the
remote invocation; task warnings and failures remain visible. Terminal
availability determines prompting and output capture. See
[automated runs](#automated-runs) for CI inputs. Both direct
execution and terminal capture use the same session environment helper. Temporary
bootstrap manifests and capture files use scoped cleanup traps, including on
failure or interruption. Exercise these paths with the isolated entrypoint tests
in `e2e-tests/unit/` before changing bootstrap behavior.

The session helper forwards nonempty desktop, GPG terminal, and SSH agent values
across sudo. Missing or empty values stay unset in the child process so headless
runs do not pass invalid display or terminal options to GnuPG through GPGME.
The caller's environment is preserved.

Interactive runs capture Ansible output through `script` while keeping prompts
on a terminal. The capture runner assigns its newly allocated terminal to the
resolved user without changing its permissions, so root orchestration and
managed-user verification prompts can share the same input path. When the entrypoint is piped into `sh`, this runner loads
`workstation.sh` from the configured repository and ref because the running
script has no source file on disk. Local runs reuse their entrypoint source.
The runner validates shell syntax before execution and removes its temporary
source and credential files afterward.

### Source overrides

Development and CI can select the source and private override through these
environment variables:

| Environment variable                        | Purpose                                             |
| ------------------------------------------- | --------------------------------------------------- |
| `REPOSITORY_URL`                            | GitHub repository URL or local checkout to execute. |
| `REPOSITORY_BRANCH`                         | Branch, tag, or full commit SHA to apply.           |
| `WORKSTATION_MANAGER_PRIVATE_OVERRIDE_FILE` | Absolute path to a local private override file.     |

To use a local override:

```sh
WORKSTATION_MANAGER_PRIVATE_OVERRIDE_FILE=/absolute/path/private.override.yml ./workstation.sh setup
```

To exercise the remote bootstrap at a reviewed immutable revision, use the same
full commit for the entrypoint and its Ansible checkout:

```sh
revision="<reviewed-40-character-commit>"
wget -qO- "https://raw.githubusercontent.com/neilime/workstation-manager/${revision}/workstation.sh" | \
  REPOSITORY_BRANCH="$revision" sh -s -- setup
```

### Automated runs

CI and interactive use run the same `setup`, `backup`, and `cleanup` commands.
For unattended execution, supply the inputs that would otherwise be prompted for
through your automation's secret store.

All three Bitwarden values must be supplied to skip the credential prompts.
Missing Bitwarden credentials without a terminal stop the workstation action;
a missing backup destination stops before bootstrap. Ensure sudo can run unattended.
Terminal availability controls prompting and authentication retries; the `CI`
and `GITHUB_ACTIONS` environment flags do not change execution.

| Environment variable               | Purpose                                                                |
| ---------------------------------- | ---------------------------------------------------------------------- |
| `WORKSTATION_MANAGER_GITHUB_TOKEN` | Token for GitHub CLI sign-in when no valid saved keyring login exists. |
| `BW_SESSION`                       | Reuse an already-unlocked Bitwarden CLI session instead of prompting.  |
| `BITWARDEN_CLIENT_ID`              | Bitwarden API client ID.                                               |
| `BITWARDEN_CLIENT_SECRET`          | Bitwarden API client secret.                                           |
| `BITWARDEN_PASSWORD`               | Unlock the Bitwarden vault.                                            |

Unattended runs require an unlocked desktop keyring and either a valid saved
GitHub CLI login or a token accepted by `gh auth login --with-token`. They run
the same GitHub authentication and Git integration steps as interactive use.
For github.com, that login also requires `write:packages` for Docker's GHCR
authentication; unattended runs cannot grant missing permissions.
Bootstrap and installation downloads reuse the verified saved login.

Setup passes the GitHub token to mise and GitHub CLI extension commands through
their environment and uses it for the Orca release lookup, including previews.
The Orca request keeps the token out of logs and redirected requests. Setup does
not write it to application configuration or shell activation files.

Selected AI providers also need existing native account logins for unattended
setup unless authentication is explicitly deferred; see
[AI authentication](../usage/ai-tools.md#authentication).

Unattended backup also requires `WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR`.
Recovery checks that require a human decision stop noninteractive backup; browser
Sync completion requires interactive confirmation.

Do not put credential values in command examples, configuration files, or Git.

## Bitwarden integration

Collection enumeration and key backup item reads use
[`community.general.bitwarden`](https://docs.ansible.com/projects/ansible/latest/collections/community/general/bitwarden_lookup.html).
The tooling image pins the collection in its
[requirements](../../ansible/collections/requirements.yml); the runtime requires at least
10.4.0 for exact item-count validation. `query(...) | first` preserves an empty,
single-item, or multi-item collection as a list. Individual item reads require
`result_count=1`; missing records and lookup failures stop backup.

Lookups execute on the controller and do not inherit task `become` or
`environment`. The thin `neilime.workstation_setup.bitwarden` adapter selects the
managed user's `~/.config/Bitwarden CLI` cache only while calling the community
lookup, then restores the controller environment. It also replaces upstream
exception text with a safe failure: CLI stderr can contain secrets, and Ansible
can display lookup exceptions before task `no_log` takes effect. Authentication
and cache sync run as the managed user in the same directory. The adapter does
not implement record retrieval or suppress failed reads.

Keep CLI operations for login, unlock, server selection, collection metadata,
attachments, and vault writes: the lookup does not implement them. Sync also stays
in managed-user tasks to preserve cache ownership and retries, rather than using
the lookup's controller-side `sync` option. Browser modules use the CLI during
live recovery and write verification because Ansible lookups are controller
plugins and cannot execute inside managed-node modules. Do not replace those
fresh reads with previously captured collection facts.

## Dependency updates

Support the current workstation baseline. When replacing an implementation,
remove its adapters, aliases, transition tasks, tests, and documentation instead
of retaining upgrade paths. Add migration behavior only when explicitly requested.
Keep current backup/restore contracts and data and credential safety checks.

Declare dependency versions and commit pins in configuration or dependency
manifests only. Workstation tool pins belong in
[`ansible/group_vars/all.yml`](../../ansible/group_vars/all.yml). Python
normalizers, shell scripts, role tasks, and templates consume configured values;
they must not contain release literals or fallback versions. Normalization
requires valid Node, mise, PHP, Composer, Orca, and Chezmoi versions after public defaults and private
overrides have been merged. Private examples inherit these pins.

Every added or moved pin needs a working update handler in the same change.
Prefer Dependabot when it supports the complete update; use Renovate for custom
configuration, release filtering, and coordinated updates. Check that each
handler extracts the intended pin from its actual file, and remove obsolete
matches. Tests use configuration or synthetic versions so upgrades do not need
Python edits.

The [Renovate workflow](../../.github/workflows/renovate.yml) runs every Friday
and supports manual dispatch. Its [configuration](../../.github/renovate/renovate-config.json5)
updates Ansible dependencies, Node LTS, mise, Chezmoi, Oh My Zsh, and reviewed
development-tool pins in one grouped pull request. Inline Renovate annotations
cover the Docker Secret Service helper, Orca, Starship, Helm, Dive, gh-act, gh-stack, Composer, Codex,
Copilot, and MCP release versions. AI application and MCP pins live under
`development.ai_tools`; the extraction check in
`e2e-tests/unit/test_ai_tools_pins.py` verifies their Renovate coverage
against the public configuration. GitHub skill annotations use
`datasource=git-refs`, `depName` and `branch`; a separate manager proposes updated
commit digests embedded in Skillshare `source` URLs while keeping setup pinned to full SHAs. The extraction tests
verify these pins in public workstation defaults, along with GitHub-backed mise
tools such as Skillshare. Skillshare generates and updates project skill pins
through its own lockfile commands; Renovate does not natively support that format.
The Docker credential helper pin is
`development.docker.credential_helper_version`; setup verifies the official
release checksum for the selected architecture.
PHP follows stable `php-*` tags from
`php/php-src`; mise owns its runtime and Ubuntu owns its build prerequisites.
Renovate's `ansible-galaxy` manager automatically discovers and updates
the collection pins in [the tooling requirements](../../ansible/collections/requirements.yml).
These pins are shared with workstation bootstrap. Renovate uses Canonical's
stable `meta-release` feed to update the bootstrap guard, tooling image, and Lima
image together, including interim releases. Prereleases are excluded and Ubuntu
updates require review. Dependabot ignores the Ubuntu image to avoid competing
proposals.
Clipboard Indicator follows reviewed GNOME Extensions versions through a custom
Renovate datasource in the same weekly run. Its regular expression extracts the version from
`desktop.clipboard_indicator` in `ansible/group_vars/all.yml`. Reviewers must
download the matching reviewed archive, refresh its SHA-256, and rerun the
[Wayland acceptance checks](adr/adr-0001-workstation-toolchain.md#gnome-clipboard-indicator).
The old digest deliberately prevents installation of an unreviewed new version;
these updates never automerge. GNOME compatibility is checked against the
downloaded metadata before extraction.
The Vitals system monitor follows the same workflow through its own custom
Renovate datasource, extracting the version from `desktop.system_monitor`;
reviewers refresh its SHA-256 and requalify the panel on Wayland. See
[ADR 0003](adr/adr-0003-desktop-system-monitor.md).
GNOME extension digests must match the downloaded reviewed archives; configuration
validation rejects all-zero placeholders before setup changes the workstation.
Dependabot handles GitHub Actions, Docker images, and Python packages; it does not
support Ansible Galaxy collections.

Renovate logs debug details to identify failed file replacements. Branch update
errors fail the workflow; inspect the preceding messages for the dependency and file.

## End-to-end tests

Install cURL, Python 3, Lima, `qemu-img`, and `qemu-system-x86_64` on the host.
The VM uses the selected Ubuntu release, currently 26.04, on amd64 with 2 CPUs,
6 GiB RAM, a 40 GiB disk, and a 4 GiB swap file for source-build memory peaks.
CI assigns 4 CPUs and 8 GiB RAM so source builds
can use the public runner's CPU capacity. Set `E2E_VM_CPUS` and
`E2E_VM_MEMORY_GIB` to positive integers before creating a VM to override its
resources; existing VMs retain their configuration. Readiness checks require a
GNOME Wayland session; Ptyxis is the managed terminal. The fixture installs GNOME Keyring before login
and initializes an encrypted keyring with a random password held in the guest's
private runtime directory. After setup, the fixture requests GNOME logout and waits
for the old login session to close before restarting GDM for automatic login.
It then unlocks the fixture keyring so native recovery tests have the same
credential-store access as an unlocked desktop.

Provide these credentials through the environment without committing them:

- `BITWARDEN_CLIENT_ID`, `BITWARDEN_CLIENT_SECRET`, and `BITWARDEN_PASSWORD` for
  the configured vault.
- `WORKSTATION_MANAGER_GITHUB_TOKEN` for private configuration repository access
  and GHCR pull/push authentication, including `write:packages`.

Tests download the public entrypoint from GitHub and exercise the remote
bootstrap workflow. The default source is the checkout's `origin` and current
branch, falling back to its commit when detached. Set `E2E_REPOSITORY_URL` and
`E2E_REPOSITORY_REF` to test a different repository or ref. The selected ref must
already contain the changes on GitHub; local uncommitted changes are not deployed.
In CI, the bootstrap uses the exact checked-out commit from the workflow
repository. Pull request runs use GitHub's merge commit so the installed code
includes the same base-branch changes as the assertions. The entrypoint explicitly
fetches pinned commits so PR commits outside normal branches and tags are available
to `ansible-pull`.

```sh
make e2e-up
make e2e-test
make e2e-down
```

Use `make e2e-prepare` to start the VM and prepare the Docker tooling image in
parallel. CI uses this target and saves Lima's public image download cache before
the authenticated test phases, so a later failure does not discard downloaded
images. The cache key includes the Lima version, runner platform, and VM template.
Guest disks and authenticated workstation state are never cached.

Run `make e2e-down` after failures too. It asks the browser devices created by
this test run to leave their Sync chains, then deletes the VM. A stopped VM is
resumed for this cleanup. Failed browser teardown retains the local VM and recorded
identities for diagnosis; GitHub-hosted runners still expire after their job.
The next successful setup in a VM with the same device name removes abandoned
registrations through [same-name device cleanup](../usage/browser.md).
VM names are not included in workstation cleanup defaults. This also works with
custom `VM_NAME` values, using the name reported by Brave.
Use separate chains for concurrent test runs so their shared device names cannot
cause one run to remove another run's registration.
Use `make e2e-reset` before reusing a VM. `VM_NAME` selects a different instance.
Browser setup requires an absent Brave profile tree and records each initialized
test device's identity. Teardown checks those exact identities and ignores profiles
introduced after capture; preexisting workstation profiles cannot be claimed as
test devices. Each device must complete a fresh Sync download and have a healthy
Device Info tracker before its leave request. Teardown reads native status and
entity-count events through the page's existing WebUI callbacks, without importing
browser modules. Each readiness observation requests fresh status and waits for
its asynchronous counts; cached idle status cannot authorize leaving during a
busy cycle. The native smoke test also checks readiness and removal with
those imports blocked. If its diagnostic page is replaced before removal,
teardown restores that automation tab within the same timeout and requires fresh
Sync evidence. Timeout reports retain the last observed check names even when
the page loses its state; browser data and recovery words are never reported.
Teardown prompts pending commits and requires a successful
server response for that exact device's deletion;
Brave's local leave acknowledgement alone does not prove removal.
Deletion requests are matched using Chromium's native
[client tag hash](https://github.com/chromium/chromium/blob/main/components/sync/base/client_tag_hash.cc),
derived from the captured device GUID. Successful commit responses are matched
by request position, as required by the Sync protocol; response IDs may change
or be omitted. This keeps teardown independent of node queries
across unrelated browser data types. The matched response emits a boolean through
a target-scoped DevTools binding. The automation connection retains that
acknowledgement if native leave discards the diagnostic page's JavaScript state.
The Runtime domain stays enabled to reinstall the binding after navigation.
After the leave callback returns, teardown waits up to 30 seconds for the binding
event before removing its observer; the two pages can deliver their replies independently.
Both the native leave callback and server acknowledgement must succeed; page loss
cannot stand in for either confirmation or hide a failed leave request.
Missing acknowledgements report incomplete commit-request, tombstone, and response
stages when the observer is still available, without exposing device identities
or protocol payloads.
The VM downloads Ubuntu packages over HTTPS with bounded retries. On startup
failure, it prints Lima logs and attempts a bounded guest diagnostic command
before teardown. Inspect the `Prepare e2e VM and tooling` job output for provisioning,
desktop, and networking errors.
Setup failures also print bounded guest memory, swap, login-session, display-manager,
and OOM diagnostics before teardown. These exclude action journals and process
environments, which can contain credentials.

The suite runs three phases, with assertions after each:

1. **Backup:** create project fixtures and an isolated, published Chezmoi source,
   restore SSH/GPG keys from the configured Bitwarden collections, then run
   backup. The temporary override keeps those collections and disables managed
   browser profiles. Recovery checks must pass without prompts or skipped sources.
2. **Setup:** remove the temporary recovery fixture, run setup with the generated
   archive and an isolated private override, and verify the installed workstation
   and restored files. The override defers provider sign-in with
   `development.ai_tools.authenticate: false`.
3. **Cleanup:** run cleanup and check its report and preservation behavior.

The backup fixture requires a fresh VM without Chezmoi or Brave profile state.
The suite uses the configured Bitwarden collections and private configuration;
it is not an offline simulation. Setup requires verified live Brave Sync recovery
for configured profiles. The separate native browser smoke test uses disposable
profiles with a disabled Sync endpoint.
AI tooling is covered by [unit and isolated integration tests](ai-tools.md#testing).
The VM suite has no dedicated AI assertions; account sign-in remains part of
normal workstation setup.
For focused investigation, `make e2e-backup`, `make e2e-setup`, and
`make e2e-cleanup` run their action without the assertion phase; setup expects the
backup fixture archive.

Set `REPORTS_DIR=.reports` to collect syntax and test reports. The setup desktop
screenshot defaults to `.reports/screenshots/e2e-setup-desktop.png`; use
`SCREENSHOTS_DIR` to change its directory. CI publishes reports and the screenshot.
The suite logs elapsed time and exit status for each action, assertion phase, and
desktop capture step. Set `E2E_PROFILE_TASKS=1` to also collect Ansible task timings;
CI enables this automatically and appends phase durations and exit codes to the
job summary, including failed phases. Assertion output lists the ten slowest tests.
Profiling temporarily updates the disposable VM's Ansible configuration and
restores it when the suite exits.
After failed setup, the suite reopens seeded browser profiles in the VM to collect
redacted Sync initialization checks and numeric request metrics. It also verifies
an independent disposable chain and removes that control device afterward. These
diagnostics preserve the original setup failure and the saved recovery chains.
Each assertion phase uses an SSH control socket inside its test container. Lima's
configuration stays mounted read-only, and a fresh connection sees group changes
made during setup.

The Lima workspace mount uses QEMU 9p without caching; this keeps Ubuntu AppArmor
enabled and makes the guest see host edits in the read-only repository mount. The toolchain ADR records the
[delivery decisions](adr/adr-0001-workstation-toolchain.md#operating-system-and-delivery-tools).
