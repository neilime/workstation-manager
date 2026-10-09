# Architecture decision records

Architecture decision records (ADRs) capture a significant decision, the context
that forced it, and the consequences the project accepts. Read them to understand
why a part of the system works the way it does before changing that behavior.

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

## Records

| ADR                                               | Status               | Decision                                                              |
| ------------------------------------------------- | -------------------- | --------------------------------------------------------------------- |
| [0001](adr-0001-workstation-toolchain.md)         | Implemented baseline | Workstation software, runtime ownership, and validation requirements. |
| [0002](adr-0002-ai-tools-setup-and-management.md) | Proposed             | Provider-agnostic setup and management of AI skills and MCP servers.  |
