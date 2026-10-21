# ADR 0004 Documentation boundaries and decision history

- Status: Accepted
- Date: 2026-10-21
- Scope: workstation-manager and workstation-config

## Context

Users need short setup and everyday-use instructions. Contributors need detailed
contracts, validation steps, and the reasons for architectural choices. Mixing
these audiences in root readmes makes common tasks harder to find. Mixing old
and current procedures makes supported behavior unclear.

## Decision

Keep root readmes focused on end users and link to detailed guides in `docs/`.
Use `docs/usage/` for user procedures, `docs/development/` for contributors, and
`docs/README.md` as the index. Each topic has one canonical guide.

Guides describe implemented behavior and change with the code. Remove obsolete
workflows, aliases, examples, duplicate explanations, and compatibility stubs.
Keep prose concise and state prerequisites, actions, results, and relevant limits.

Keep significant decision history and dated evidence in ADRs. Preserve accepted
records and link superseding decisions. Historical evidence remains historical;
current acceptance requires current validation.

Enforce these rules through repository `AGENTS.md` files, contributor guides, and
the Chezmoi-managed shared engineering and testing instructions.

## Alternatives

- A comprehensive root readme mixes end user and contributor tasks.
- Rolling migration notes in active guides leave obsolete procedures beside
  supported ones.
- Rewriting accepted ADRs to match current code loses the rationale for changes.

## Consequences

Contributors maintain guide links and indices when moving topics. Documentation
review checks source claims, Markdown, and local links. Documentation-only changes
do not require workstation actions. Current guide maintenance and preserved
decision history have separate responsibilities.
