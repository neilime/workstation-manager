# AI provider adapters

The setup collection implements [ADR 0002](adr/adr-0002-ai-tools-setup-and-management.md).
[AI tool configuration](../usage/ai-tools.md) defines the user contract.

## Adapter contract

Defaults belong in [`ansible/group_vars/all.yml`](../../ansible/group_vars/all.yml).
The [AI normalizer][normalizer] validates metadata without host inspection or vault
reads. The secrets normalizer validates selectors before binding
`bitwarden_secret` references to item UUIDs. Retrieve credentials only in setup's
private credential phase.

Each `development.ai_tools.providers.<name>` entry declares its CLI's `npm`,
`version`, and `command`. Add an `ai_tool_<name>` role with:

| Task file          | Responsibility                                                                  |
| ------------------ | ------------------------------------------------------------------------------- |
| `preflight.yml`    | Check selected clients, tolerating pending installations in check mode.         |
| `authenticate.yml` | Establish and verify the provider's native account session.                     |
| `main.yml`         | Translate shared resources into native configuration and reconcile owned links. |

[Configuration resolution](../../ansible/tasks/resolve_workstation_config.yml)
requires all three files. Provider keys select roles directly; adding a provider
requires no shared registry.

The [shared role][shared-role] installs provider CLIs and Orca, then runs
preflight, native authentication, resource provisioning, credential resolution,
MCP probes and adapter configuration. It follows restoration, Chezmoi, development
tooling and GitHub authentication. An empty provider mapping skips provider and
extension provisioning while keeping Orca managed.

Run extensions as the resolved user with explicit `HOME`, `XDG_CONFIG_HOME` and
`PATH`. CLI packages belong to that user under
`~/.local/share/workstation-manager/ai-tools/cli`; root owns their
`/usr/local/bin/<command>` links. System applications and Playwright's Ubuntu
dependencies install as root. Native client updates may change executable versions
independently of npm metadata.

Adapters consume:

- `workstation_ai_servers`: MCP `command`, `args`, and string-valued `env` mappings
  keyed by name. These contain secrets: mark every consuming task `no_log: true`
  and clear temporary maps.
- `workstation_ai_skills`: verified source roots, relative directories and names.
- `workstation_ai_state`: private directory for adapter ownership records.

Keep common resources in portable Agent Skills and MCP formats, including skill
frontmatter and instructions. Keep provider-specific translation inside adapters.
Use `ai_provider_config` for JSONC merges or owned TOML blocks and `ai_skill_links`
for owned symlinks. They must reject conflicts before mutation, preserve user
content and plan without writing in check mode.

The shared role defers downloads, authentication, credential resolution, MCP
launches and native configuration in check mode; pending installations can supply
required paths. Do not report these deferred operations as verified.

## Authentication and MCP verification

[Provider authentication][provider-auth] strips ambient provider tokens and checks
native login status in the managed home. Codex requires a ChatGPT session; Copilot
uses `auth.getStatus` over its CLI's SDK transport and checks the returned account
and host against the GitHub declaration. Interactive login uses the bootstrap
terminal so credentials bypass captured Ansible output. Missing unattended login
fails. Authentication sends no model request and does not edit OAuth caches.

`development.ai_tools.authenticate: false` defers only provider login. Installation,
configuration and MCP verification still run; the final report identifies logins
as unverified. Check mode starts no clients.

The [stdio helper][mcp-stdio] bounds protocol responses and deadlines, discards
stderr, and closes its process group on completion or failure. It never logs
payloads. Probes verify discovery and each declared `auth_check`. Keep credentials
in the private server environment and select read-only tools. Use `expect_text`
for tools that report upstream failures as text without MCP's `isError` flag.

## Updating resources

Follow [dependency updates](dependencies.md) for pin ownership and extraction
checks. Recheck native authentication, configuration schemas, Node requirements,
exported binaries and credential handling when upgrading a provider or MCP server.

Global remote skills install through pinned Skillshare into isolated configuration
and source-hashed download directories. Reuse existing installations; a changed
source installs before provider links are reconciled. Audit failures propagate.
Preserve user-authored skill directories. Repository skills use the separate
[project skill workflow](project-skills.md).

Use Playwright's CLI from the installed MCP dependency tree, including its exact
upstream Playwright dependency. Do not replace it independently or use a global
installer: MCP's selected release owns that compatibility contract.

## Testing

Run the [unit and integration checks](README.md):

```sh
make test-unit
make test-integration
```

Unit tests cover normalization, native merges, skill ownership, authentication
status and Renovate extraction with synthetic inputs. Integration tests use
isolated homes, real Ansible, disposable client processes, and local HTTP/MCP
fixtures. They cover provisioning, authentication terminals, protocol failures,
idempotence, permissions, reconciliation, previews and credential redaction.

These checks require no provider accounts or live AI services. They do not verify
live OAuth sessions, desktop startup or browser operations. The Lima fixture
explicitly defers provider sign-in and checks command availability and user write
access to installed packages. Normal setup still requires provider login unless
the configuration explicitly defers it.

[normalizer]: ../../ansible/collections/ansible_collections/neilime/workstation_setup/plugins/module_utils/desired_state_ai_tools.py
[shared-role]: ../../ansible/collections/ansible_collections/neilime/workstation_setup/roles/ai_tools
[provider-auth]: ../../ansible/collections/ansible_collections/neilime/workstation_setup/plugins/modules/ai_provider_auth.py
[mcp-stdio]: ../../ansible/collections/ansible_collections/neilime/workstation_setup/plugins/module_utils/mcp_stdio.py
