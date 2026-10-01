# Development

Use Git, Make, and Docker Engine for repository work. Run workstation-changing
tests in the Lima VM.

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
- `workstation_cleanup`: cleanup, managed-state comparison, and drift reports.
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
[AGENTS.md](../../AGENTS.md) for repository-wide contribution rules.

## Local checks

```sh
make setup
make lint
make check-ansible
make test
```

- `make setup` builds the tooling image, reusing Docker layers when its inputs
  are unchanged. CI pulls the image published by its build job.
- `make lint` builds and runs the separate repository linter image.
- `make check-ansible` checks all top-level playbooks against the local inventory.
- `make test` runs host-tool tests and first-party collection `ansible-test sanity`
  and `ansible-test units` checks with Python 3.12.
- `make test-host` runs the isolated host tests with two pytest workers. Set
  `HOST_TEST_WORKERS=1` for sequential execution.
- `make test-collections` runs the collection checks separately.

The tooling image includes Python dependencies for host and end-to-end assertions and
Ansible collections from [its versioned requirements](../../docker/tooling/requirements.yml).
Syntax checks and tests use these installed dependencies without downloading them
again. The image build checks that the tooling and workstation manifests declare
the same collection names. Run `make setup` after changing either manifest.

CI runs lint independently. Ansible checks, host tests, and end-to-end tests run
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
rewrites files; `make ci` runs it before syntax and test checks. Review its diff.
Documentation-only changes need applicable lint and local link checks.

Running `./workstation.sh` from a local checkout defaults to that checkout and
its current branch or detached commit. Direct local runs execute Ansible from
the local working tree, including uncommitted changes. The piped `curl ... | sh`
bootstrap still uses the published GitHub repository unless you override
`REPOSITORY_URL`.

Interactive runs capture Ansible output through `script` while keeping prompts
on a terminal. When the entrypoint is piped into `sh`, this runner loads
`workstation.sh` from the configured repository and ref because the running
script has no source file on disk. Local runs reuse their entrypoint source.
The runner validates shell syntax before execution and removes its temporary
source and credential files afterward.

## Dependency updates

The [Renovate workflow](../../.github/workflows/renovate.yml) runs every Friday
and supports manual dispatch. Its [configuration](../../.github/renovate/renovate-config.json5)
updates Ansible dependencies, PHP and Chezmoi pins, and the Helm major track in
one grouped pull request. Helm minor and patch releases stay within the configured
major track. Renovate's `ansible-galaxy` manager automatically discovers and updates
the collection pins in [the tooling requirements](../../docker/tooling/requirements.yml).
These pins target the tooling image's Ansible runtime; workstation bootstrap
resolves its own [collection requirements](../../ansible/collections/requirements.yml).
Dependabot handles GitHub Actions, Docker images, and Python packages; it does not
support Ansible Galaxy collections.

Renovate logs debug details to identify failed file replacements. Branch update
errors fail the workflow; inspect the preceding messages for the dependency and file.

## End-to-end tests

Install cURL, Python 3, Lima, `qemu-img`, and `qemu-system-x86_64` on the host.
The VM configuration uses Ubuntu 24.04 amd64 with 2 CPUs, 6 GiB RAM, and a 40 GiB
disk.

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
it is not an offline simulation. It does not verify live Brave Sync completion.
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
