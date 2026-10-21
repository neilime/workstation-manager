# Documentation rules

Current code and maintained configuration define supported behavior.
[AGENTS.md](../../AGENTS.md) makes this contract part of every change.

## Audience and ownership

- Keep the root README limited to purpose, end-user prerequisites, everyday
  commands, and links into `docs/`.
- Put user procedures in `docs/usage/` and contributor instructions in
  `docs/development/`. Maintain [the documentation index](../README.md).
- Give each topic one canonical guide. Collection and role READMEs state their
  responsibility and link to it.
- Write concise, direct instructions: prerequisites, action, result, and any
  limitation that affects the user's decision. Keep implementation details in
  developer guides.

## Current behavior and history

Usage and development guides describe implemented behavior. Remove obsolete
options, workflows, aliases, examples, duplicate explanations, and migration
narratives. Keep version pins in their maintained configuration and link to them.

Preserve significant decision history in [ADRs](adr/README.md): context,
alternatives, decisions, consequences, and dated evidence. Accepted records may
describe former choices. Add a linked superseding ADR when a decision changes;
do not rewrite the accepted record to present old evidence as current validation.

## Review each change

1. Verify affected commands, paths, defaults, ownership, and guarantees against
   the entrypoint, normalizers, owning role, or helper.
2. Update guides and examples with implementation changes. Update every link,
   index, and anchor when moving or deleting a topic; leave no compatibility stub.
3. Retain tests for current behavior. Remove retired scenarios and helpers;
   use synthetic inputs or maintained configuration instead of release snapshots.
4. Preserve tests for reruns, previews, permissions, credentials, recovery, and
   unmanaged data. Existing application state remains a valid safety fixture.
5. Run applicable lint, local link checks, and affected tests. Documentation-only
   changes do not require workstation actions.
6. Report checks actually run and remaining limits. Keep acceptance requirements
   distinct from completed validation.

Shared personal instructions are maintained in the companion repository's
`home/dot_agents/` sources and installed by Chezmoi. Update those sources when
the same rule applies across repositories.
