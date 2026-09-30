# Repository instructions

These instructions apply to the entire `workstation-manager` repository. Follow
more specific `AGENTS.md` files when working in their directories.

## Understand the existing codebase

- Read `README.md`, the relevant collection readme, and nearby implementation and
  tests before changing behavior. Follow established patterns unless they are
  obsolete, unsafe, or unnecessarily complex.
- Keep changes focused and preserve existing staged and unstaged user changes.
- This project manages Ubuntu workstations through `workstation.sh` and Ansible.
  The public interface is `setup`, `backup`, `cleanup`, and `help`, with
  `--dry-run` for previews. Archive restoration is part of setup.
- Keep `Makefile` commands for development and validation. Preserve the public
  bootstrap workflow that downloads the entrypoint and pipes it to `sh`.

## Architecture and configuration

- First-party collections live under
  `ansible/collections/ansible_collections/neilime/`: `workstation_setup`,
  `workstation_backup`, `workstation_restore`, `workstation_cleanup`, and
  `workstation_state`. Put behavior in the collection that owns it and shared
  managed-state logic in `workstation_state`.
- Keep playbooks and roles focused on orchestration. Put reusable Python logic in
  `plugins/module_utils/`, with thin adapters in `plugins/modules/` and
  `plugins/filter/`.
- When a role grows multiple files, templates, or task entries for one feature,
  group that feature into a dedicated task file and matching scoped subdirectories
  under the role's `files/` and `templates/` trees instead of adding more flat
  top-level assets.
- Public defaults belong in `ansible/group_vars/all.yml`; configuration validation
  and normalization belong in the setup collection's `desired_state*` helpers.
  Roles should consume `workstation_manager_resolved` where applicable.
- When configuration changes, update defaults, normalizers, the example in
  `ansible/vars/private.override.example.yml`, affected tests, and documentation
  together. Keep duplicated defaults consistent.
- Private non-secret overrides and Chezmoi dotfiles belong to the companion
  `workstation-config` repository. Actual secrets belong in Bitwarden.
- Follow `docs/development/browser-adapters.md` for browser extensions to the architecture;
  keep vendor details inside the adapter and preserve its setup, backup, and
  inspection entrypoints.

## Engineering best practices

- Use simple, cohesive functions and modules with clear responsibilities. Reuse
  existing helpers, avoid unnecessary dependencies and abstractions, and fix root
  causes rather than hiding failures.
- Validate external input at boundaries and report actionable errors. Never
  silently swallow unexpected failures or report incomplete work as successful.
- Keep Ansible tasks idempotent. Use fully qualified collection names, descriptive
  task names, namespaced variables, explicit ownership, and quoted file modes.
  Prefer dedicated modules; use `command` with `argv` when a command is needed,
  and use `shell` only when shell features are necessary.
- Report changes accurately with `changed_when` or module results, and preserve
  check-mode support. Read-only probes must not report changes. Guard mutations
  during `--dry-run`; preserve the documented authentication and cache behavior.
- Keep `workstation.sh` POSIX-compatible: retain its `sh` shebang and `set -eu`,
  quote expansions, and avoid Bash-only syntax. Preserve `/dev/tty` prompting for
  piped execution and cleanup traps for temporary files and credentials. Follow
  the declared shell in development and test scripts.
- Follow existing Python type hints, docstrings, import structure, and validation
  patterns. Custom Ansible modules need argument validation, appropriate
  check-mode handling, and the documentation required by `ansible-test sanity`.
- Follow the repository's lint configuration in `.github/linters/` and
  `biome.json`. Do not weaken checks to make a change pass; keep any justified
  suppression narrow and explain why it is necessary.

## Keep technologies current

- Always use current, stable, supported technologies for new work. When adding or
  upgrading dependencies, verify the latest stable release, support status, and
  migration guidance against official upstream sources; do not rely on memory.
- Use the latest stable version compatible with the supported Ubuntu, Python,
  and Ansible environment. If compatibility prevents an upgrade, document the
  concrete blocker and follow-up instead of silently retaining an obsolete choice.
  Avoid deprecated APIs and unsupported releases.
- Keep upgrades reproducible: follow the repository's version constraints and
  GitHub Actions commit-SHA pins. Using current technology does not mean replacing
  controlled versions with unbounded `latest` references.
- Coordinate runtime upgrades across `docker/tooling/Dockerfile`,
  `docker/tooling/requirements.txt`, `e2e-tests/requirements.txt`, collection
  metadata, `Makefile`, and CI wherever affected. The test Python version must
  agree with the tooling image.
- Maintain the existing Renovate and Dependabot coverage when adding or moving
  dependencies. Update affected version references, fixtures, and documentation
  together, then run the relevant compatibility checks.

## Remove dead and unnecessary code

- With every change, actively look for unused imports, variables, helpers, roles,
  obsolete configuration, redundant branches, duplicate logic, stale comments,
  and outdated tests or documentation in the affected area. Remove verified dead
  code and simplify needless complexity as part of the change.
- Check callers, tests, templates, dynamic Ansible includes, configuration-driven
  role selection, and documented interfaces before declaring something unused.
  A missing direct Python reference alone is insufficient evidence.
- Remove obsolete references and tests when removing behavior; retain regression
  coverage for supported behavior. Do not add speculative abstractions or leave
  commented-out implementations behind.
- Keep cleanup related and reviewable. Report unrelated cleanup opportunities
  separately. Never treat user data, private overrides, backup archives, or
  installed workstation state as disposable code.
- Do not hand-edit vendored collections or generated artifacts, including
  `ansible/vendor-collections/`, `.reports/`, caches, and collection `tests/output/`.

## Protect workstation data and secrets

- Use the resolved target user and the existing privilege-escalation conventions;
  do not assume the process user or its home is the managed account.
- Keep credentials, SSH/GPG private keys, browser recovery words, and sensitive
  attachment data out of logs, reports, fixtures, and committed files. Use
  `no_log` and restricted permissions for sensitive Ansible operations.
- Preserve backup drift checks and verification after synchronization. A backup
  must fail when required recovery checks or reconciliation remain incomplete
  unless the user explicitly skips that recovery source. Record skipped coverage
  in the manifest and final output; never report it as verified. Failed operations
  and verification of approved changes must still fail. Non-interactive runs must
  not guess synchronization decisions or skip checks automatically.
- Preserve archive validation before extraction, including path traversal and
  link protections. Cleanup must preserve browser profiles and unmanaged user
  data according to the documented cleanup contract.
- Exercise workstation-changing commands in the Lima test VM rather than on the
  development host. End-to-end tests require credentials and can interact with external
  services; follow the existing fixture isolation and teardown workflow.

## Documentation

- Keep `README.md` focused on the project purpose, prerequisites, and everyday
  end user commands. Put detailed procedures and contracts in `docs/` and link
  to them from the readme.
- Organize guides by audience: `docs/usage/` for workstation users and
  `docs/development/` for contributors. Maintain `docs/README.md` as the index.
  Add a page only when the topic needs its own useful guide.
- Give each topic one canonical explanation. Collection and role readmes should
  state their purpose and link to the relevant guide, not duplicate user workflows.
- Document current, implemented behavior only. Remove obsolete options, deleted
  features, migration history, stale examples, and descriptions of dead code.
  Do not retain old documentation as compatibility stubs after moving a guide.
- Write directly: state prerequisites, show the command or configuration, and
  explain the result. Include limitations only when they affect a user's action
  or expectations. Avoid filler, marketing language, repetitive disclaimers,
  speculative features, and implementation details in user procedures.
- Verify commands, defaults, configuration names, and claimed behavior against
  the implementation. Distinguish automatic work from required manual steps;
  never claim a dry run, backup, restore, or sync guarantees more than it checks.
- Keep examples usable, mark placeholders clearly, and never include real secrets
  or personal vault records. Link to source configuration instead of copying
  exhaustive lists of defaults into prose.
- When moving or removing a guide, update every reference, including collection
  readmes and these instructions. Check Markdown formatting and local links.
  Documentation-only changes do not require executing workstation actions.

## Validation and completion

- Use the existing Docker-based development tools. The normal validation sequence
  for code changes is:

  ```sh
  make setup
  make lint
  make check-ansible
  make test
  ```

- `make test` runs host-tool unit tests plus first-party collection sanity and
  unit checks. Add meaningful regression tests for changed behavior in the
  relevant collection's `tests/unit/` or `e2e-tests/unit/`.
- For changes to installation, backup, restoration, or cleanup behavior, run the
  relevant VM assertions in `e2e-tests/`. The complete flow is `make e2e-up`,
  `make e2e-test`, then `make e2e-down`; it tests backup, setup, and cleanup in
  phases. Ensure the configured test repository and ref contain the intended
  changes, since the VM exercises the remote bootstrap workflow.
- `make lint-fix` rewrites files, and `make ci` invokes it. Review resulting diffs
  and preserve unrelated work. Documentation-only edits need applicable lint and
  link checks, not workstation execution or new behavior tests.
- Update user-facing and collection documentation when behavior or configuration
  changes. Report what changed, which checks actually ran, and any remaining
  limitations or blockers. Never claim an unrun check passed.
