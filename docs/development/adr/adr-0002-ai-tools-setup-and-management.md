# ADR 0002 AI developer tools setup and management

- Status: Accepted
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
- **[Skillshare](https://skillshare.runkids.cc/)** installs remote skills from a
  source URL and manages repository-scoped declarations. `mise` provisions its
  pinned CLI. Local custom skills remain Chezmoi-owned directories.
- Node-based MCP servers reuse the configured system Node.js runtime; any
  additional runtime requires an explicit compatible pin and update coverage.

## Decision

Manage AI tools through a single provider-agnostic declaration that setup renders
into each installed provider's native configuration. Behavior lives in the
`workstation_setup` collection; vendor specifics live behind per-provider
adapters that mirror the [browser adapter contract](../browser-adapters.md).

The portability boundary is [Agent Skills](https://agentskills.io/home) for
workflows and [MCP](https://modelcontextprotocol.io/docs/getting-started/intro) for
tools. Both are supported by Codex, Copilot and Claude Code. Skillshare manages
skill downloads and links; it does not define the skill format. Keep reusable
content independent of provider-specific connectors and plugin runtimes. Provider
adapters own installation, sign-in and native configuration differences.

### 1. One declarative source, many providers

Use the `workstation_manager.development.ai_tools` section in the
[public configuration](../../../ansible/group_vars/all.yml). Settings resolve
into `workstation_manager_resolved` and are normalized in the setup collection's
`desired_state*` helpers. The
configuration groups the baseline Orca application
under `orca`, provider CLI installation and adapter selection together under
`providers`, and MCP installation and launch settings under `mcp_servers`. Each
provider entry contains its `npm` package, `version` and verification `command`.
Each npm server entry contains its `npm` package, `version`, exported `binary`
and launch options. The declaration also names the skills to install. This is project
metadata using common MCP launch fields, with named list entries and Bitwarden
item references rather than secret values. Normalization validates selectors,
fields, and references without retrieving secrets; setup resolves credentials
separately before adapters render client configuration. Bitwarden reference
objects are never serialized as native `env` values.

The implemented interface is documented in the
[AI tool guide](../../usage/ai-tools.md). The example below adds skills in
`all.yml`; keep its existing provider and MCP server declarations. Replace the
repository and commit placeholders with a reviewed source. Skillshare's release
is pinned in `development.mise.tools`.

```yaml
workstation_manager:
  development:
    ai_tools:
      skills:
        - name: commit-messages
          source: ~/.agents/skills/commit-messages
        - name: review-checklist
          source: "<owner>/<skills-repository>/tree/<full-commit-sha>/skills/review-checklist"
```

Configuration resolution validates provider selectors and adapter availability,
following the browser adapter pattern. After application and tooling provisioning,
setup checks that each selected client is installed before configuring it and
fails with an actionable error if it is missing. In check mode, checks that need
pending installations are reported as deferred, not passed.

### 2. Provider adapters own vendor format

The keys in `providers` select roles named `neilime.workstation_setup.ai_tool_<name>`
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
  `mcpServers` map read by the Visual Studio Code Agent Host and
  [Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers).
  Visual Studio Code supports both formats. The adapter exposes synced skills where the
  selected client loads them.

Adapters are idempotent, support check mode, merge into existing user
configuration instead of overwriting it, and never log secret values. Adding a
new assistant means adding one adapter, with no change to the shared declaration
or to callers.

### 3. Skills: custom and remote

Skills use the portable `SKILL.md` Agent Skills format and Skillshare's `name`
and `source` declaration:

- **Custom skills** are authored in the companion `workstation-config` repository
  and delivered through Chezmoi. Their `~/` sources resolve in the managed home
  and link directly to providers, preserving the original content.
- **Remote skills** use pinned GitHub URLs. Setup runs the configured Skillshare
  release with a private configuration and download directory for each source.
  Native installation auditing remains enabled. Changing a source pin creates a
  fresh installation before provider links are reconciled. Renovate follows
  annotated repository branches and proposes commit updates for review.
- **Repository skills** use `.skillshare/config.yaml` and its generated lockfile.
  Setup discovers opted-in projects and runs Skillshare's native installation
  and synchronization. The `universal` target exposes `.agents/skills` to Codex
  and Copilot; the `claude` target exposes the same content through `.claude/skills`.
  The [project guide](../README.md#project-skills) owns the
  configuration and setup workflow.

Provider adapters validate selected skill directories and preserve user-managed
files. Missing sources and conflicting provider destinations fail setup. Global
setup downloads remain separate from personal Skillshare configuration.

### 4. MCP servers: install, setup, update

- **Install**: reuse the pinned system Node.js runtime for Node-based servers and
  provision compatible server packages during setup in managed locations for the
  resolved user. Provision any additional runtimes explicitly. Launch installed
  packages without fetching them at chat startup: a version pin alone does not prevent
  [`npx` from installing a missing package into its cache](https://docs.npmjs.com/cli/v11/commands/npm-exec/).
- **Launch**: configure stable commands with explicit runtime paths and environment,
  independent of interactive shell initialization. Keep the pinned install under its
  versioned directory and reference it through a stable `current` symlink that tracks
  the installed version, so the rendered launch command and browser cache path stay
  identical across version updates and across a user's machines, including when the
  resulting `mcp.json` is carried by Settings Sync. Native Visual Studio Code and
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
- **Setup**: reuse native provider logins or start interactive sign-in; unattended
  runs require an existing login. Resolve configured MCP credentials from Bitwarden as the resolved user,
  then render native configuration through each selected adapter. Keep secret
  values out of normalized desired state, logs, reports, and tracked files.
  Validate authentication against the selected version
  and transport: [Context7 recommends a key for higher limits](https://github.com/upstash/context7),
  rather than requiring one for every configuration. Its
  [current stdio implementation](https://github.com/upstash/context7/blob/master/packages/mcp/src/index.ts)
  accepts `CONTEXT7_API_KEY`; validate that support in the chosen release before
  using the [credential example](../../usage/ai-tools.md#mcp-servers). Missing inputs that the selected configuration requires
  fail setup with an actionable message. Run declared read-only `auth_check` calls
  after discovery; Context7 defaults include a public library lookup so invalid
  credentials or unavailable service access stop setup.
- **Update**: pin each server's package version in its `ai_tools.mcp_servers` entry. The annotated
  Renovate manager extracts MCP and tool pins from public defaults, with focused
  tests verifying package versions and skill source pins. Re-running setup reconciles
  installed packages, prerequisites, and provider launch configuration to the
  reviewed versions.

### 5. Verify adapters with unit and integration tests

Unit tests cover configuration normalization, native formats, resource ownership,
authentication status and MCP protocol behavior. Isolated integration tests run
real Ansible with temporary homes, synthetic client executables and local fixtures
to verify installation orchestration, idempotence, permissions, previews and
credential redaction. See the [adapter testing guide](../ai-tools.md#testing).

Live provider sessions, hosted-service availability and desktop/browser behavior
are outside the test suite's scope. Passing these checks does not establish that
the reported client startup failures are resolved.

## Consequences

- One declaration configures every installed assistant consistently; a server or
  skill is defined once and reaches Copilot, Codex, and future providers.
- AI tooling reuses existing project mechanisms (`mise`, Renovate, Chezmoi,
  Bitwarden, the adapter contract), common MCP launch fields, and the portable
  `SKILL.md` format. Skillshare provides remote installation and project skill
  synchronization with the same source notation.
- Secrets stay in Bitwarden and out of tracked files, matching the project's
  existing secret-handling guarantees.
- Each provider adds integration cost: a new adapter must be written and tested,
  and vendor format changes are absorbed inside that adapter.
- The shared declaration is intentionally a lowest-common-denominator surface.
  Provider-only capabilities that cannot be expressed agnostically are configured
  inside the owning adapter, not added to the shared schema.
- Defaults, normalizers, adapters, ownership reconciliation, tests and user
  documentation implement this decision together. Setup verifies stdio
  initialization, discovery and declared authentication/access checks; client
  startup and browser operations are outside automated test coverage.

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
  Skillshare installs remote sources and provider adapters reconcile their links.

## Tooling evaluated

Dedicated skill and MCP installers were assessed against the goal of the most
stable, modern, widely used, and standard approach for a reproducible, headless,
Ansible-driven workstation.

- **[Skillshare](https://skillshare.runkids.cc/)** — Adopted for remote skill
  installation and repository-scoped synchronization. Its source URLs keep each
  declaration compact, while full commit SHAs preserve reproducible global
  downloads and native lockfiles pin project downloads.
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
  `SKILL.md` bundles remain installable through pinned Skillshare sources.
