# Development

Use Git, Make, and Docker Engine. Run workstation-changing tests in the Lima VM.
Read [AGENTS.md](../../AGENTS.md) and apply the
[documentation review](documentation.md#review-each-change) before completing
each change. Keep guides current and decision history in ADRs; regenerate
GitHub Actions and workflow readmes from their sources.

## Repository layout

| Path                                                                              | Responsibility                                                    |
| --------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| [`workstation.sh`](../../workstation.sh)                                          | Public setup, backup, cleanup, and help commands.                 |
| [`ansible/group_vars/all.yml`](../../ansible/group_vars/all.yml)                  | Public defaults and workstation tool pins.                        |
| [`ansible/tasks/`](../../ansible/tasks/)                                          | Configuration resolution and orchestration.                       |
| [First-party collections](../../ansible/collections/ansible_collections/neilime/) | Setup, backup, restore, cleanup, and shared state.                |
| [`docker/tooling/`](../../docker/tooling/)                                        | Ansible and Python validation environment.                        |
| [`tests/`](../../tests/)                                                          | Local unit tests, isolated integration tests, and shared helpers. |
| [`e2e-tests/`](../../e2e-tests/)                                                  | Lima workflows and VM assertions.                                 |
| [`ci/`](../../ci/)                                                                | Tooling launchers and report helpers.                             |

Keep orchestration in roles and playbooks, reusable Python in
`plugins/module_utils/`, and thin Ansible adapters in `plugins/modules/` and
`plugins/filter/`. Roles consume `workstation_manager_resolved`.

The owning collections are `workstation_setup`, `workstation_backup`,
`workstation_restore`, and `workstation_cleanup`. Put shared state serialization
and baseline markers in `workstation_state`. Configuration changes update defaults,
normalizers, the private override example, tests, and the relevant guide together.

Backup source roles use the shared
[recovery decision contract](automation.md#recovery-decisions).

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
`tests/unit/` and `tests/integration/`; `make test-collections` selects collection
sanity and unit checks. These convenience targets overlap `make test`; CI runs
`make check-collections` and `make test` once each.
VM tests use the separate [end-to-end workflow](e2e-tests.md).

### Coverage ownership

| Location                 | Responsibility                                                                                                                             |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Collection `tests/unit/` | Parsing, normalization, planning, and recovery decisions in the owning Python helpers. Temporary files and local Git fixtures are allowed. |
| `tests/unit/`            | Bootstrap and CI helpers with isolated command stand-ins; public configuration and dependency-update contracts.                            |
| `tests/integration/`     | Real Ansible wiring, terminal interaction, subprocess protocols, and process lifecycle. No live credentials or workstation changes.        |
| `e2e-tests/`             | Installed behavior, desktop sessions, and recovery against live services in the Lima VM.                                                   |

Directory selection defines the local layers; no marker is needed to keep a new
integration test out of `make test-unit`. Plain `pytest` collects both local
layers and collection units, excluding VM assertions. The Make targets collect
only their selected directories and report the slowest tests.

Cover exhaustive input combinations in unit tests. Integration tests should
prove representative wiring, reruns, previews, and failure propagation without
repeating the same input matrix. Preserve distinct archive-safety, recovery,
permissions, credential-redaction, and user-data checks. VM assertions verify
the resulting installation rather than repeating normalization checks.

Reuse `tests/support/ansible_test_helpers.py` for bounded playbook runs and isolated
controller state, and the adjacent entrypoint helpers for terminal fixtures.
When replacing external operations, preserve role imports and `tasks_from`
entrypoints so tests exercise Ansible's role-relative task lookup.
Keep mutable homes and process state local to each test; share setup only when
the fixture is immutable. Use synthetic inputs and maintained configuration
instead of release snapshots or assertions about source layout.

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
VM jobs after resolving the tooling image. Images are reused by a fingerprint of
the Dockerfile, its copied inputs, ignore files, Ubuntu base digest, architecture,
and UTC calendar week. A miss builds the image; registry and authentication
failures stop resolution. Each job consumes the selected immutable digest and
mounts the current checkout. The weekly refresh also invalidates package-install
build layers. Input-addressed registry tags are retained and share image layers.
The Ansible job caches only sanity virtual environments, keyed by runner
architecture and tooling filesystem layers.

The Ansible job uses Hoverkraft's `ci-github-iac/actions/ansible/test` for native
syntax and collection sanity checks, JUnit/SARIF reports, annotations, PR comments
and artifacts. Local `make check-ansible` and `make check-collections` remain
available. Unit/integration and VM scenarios run in their existing jobs.

## Detailed guides

- [Documentation rules](documentation.md): audience, current behavior, ADR history, and review checklist.
- [Automation](automation.md): source selection, unattended credentials, and Bitwarden integration.
- [Project skills](project-skills.md): declarations, installation, and updates.
- [Dependency updates](dependencies.md): pin ownership and update handlers.
- [End-to-end tests](e2e-tests.md): VM isolation, credentials, phases, teardown, and reports.
- [Browser adapters](browser-adapters.md) and [AI adapters](ai-tools.md): extension contracts.
- [ADRs](adr/README.md): decisions, rationale, and historical evidence.
