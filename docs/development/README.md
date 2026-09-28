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

See [browser adapters](browser-adapters.md) for that extension contract and
[AGENTS.md](../../AGENTS.md) for repository-wide contribution rules.

## Local checks

```sh
make setup
make lint
make check-ansible
make test
```

- `make setup` builds the tooling image if it is absent. Rebuild it after changing
  its Dockerfile or dependencies.
- `make lint` builds and runs the separate repository linter image.
- `make check-ansible` checks all top-level playbooks against the local inventory.
- `make test` runs host-tool unit tests and first-party collection
  `ansible-test sanity` and `ansible-test units` checks with Python 3.12.

Ansible checks install collection dependencies into `ansible/vendor-collections/`.
Do not edit that directory or generated reports and test output.

Use `make tool-shell` for an interactive tooling container. `make lint-fix`
rewrites files; `make ci` runs it before syntax and test checks. Review its diff.
Documentation-only changes need applicable lint and local link checks.

## Dependency updates

The [Renovate workflow](../../.github/workflows/renovate.yml) runs every Friday
and supports manual dispatch. Its [configuration](../../.github/renovate/renovate-config.json5)
updates Ansible dependencies, PHP and Chezmoi pins, and the Helm major track in
one grouped pull request. Helm minor and patch releases stay within the configured
major track. Dependabot handles GitHub Actions, Docker images, and Python packages.

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

```sh
make e2e-up
make e2e-test
make e2e-down
```

Run `make e2e-down` after failures too; it deletes the VM. Use `make e2e-reset`
before reusing a VM. `VM_NAME` selects a different instance.

The suite runs three phases, with assertions after each:

1. **Backup:** create project fixtures and an isolated, published Chezmoi source,
   then run backup. The temporary override keeps the configured SSH/GPG
   collections and disables managed browser profiles.
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
`SCREENSHOTS_DIR` to change its directory. CI runs static checks before the end-to-end
suite and publishes reports and the screenshot.
