# AI tools

Setup installs Orca and the baseline Codex and Copilot CLIs and configures AI
extensions from `workstation_manager.development.ai_tools` in
[`ansible/group_vars/all.yml`](../../ansible/group_vars/all.yml). Configure
applications, providers, skills and MCP servers there. The public configuration
enables both providers with pinned Context7 and Playwright MCP packages. Apply
configuration changes with `workstation.sh setup`.

## Applications

`development.ai_tools.providers` defines each provider once. Its name, such as
`codex` or `copilot`, selects the adapter; its `npm`, `version`, and `command`
fields define the CLI package, exact release and verification command. Setup
installs that CLI with the system Node runtime, verifies it without shell
activation, establishes its native account login, and configures its extensions.
CLI packages belong to the managed user, allowing Copilot's automatic updates
and `/update` command to replace its executable without administrator access.
Setup installs the configured npm release; client updates can change the running
version between setup runs.

`development.ai_tools.orca` contains Orca's release `version` and initial
`settings`. Setup checks the architecture-specific package digest and seeds only
missing settings, preserving existing workspaces and preferences.

Renovate maintains these public pins. An empty `providers` mapping skips provider
installation and extension configuration; Orca remains managed separately.

## Authentication

Setup uses a ChatGPT account session for Codex and native OAuth sign-in for
Copilot. It reuses the managed user's saved sessions. When a login is missing,
interactive setup connects the native sign-in flow to your terminal.
Complete the browser or device-code prompt there; codes and tokens are kept out
of Ansible logs. Copilot must use the configured `development.github.account`
and `development.github.host`.

For unattended setup, sign in beforehand as the managed user with `codex login`
and `copilot login`. Complete the browser approval for each account. On a headless
machine, use `codex login --device-auth` and `copilot login --device-code`, then
open the displayed links in your browser. Bitwarden account passwords do not
replace this approval step. A missing ChatGPT session or mismatched Copilot
account stops setup. A Codex API-key login does not satisfy the ChatGPT requirement.
Inherited automation tokens do not count as a persistent provider login.
Credentials remain in each client's native credential store; setup does not copy
OAuth tokens into configuration or Bitwarden. See the native
[Codex authentication](https://learn.chatgpt.com/docs/auth) and
[Copilot authentication](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/authenticate-copilot-cli)
guides for account options.

Provider authentication is required by default. For an installation-only run,
explicitly set `development.ai_tools.authenticate: false` in your private
override. Setup still installs and configures providers, skills and MCP servers,
and verifies MCP startup and declared access checks. It reports provider sign-in
as deferred and unverified; complete the native logins before using the clients.

The login checks make no model requests. They establish that the client reports
an available login; they do not prove subscription entitlement, remaining quota,
or access to a particular model. Separate desktop application sign-in prompts
still belong to those applications.

## MCP servers

[MCP](https://modelcontextprotocol.io/docs/getting-started/intro) is the shared
protocol for tools and services. The same server launches are rendered into each
provider's native configuration by its adapter. Setup currently configures Codex
and Copilot; adding another provider requires its installation, authentication
and configuration adapter. Provider plugin packages are not required for the
shared skills or MCP servers.

Each entry in `development.ai_tools.mcp_servers` defines one server's installation
and launch settings: a unique lowercase `name`, an `args` list and an optional
`env` mapping. For npm installation, declare the `npm` package, exact stable
`version`, and exported `binary` in that same entry. For a program already
installed on the workstation, declare its absolute `command` instead. Managed
servers use local stdio; remote HTTP servers and their OAuth flows are not managed.

Keep maintained versions in `all.yml` with their Renovate annotations. Setup
provisions npm packages under the managed user's home and configures installed
executables; chat startup does not use `npx` or download missing packages.

Context7 requires an API key stored in Bitwarden. Set its item UUID under
`secrets.bitwarden`:

```yaml
secrets:
  bitwarden:
    context7-api-key: "<item-uuid>"
```

Store the API key in that item's password field. Setup supplies it as
`CONTEXT7_API_KEY` through the public MCP declaration. A missing, blank, or invalid
item UUID fails configuration validation, including during dry runs. A missing,
empty, or inaccessible item password fails setup.

Other MCP `env` credentials can use `bitwarden_item_id` directly or
`bitwarden_secret` to reference a selector in `secrets.bitwarden`. Unknown
selector names and empty selectors fail validation. Credential fields support `login.password` (the default),
`login.username`, `notes`, and `fields.NAME`. An optional
`bitwarden_collection_id` restricts the item to the expected collection.
Missing, empty, ambiguous or inaccessible credentials fail setup. Literal `env`
strings are for non-secret values. Setup reuses the managed user's Bitwarden
session and cache; see [Bitwarden authentication](configuration.md#prepare-bitwarden-collections).

An optional `auth_check` declares a read-only MCP tool call to verify service
access after startup. Set its `tool`, optional `arguments` mapping, and optional
`expect_text` substring. Use a harmless identity or public lookup operation and
keep its arguments free of secrets. A failed call or missing expected response
stops setup without logging the server response. Servers without this declaration
receive startup and tool-discovery checks only.

The default Context7 check resolves a public library and validates access with
any configured key. Invalid keys, quota limits and network failures stop setup.
Local Playwright needs no server login.

For `@playwright/mcp`, `playwright.browser` selects `chromium`, `firefox` or
`webkit`. Setup uses the Playwright dependency shipped with the pinned MCP package
to install the matching browser and Ubuntu libraries. Browser caches are separate
for each server version. The default arguments use a headless, isolated profile.
Browser selection flags and external browser connections cannot override this
managed selection; omit `playwright` only when you provision prerequisites yourself.

## Skills

Skills use the open [Agent Skills](https://agentskills.io/home) format: a directory
with `SKILL.md` and optional scripts or references. Codex, Copilot and Claude Code
support this format. Skillshare handles installation and synchronization; its
`name` and `source` declarations select the content without changing its format.
Use shared command-line tools such as `gh` and portable skill instructions. Check
upstream requirements before selecting skills that depend on a provider-specific
connector, tool name or extension.

The default declaration exposes `review-loop` and `migrate-lib`, supplied by
`workstation-config` through Chezmoi, to both providers. `review-loop` runs an
explicitly requested review and fix workflow; `migrate-lib` guides dependency
migrations. Their source files live in `home/dot_agents/skills/` in the companion
repository.

Each skill uses Skillshare's `name` and `source` fields. Local sources start with
`~/`, relative to the managed user's home. Remote sources use a GitHub skill URL
with a full 40-character commit SHA, either as `owner/repo/tree/<sha>/<path>` or
with the `https://github.com/` prefix. Each source directory must contain `SKILL.md`.

For example, in `all.yml`, replace the remote placeholders with a reviewed source:

```yaml
workstation_manager:
  development:
    ai_tools:
      skills:
        - name: commit-messages
          source: ~/.agents/skills/commit-messages
        - name: review-checklist
          # renovate: datasource=git-refs depName=<owner>/<repository> branch=main
          source: "<owner>/<repository>/tree/<full-commit-sha>/skills/review-checklist"
```

Chezmoi applies before AI setup. Local sources are linked directly; a missing
selected skill fails setup. Setup installs remote sources with the configured
Skillshare release and exposes them through the provider adapters. Reruns reuse
installed sources; changing a source pin installs the selected revision and
updates managed provider links. Skillshare's download configuration is private to
setup, so a personal global Skillshare configuration remains untouched.

Renovate proposes commit updates for sources annotated with `datasource=git-refs`,
`depName` and `branch`, as shown above. Choose a maintained upstream skill and
review its dependencies before adding it. Review upstream changes before
accepting a new pin.

For skills scoped to a repository, use its `.skillshare/config.yaml` as described
in [project skills](../development/project-skills.md).

## Configuration ownership and reruns

| Client             | MCP configuration                          |
| ------------------ | ------------------------------------------ |
| Codex              | `~/.codex/config.toml`, `mcp_servers`      |
| Copilot            | `~/.copilot/mcp-config.json`, `mcpServers` |
| Visual Studio Code | `~/.config/Code/User/mcp.json`, `servers`  |

Copilot's portable file serves CLI and Agent Host. The native Visual Studio Code file is
configured when `code` is selected in `editor_packages`. Codex reads skills from
`~/.agents/skills`; Copilot clients read `~/.copilot/skills`.

Setup requires selected clients to exist after application provisioning. It
preserves unrelated configuration and comments. Codex entries live in a marked
TOML block; JSON entries are merged individually. Private native files have mode
`0600`, including any credentials resolved from Bitwarden. Exclude generated MCP
settings and credentials from Chezmoi source files and application settings
synchronization. Personal Codex preferences may use a Chezmoi modify template
that preserves the current MCP tables and their ownership markers. It must leave
the existing file unchanged when personal preferences already match, so setup's
updates do not create dotfile drift. Do not track the rendered configuration as a
regular dotfile or use `chezmoi add` to capture its credentials. Setup refuses
symlinked configuration paths so it cannot write credentials into a dotfile source.

Ownership fingerprints and link targets live in
`~/.local/state/workstation-manager/ai-tools`. Reruns update or remove only
unchanged, setup-owned entries and symlinks. Personal files, custom skill
directories, and edits to managed entries are preserved; conflicting names fail
setup. Move or rename conflicting native entries before adopting a name into the
declaration. Keep personal Codex tables outside the managed block. Codex can insert
project tables before its closing marker; setup refuses to replace that block
until those personal tables are moved outside it.

Remove a server or skill from the declaration and rerun setup while its provider
is still enabled to remove the managed entry or link. Disabling a provider
preserves its installed CLI and existing files. Cached packages, browser binaries and Git checkouts
are retained; removing an extension does not erase its source content.

## Verification and troubleshooting

Normal setup starts each declared MCP command as the managed user with explicit
runtime paths, checks protocol initialization and tool discovery, and runs any
declared authentication/access check. Failures stop setup and server output stays
private. These checks do not establish that a desktop client starts the same
server successfully or that a browser can launch.

`workstation.sh setup --dry-run` validates declarations and provider availability
where possible. Downloads, provider sign-in, credentials, MCP execution and configuration changes are
reported as deferred; a preview does not prove startup readiness.

After setup, restart the clients. In Copilot CLI use `/mcp`; in Codex use `/mcp`
and `codex mcp list`; in Visual Studio Code use **MCP: List Servers** and each server's output
log. Resolve existing workspace or profile entries that override the same names.
Keep logs private: server diagnostics may contain credentials.
