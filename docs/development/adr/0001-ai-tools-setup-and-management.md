# 0001. AI developer tools setup and management

- Status: Proposed
- Date: 2026-10-08
- Deciders: workstation-manager maintainers
- Issue: [#277](https://github.com/neilime/workstation-manager/issues/277)

## Context

Workstations now run one or more AI coding assistants. The two in use today are
GitHub Copilot and OpenAI Codex, and more are likely. Each assistant consumes the
same two kinds of extension:

- **Skills**: reusable instruction bundles that teach an assistant a repeatable
  procedure. Some are **custom** (authored for this workstation) and some are
  **remote** (published by a third party and installed, then updated, from a Git
  repository or registry).
- **MCP servers**: [Model Context Protocol](https://modelcontextprotocol.io)
  servers that expose tools and data to an assistant. They must be installed,
  configured with their runtime, credentials, and arguments, and kept current.

Every provider stores this configuration in its own location and format. Managing
each assistant by hand drifts quickly: a server declared for Copilot is missing
from Codex, pinned versions diverge, and secrets leak into tracked files.

The current unmanaged setup also fails at runtime. Copilot reports:

```text
Multiple MCP servers were unable to start successfully:
  io.github.upstash/context7
  microsoft/playwright-mcp
Automatically start MCP servers when sending a chat message
```

These failures share root causes that this decision must address:

- The launch command depends on a runtime (`node`/`npx`, or a container engine)
  that is not guaranteed to be present or on the MCP host's `PATH`.
- Unpinned `npx -y <package>@latest` launches resolve and download on every cold
  start, which is slow and can time out before the server reports ready.
- Some servers need inputs that were never provisioned: Context7 expects an API
  key, and Playwright needs its browser binaries installed.

This project already solves the equivalent problems for other tools: `mise`
manages pinned runtimes, Renovate keeps pinned remote revisions current, Chezmoi
owns user-authored content, Bitwarden holds secrets, and browser support uses a
thin per-vendor adapter behind a shared role contract. AI tooling should reuse
these patterns rather than invent new ones.

## Decision

Manage AI tools through a single provider-agnostic declaration that setup renders
into each installed provider's native configuration. Behavior lives in the
`workstation_setup` collection; vendor specifics live behind per-provider
adapters that mirror the [browser adapter contract](../browser-adapters.md).

### 1. One declarative source, many providers

Add an `development.ai_tools` section to the
[public defaults](../../../ansible/group_vars/all.yml), resolved like every other
setting into `workstation_manager_resolved` and normalized in the setup
collection's `desired_state*` helpers. The declaration names the enabled
providers, the skills to install, and the MCP servers to run. It never contains
secrets; those stay in Bitwarden and are referenced by collection and item ID.

```yaml
development:
  ai_tools:
    providers:
      - copilot
      - codex
    skills:
      - name: commit-messages # custom, authored in the config repo
        source: chezmoi
      - name: terraform-review # remote, pinned and Renovate-tracked
        source: git
        repository: https://github.com/example/skill-terraform-review.git
        version: v1.4.0
    mcp_servers:
      - name: context7
        command: npx
        args: ["-y", "@upstash/context7-mcp@1.0.0"]
        env:
          CONTEXT7_API_KEY:
            bitwarden_item_id: "<uuid>"
      - name: playwright
        command: npx
        args: ["-y", "@playwright/mcp@0.0.41"]
```

A provider is configured only when its client is actually installed on the
workstation; a selector that names a missing provider fails configuration
resolution with an actionable error, as browser selection already does.

### 2. Provider adapters own vendor format

`providers` selects roles named `neilime.workstation_setup.ai_tool_<name>`
(`ai_tool_copilot`, `ai_tool_codex`). Each adapter translates the shared
declaration into its provider's files and keeps all vendor knowledge inside the
role:

- **Codex** writes `[mcp_servers.<name>]` tables to `~/.codex/config.toml` and
  places skill and prompt content where Codex loads it, preserving any existing
  user-managed entries.
- **Copilot** writes the MCP server definitions to the Copilot CLI and Visual
  Studio Code configuration it reads, and installs skills as the agent files
  Copilot loads.

Adapters are idempotent, support check mode, merge into existing user
configuration instead of overwriting it, and never log secret values. Adding a
new assistant means adding one adapter, with no change to the shared declaration
or to callers.

### 3. Skills: custom and remote

- **Custom** skills are authored in the companion `workstation-config` repository
  and delivered through the existing Chezmoi integration, so they version and
  recover with the rest of the user's dotfiles. Setup links or copies them into
  each selected provider's skills location.
- **Remote** skills are installed from a pinned Git revision (or registry
  version) into a managed directory, updated to the declared version on later
  runs, and refuse to overwrite tracked local edits. Pins follow the repository's
  Renovate conventions so updates arrive as reviewed pull requests, exactly like
  the Oh My Zsh and `mise` tool pins.

### 4. MCP servers: install, setup, update

- **Install**: provision the launch runtime deterministically. Node-based servers
  use the `mise`-managed Node already installed for development, so `npx` resolves
  against a known binary on `PATH`; containerized servers use the managed Docker
  daemon. Pre-install per-server prerequisites during setup (for example,
  `playwright install chromium`) so the first chat message does not pay that cost.
- **Setup**: render each server's `command`, `args`, and `env` into every selected
  provider's configuration. Required credentials are read from Bitwarden as the
  resolved user and injected through the provider configuration without being
  written to logs, reports, or tracked files. Missing required inputs fail setup
  with a clear message rather than leaving a server that cannot start.
- **Update**: pin server package versions in the declaration and track them with
  Renovate. Re-running setup reconciles each provider to the declared versions.

### 5. Fix the current startup failures

The failures above are resolved by the rules this ADR adopts:

- Servers launch from the `mise`-managed Node runtime, so `npx` is found.
- Package versions are pinned, removing the per-start `@latest` resolution that
  caused cold-start timeouts.
- Context7 receives its API key from Bitwarden, and the Playwright browser
  binaries are installed during setup.

With a working, pinned launch command and provisioned inputs, "Automatically
start MCP servers when sending a chat message" can remain enabled because the
servers start reliably.

## Consequences

- One declaration configures every installed assistant consistently; a server or
  skill is defined once and reaches Copilot, Codex, and future providers.
- AI tooling reuses existing project mechanisms (`mise`, Renovate, Chezmoi,
  Bitwarden, the adapter contract) instead of adding new ones, keeping the mental
  model and the maintenance surface small.
- Secrets stay in Bitwarden and out of tracked files, matching the project's
  existing secret-handling guarantees.
- Each provider adds integration cost: a new adapter must be written and tested,
  and vendor format changes are absorbed inside that adapter.
- The shared declaration is intentionally a lowest-common-denominator surface.
  Provider-only capabilities that cannot be expressed agnostically are configured
  inside the owning adapter, not added to the shared schema.
- This ADR records the decision only. Implementation (defaults, normalizers, the
  adapters, tests, and user documentation) follows in separate changes that update
  those artifacts together, per the repository conventions.

## Alternatives considered

- **Configure each assistant independently.** Rejected: it guarantees drift
  between providers, duplicates pins and secrets, and offers no shared contract
  for adding the next assistant.
- **Standardize on one assistant.** Rejected: the workstation deliberately runs
  multiple assistants, and the project's purpose is to manage the real
  environment rather than constrain it.
- **Manage AI tools entirely through Chezmoi templates.** Rejected for MCP
  servers and remote skills: Chezmoi fits user-authored content but not runtime
  provisioning, secret injection from Bitwarden, pinned remote installs, or
  check-mode-safe reconciliation. Chezmoi still delivers custom skills.
