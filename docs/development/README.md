# Development

Use Git, Make, and Docker Engine. Run workstation-changing tests in the Lima VM.
Read [AGENTS.md](../../AGENTS.md) and the
[documentation rules](documentation.md) before editing.

## Repository layout

| Path                                                                              | Responsibility                                          |
| --------------------------------------------------------------------------------- | ------------------------------------------------------- |
| [`workstation.sh`](../../workstation.sh)                                          | Public setup, backup, cleanup, and help commands.       |
| [`ansible/group_vars/all.yml`](../../ansible/group_vars/all.yml)                  | Public defaults and workstation tool pins.              |
| [`ansible/tasks/`](../../ansible/tasks/)                                          | Configuration resolution and orchestration.             |
| [First-party collections](../../ansible/collections/ansible_collections/neilime/) | Setup, backup, restore, cleanup, and shared state.      |
| [`docker/tooling/`](../../docker/tooling/)                                        | Ansible and Python validation environment.              |
| [`e2e-tests/`](../../e2e-tests/)                                                  | Isolated host tests, Lima workflows, and VM assertions. |
| [`ci/`](../../ci/)                                                                | Tooling launchers and report helpers.                   |

Keep orchestration in roles and playbooks, reusable Python in
`plugins/module_utils/`, and thin Ansible adapters in `plugins/modules/` and
`plugins/filter/`. Roles consume `workstation_manager_resolved`.

The owning collections are `workstation_setup`, `workstation_backup`,
`workstation_restore`, and `workstation_cleanup`. Put shared state serialization
and baseline markers in `workstation_state`. Configuration changes update defaults,
normalizers, the private override example, tests, and the relevant guide together.

Backup source roles use the shared
[recovery decision contract](../../ansible/collections/ansible_collections/neilime/workstation_backup/roles/recovery_decision/README.md).
Source inspection, approved mutations, and verification stay with the owning
role. Start each decision with an empty result and verify the approved action.

## Local checks

```sh
make setup
make lint
make check-ansible
make check-collections
make test
```

| Command                  | Checks                                                              |
| ------------------------ | ------------------------------------------------------------------- |
| `make setup`             | Builds the tooling image; CI pulls its published image.             |
| `make lint`              | Static checks in the separate linter image, including Ansible Lint. |
| `make check-ansible`     | Top-level playbooks against the local inventory.                    |
| `make check-collections` | First-party `ansible-test sanity` checks.                           |
| `make test-unit`         | Fast host and collection unit tests.                                |
| `make test-integration`  | Isolated Ansible and terminal tests.                                |
| `make test`              | Unit and integration suites.                                        |

Select tests with `TEST_ARGS="-k desired_state"`. Integration tests use two
workers; set `HOST_TEST_WORKERS=1` for sequential runs. `make test-host` selects
`e2e-tests/unit/`; `make test-collections` selects collection sanity and unit checks.
VM tests use the separate [end-to-end workflow](e2e-tests.md).

Use unit tests for parsing and normalization, isolated integration tests for
Ansible wiring and check mode, and VM assertions for installed behavior.
Reuse `e2e-tests/unit/ansible_test_helpers.py`. Use synthetic inputs and maintained
configuration; preserve archive-safety, recovery, permissions, credential-redaction,
and user-data checks.

`make setup` consumes the [controller requirements](../../ansible/requirements.txt),
[collection manifest](../../ansible/collections/requirements.yml), and tooling/test
requirements. Rebuild after changing them. Tests use the image's Python and
installed dependencies. Tooling containers run with the host UID/GID and a
temporary container home; `make tool-shell` opens an interactive session.

`make lint-fix` rewrites files. `make ci` runs it before syntax, sanity, and tests;
review its diff. Documentation-only changes require applicable lint and local
link checks. Do not edit generated caches, reports, vendored collections, or
test output.

CI runs the linter independently and starts syntax/sanity, unit/integration, and
VM jobs after the tooling image is available. The Ansible job caches only sanity
virtual environments, keyed by runner architecture and tooling filesystem layers.

## Detailed guides

- [Documentation rules](documentation.md): audience, current behavior, ADR history, and review checklist.
- [Automation](automation.md): source selection, unattended credentials, and Bitwarden integration.
- [Project skills](project-skills.md): declarations, installation, and updates.
- [Dependency updates](dependencies.md): pin ownership and update handlers.
- [End-to-end tests](e2e-tests.md): VM isolation, credentials, phases, teardown, and reports.
- [Browser adapters](browser-adapters.md) and [AI adapters](ai-tools.md): extension contracts.
- [ADRs](adr/README.md): decisions, rationale, and historical evidence.
