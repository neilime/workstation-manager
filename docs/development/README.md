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
- `make lint` builds and runs the separate repository linter image.
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

CI runs lint independently. Ansible checks, unit/integration tests, and end-to-end tests run
in parallel once the tooling image is available. Each publishes its own result.
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

Running `./workstation.sh` from a local checkout defaults to that checkout and
its current branch or detached commit. Direct local runs execute Ansible from
the local working tree, including uncommitted changes. The piped `curl ... | sh`
bootstrap still uses the published GitHub repository unless you override
`REPOSITORY_URL`.

Keep the public entrypoint self-contained for piped execution. Its `run_action`
dispatcher shares dependency preparation and authentication across commands;
`run_ansible_pull` selects the local or remote controller command. Both direct
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
cover Orca, Starship, Helm, Dive, gh-act, gh-stack, Composer, Codex, and Copilot
release versions. PHP follows stable `php-*` tags from
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
Dependabot handles GitHub Actions, Docker images, and Python packages; it does not
support Ansible Galaxy collections.

Renovate logs debug details to identify failed file replacements. Branch update
errors fail the workflow; inspect the preceding messages for the dependency and file.

## End-to-end tests

Install cURL, Python 3, Lima, `qemu-img`, and `qemu-system-x86_64` on the host.
The VM uses the selected Ubuntu release, currently 26.04, on amd64 with 2 CPUs,
6 GiB RAM, and a 40 GiB disk. Readiness checks require a GNOME Wayland session;
Ptyxis is the managed terminal. The fixture installs GNOME Keyring before login
and initializes an encrypted keyring with a random password held in the guest's
private runtime directory. It unlocks that keyring after desktop restarts so
native recovery tests have the same credential-store access as an unlocked desktop.

Provide these credentials through the environment without committing them:

- `BITWARDEN_CLIENT_ID`, `BITWARDEN_CLIENT_SECRET`, and `BITWARDEN_PASSWORD` for
  the configured vault.
- `WORKSTATION_MANAGER_GITHUB_TOKEN` for private configuration repository access.

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

Run `make e2e-down` after failures too; it deletes the VM. Use `make e2e-reset`
before reusing a VM. `VM_NAME` selects a different instance.
The VM downloads Ubuntu packages over HTTPS with bounded retries. On startup
failure, it prints Lima logs and attempts a bounded guest diagnostic command
before CI deletes the VM. Inspect the `Start e2e VM` job output for provisioning,
desktop, and networking errors.

The suite runs three phases, with assertions after each:

1. **Backup:** create project fixtures and an isolated, published Chezmoi source,
   restore SSH/GPG keys from the configured Bitwarden collections, then run
   backup. The temporary override keeps those collections and disables managed
   browser profiles. Recovery checks must pass without prompts or skipped sources.
2. **Setup:** remove the temporary recovery fixture, run setup with the generated
   archive, and verify the installed workstation and restored files.
3. **Cleanup:** run cleanup and check its report and preservation behavior.

The backup fixture requires a fresh VM without Chezmoi or Brave profile state.
The suite uses the configured Bitwarden collections and private configuration;
it is not an offline simulation. Setup requires verified live Brave Sync recovery
for configured profiles. The separate native browser smoke test uses disposable
profiles with a disabled Sync endpoint.
For focused investigation, `make e2e-backup`, `make e2e-setup`, and
`make e2e-cleanup` run their action without the assertion phase; setup expects the
backup fixture archive.

Set `REPORTS_DIR=.reports` to collect syntax and test reports. The setup desktop
screenshot defaults to `.reports/screenshots/e2e-setup-desktop.png`; use
`SCREENSHOTS_DIR` to change its directory. CI publishes reports and the screenshot.
The suite logs elapsed time and exit status for each action, assertion phase, and
desktop capture step. Set `E2E_PROFILE_TASKS=1` to also collect Ansible task timings;
CI enables this automatically. Profiling temporarily updates the disposable
VM's Ansible configuration and restores it when the suite exits.
Each assertion phase uses an SSH control socket inside its test container. Lima's
configuration stays mounted read-only, and a fresh connection sees group changes
made during setup.

The Lima workspace mount uses QEMU 9p without caching; this keeps Ubuntu AppArmor
enabled and makes the guest see host edits in the read-only repository mount. The toolchain ADR records the
[delivery decisions](adr/adr-0001-workstation-toolchain.md#operating-system-and-delivery-tools).
