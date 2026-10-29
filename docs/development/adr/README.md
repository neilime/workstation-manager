# Architecture decision records

Architecture decision records (ADRs) capture a significant decision, the context
that forced it, and the consequences the project accepts. Read them to understand
why a part of the system works the way it does before changing that behavior.

ADRs preserve decision history. They can describe former designs and dated
validation evidence; current commands and supported behavior belong in usage and
development guides. Do not use an old result as evidence of current validation.

Add an ADR when a decision changes an architectural contract, a public interface,
or a cross-collection convention and a future contributor would otherwise have to
reconstruct the reasoning. Keep routine or reversible choices in the owning
collection's code and guides instead.

## Process

- Copy the heading structure of an existing record. Number files sequentially as
  `adr-NNNN-short-title.md`.
- Start a record as `Proposed`. Change it to `Accepted` once the decision is
  adopted, or `Superseded by [NNNN](adr-NNNN-...)` when a later ADR replaces it. Do
  not rewrite history in an accepted record; add a new ADR instead.
- State the decision and its consequences directly. Link to the implementation
  and guides rather than duplicating them.
- Keep a decision's context, alternatives, and evidence when it is superseded.
  Correct links and status metadata without rewriting the accepted outcome.
  Follow the [documentation rules](../documentation.md).

## Records

| ADR                                               | Status               | Decision                                                                       |
| ------------------------------------------------- | -------------------- | ------------------------------------------------------------------------------ |
| [0001](adr-0001-workstation-toolchain.md)         | Implemented baseline | Workstation software, runtime ownership, and validation requirements.          |
| [0002](adr-0002-ai-tools-setup-and-management.md) | Accepted             | Provider-agnostic setup and management of AI skills and MCP servers.           |
| [0003](adr-0003-desktop-system-monitor.md)        | Accepted             | Managed GNOME top-bar system monitor indicator (Vitals).                       |
| [0004](adr-0004-documentation-boundaries.md)      | Accepted             | End user readmes, current guides, and preserved ADR history.                   |
| [0005](adr-0005-browser-sync-teardown.md)         | Accepted             | Verify captured Sync device removal through isolated, resumable teardown.      |
| [0006](adr-0006-shared-vm-lifecycle.md)           | Proposed             | Shared VM lifecycle with workstation-owned tests and verified browser removal. |
