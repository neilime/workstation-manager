# ADR 0002 AI developer tools setup and management

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

The report contains no server logs establishing a cause. Possible causes to
investigate include runtime visibility in the MCP host, package downloads during
startup, and missing or mismatched server prerequisites. Authentication depends
on the server version and transport; a missing Context7 key is not, by itself, an
established startup failure. Playwright browser readiness also needs checking
separately from MCP startup.

The [workstation toolchain decision](adr-0001-workstation-toolchain.md) defines
native Visual Studio Code, a pinned system Node.js LTS runtime, and the Codex and
Copilot CLIs. `mise` manages selected user tools and project runtimes, Renovate
keeps pins current, Chezmoi owns user-authored content, and Bitwarden holds
secrets. Browser support uses a thin per-vendor adapter behind a shared role
contract. AI extension management should reuse these mechanisms.

Existing formats and tools guide this design:

- **Common MCP launch fields** (`command`, `args`, `env`) appear in the widely
  used `mcpServers` JSON format and in client-specific configuration. The shared
  declaration borrows these fields; adapters handle each client's native schema.
- **Agent Skills** (`SKILL.md` directories) are the portable, cross-assistant
  skill format.
- **`mise`**, already the workstation's runtime manager, natively installs and
  version-matches tool-declared remote skills through its
  [packslip resources](https://mise.jdx.dev/dev-tools/packslip-resources.html)
  feature (`mise skills ls`, `mise skills sync --dir`). Node-based MCP servers
  reuse the configured system Node.js runtime; any additional runtime requires
  an explicit compatible pin and update coverage.

## Decision

Manage AI tools through a single provider-agnostic declaration that setup renders
into each installed provider's native configuration. Behavior lives in the
`workstation_setup` collection; vendor specifics live behind per-provider
adapters that mirror the [browser adapter contract](../browser-adapters.md).

### 1. One declarative source, many providers

Add a `development.ai_tools` section to the
[public defaults](../../../ansible/group_vars/all.yml), resolved like every other
setting into `workstation_manager_resolved` and normalized in the setup
collection's `desired_state*` helpers. The declaration names the enabled
providers, the skills to install, and the MCP servers to run. This is project
metadata using common MCP launch fields, with named list entries and Bitwarden
item references rather than secret values. Normalization validates selectors,
fields, and references without retrieving secrets; setup resolves credentials
separately before adapters render client configuration. Bitwarden reference
objects are never serialized as native `env` values.

The following is a proposed configuration sketch, not an implemented interface.
Replace angle-bracket placeholders with the chosen repository, immutable pins,
validated package versions, and launch paths verified in the client environment.
The MCP commands below stand for setup-provisioned launchers using those versions.

```yaml
development:
  ai_tools:
    providers:
      - copilot
      - codex
    skills:
      - name: commit-messages # custom, authored in the config repo
        source: chezmoi
      - name: hk # remote, installed and version-matched by mise packslip
        source: mise
        tool: "packslip:github.com/jdx/hk"
      - name: review-checklist # remote, no packslip metadata required
        source: git
        repository: "https://github.com/<owner>/<skills-repository>.git"
        revision: "<full-commit-sha>"
        subdirectory: skills/review-checklist
    mcp_servers:
      # Project metadata; adapters render native MCP configuration.
      - name: context7
        # Provision @upstash/context7-mcp@<validated-version> during setup.
        command: "<absolute-context7-launcher>"
        args: ["--transport", "stdio"]
        env:
          # Optional; select a version that supports this stdio variable.
          CONTEXT7_API_KEY:
            bitwarden_item_id: "<uuid>"
      - name: playwright
        # Provision @playwright/mcp@<validated-version> during setup.
        command: "<absolute-playwright-launcher>"
        args: ["--browser", "<selected-browser>"]
```

Configuration resolution validates provider selectors and adapter availability,
following the browser adapter pattern. After application and tooling provisioning,
setup checks that each selected client is installed before configuring it and
fails with an actionable error if it is missing. In check mode, checks that need
pending installations are reported as deferred, not passed.

### 2. Provider adapters own vendor format

`providers` selects roles named `neilime.workstation_setup.ai_tool_<name>`
(`ai_tool_copilot`, `ai_tool_codex`). Each adapter maps the normalized declaration
and resolved credentials into its client's native schema, including required
transport fields, and keeps vendor knowledge inside the role:

- **Codex** writes the documented
  [`[mcp_servers.<name>]` tables](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
  to `~/.codex/config.toml`, including an `env` table with string values, and
  exposes synced skills in its supported skills directory.
- **Copilot** targets the selected client surface:
  [Visual Studio Code's user-profile `mcp.json`](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)
  uses a `servers` map; the portable `~/.copilot/mcp-config.json` uses an
  `mcpServers` map read by the VS Code Agent Host and
  [Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers).
  VS Code supports both formats. The adapter exposes synced skills where the
  selected client loads them.

Adapters are idempotent, support check mode, merge into existing user
configuration instead of overwriting it, and never log secret values. Adding a
new assistant means adding one adapter, with no change to the shared declaration
or to callers.

### 3. Skills: custom and remote

Skills use the portable `SKILL.md` Agent Skills format, and installation reuses
tools already in the workstation instead of a new skill manager:

- **Custom** skills are authored in the companion `workstation-config` repository
  and delivered through the existing Chezmoi integration, so they version and
  recover with the rest of the user's dotfiles.
- **Remote skills declared by tools** are installed and version-matched by
  `mise`'s native
  [packslip skills](https://mise.jdx.dev/dev-tools/packslip-resources.html)
  support. The declaration names the owning `mise` tool; `mise` fetches the
  skills a release declares and `mise skills sync --dir <provider skills dir>`
  links them where each assistant reads skills. `mise` preserves user-authored
  directories, skips conflicting names, and can report missing resources. Setup
  must verify that each declared skill is available from its selected source in
  each provider's skill directory after synchronization; missing or conflicting
  resources fail with an actionable error while preserving user files. Tool
  versions are pinned and updated through reviewed configuration pull requests;
  implementation must add the Renovate coverage described below.
- **Other remote skills** use a Git repository, an immutable full commit SHA,
  and a repository-relative subdirectory containing `SKILL.md`. Setup uses
  [`ansible.builtin.git`](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/git_module.html)
  for a managed checkout under the resolved user's home, following the existing
  pinned Oh My Zsh checkout pattern. It validates that the selected directory
  stays within the checkout and contains `SKILL.md`; provider adapters expose
  that directory alongside custom and tool-declared skills. No packslip
  metadata or provider-specific installer is required. Updates review the
  upstream changes and replace the commit pin in a configuration pull request;
  rerunning setup checks out the approved revision and reconciles the provider
  links. Existing user-managed files are preserved.

### 4. MCP servers: install, setup, update

- **Install**: reuse the pinned system Node.js runtime for Node-based servers and
  provision compatible server packages during setup in managed locations for the
  resolved user. Provision any additional runtimes explicitly. Launch installed
  packages without fetching them at chat startup: a version pin alone does not prevent
  [`npx` from installing a missing package into its cache](https://docs.npmjs.com/cli/v11/commands/npm-exec/).
- **Launch**: configure stable commands with explicit runtime paths and environment,
  independent of interactive shell initialization. Native Visual Studio Code and
  the agent CLIs share the system Node.js runtime. Their adapters must still
  verify that each MCP host can execute the selected launcher and access its
  packages and browser files. Host executable checks alone do not establish
  successful MCP initialization or tool execution.
- **Browser prerequisites**: explicitly select Playwright's browser/channel and
  provision its binaries and Ubuntu dependencies using the Playwright version
  required by the pinned MCP package. For bundled browsers, install that version's
  matching revision; for branded channels, provision the selected supported
  browser. A generic `playwright install chromium` is insufficient when the server
  selects another channel or uses another Playwright version. Follow the
  [Playwright browser requirements](https://playwright.dev/docs/browsers) and
  reconcile them when updating the server.
- **Setup**: resolve configured credentials from Bitwarden as the resolved user,
  then render native configuration through each selected adapter. Keep secret
  values out of normalized desired state, logs, reports, and tracked files.
  Validate authentication against the selected version
  and transport: [Context7 recommends a key for higher limits](https://github.com/upstash/context7),
  rather than requiring one for every configuration. Its
  [current stdio implementation](https://github.com/upstash/context7/blob/master/packages/mcp/src/index.ts)
  accepts `CONTEXT7_API_KEY`; validate that support in the chosen release before
  using the example above. Missing inputs that the selected configuration requires
  fail setup with an actionable message.
- **Update**: pin server package versions in the declaration. Implementation must
  add supported Renovate managers or extraction rules for new tool and MCP pins
  in their tracked source files, with focused validation that each pin is detected;
  existing rules do not cover these additions. Re-running setup reconciles
  installed packages, prerequisites, and provider launch configuration to the
  reviewed versions.

### 5. Diagnose and verify the reported startup failures

Implementation must capture each server's client logs, identify its actual failure,
and validate the resulting setup in the Lima test VM before reporting a fix:

- Start each server through the selected clients, including desktop-launched
  native Visual Studio Code, with no reliance on an interactive terminal's
  environment or an existing `npx` cache. Verify MCP initialization and tool
  discovery using the provisioned runtime and package.
- Exercise Context7's documentation tools with the selected authentication mode,
  reporting authentication or service failures separately from process startup.
- Exercise a harmless Playwright browser operation against a local test page in an
  isolated profile. Successful MCP initialization alone does not prove that the
  configured browser can launch.

Automatic startup on chat messages is a validation scenario, not a reliability
guarantee established by this ADR. The reported failures remain unverified until
these checks pass in the affected client environment.

## Consequences

- One declaration configures every installed assistant consistently; a server or
  skill is defined once and reaches Copilot, Codex, and future providers.
- AI tooling reuses existing project mechanisms (`mise`, Renovate, Chezmoi,
  Bitwarden, the adapter contract), common MCP launch fields, and the portable
  `SKILL.md` format. Ordinary remote skill repositories use
  Ansible's existing Git checkout support without another skill manager.
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
- **Manage AI tools entirely through Chezmoi templates.** Rejected as the sole
  managing layer: runtime provisioning, Bitwarden integration, and provider
  reconciliation remain setup responsibilities. Chezmoi delivers custom skills;
  mise and Ansible manage the declared remote skill sources.

## Tooling evaluated

Dedicated skill and MCP installers were assessed against the goal of the most
stable, modern, widely used, and standard approach for a reproducible, headless,
Ansible-driven workstation.

- **[`mise` packslip skills](https://mise.jdx.dev/dev-tools/packslip-resources.html)** —
  Adopted for skills declared by packslip tool releases. `mise` is already the
  workstation's runtime manager,
  so this adds no new dependency. It installs the portable `SKILL.md` format,
  version-matches skills to the active tool, and syncs them into any assistant's
  skills directory. It cannot install arbitrary skill repositories without
  packslip metadata; the pinned Git source above covers those repositories.
- **[`mcpServers` JSON format](https://gofastmcp.com/integrations/mcp-json-configuration)** —
  Used as the model for common launch fields. Its native server-name map and
  string-valued `env` differ from this project's list and secret-reference
  metadata; adapters translate that metadata into supported client formats.
- **[`fastmcp install`](https://gofastmcp.com/cli/install-mcp)** — Not adopted as
  the managing layer: it targets Python/`uv` FastMCP servers, while the servers
  considered here ship as npm packages. It supports direct configuration writes
  and JSON output for automation; clipboard use is optional.
- **[`mcp-installer`](https://github.com/anaisbetts/mcp-installer)** — Rejected.
  It is itself an MCP server that an assistant drives through chat prompts to
  install others. That is imperative and non-reproducible, and it is oriented to
  Claude Desktop rather than a declarative multi-provider setup.
- **[`skills-manager`](https://github.com/xingkongliang/skills-manager)** and
  **OpenAI `skill-installer`** — Rejected as the managing layer. `skills-manager`
  is an interactive desktop GUI. `skill-installer` provides a CLI helper for
  unattended installation with repository, path, revision, and destination
  options, but fails when the destination already exists. It does not provide
  the shared reconciliation and update lifecycle proposed here. Their portable
  `SKILL.md` bundles remain installable through the pinned Git source.
