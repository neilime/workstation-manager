"""Exercise AI declarations and private credential resolution without host access."""

from copy import deepcopy
from hashlib import sha256

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.ai_tools import (
    AiToolsRuntime,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state_ai_tools import (
    AiToolsNormalizer,
)

UUID = "12345678-1234-1234-1234-123456789abc"


@pytest.fixture(name="declaration")
def ai_declaration(with_tool_versions):
    """Supply synthetic package pins and a mix of credential and public values."""
    return with_tool_versions(
        {
            "development": {
                "mise": {"tools": {"github:runkids/skillshare": "1.2.3"}},
                "ai_tools": {
                    "skills": [],
                    "mcp_servers": [
                        {
                            "name": "example",
                            "npm": "@example/server",
                            "version": "1.2.3",
                            "binary": "example-mcp",
                            "env": {"PUBLIC": "value", "TOKEN": {"bitwarden_item_id": UUID}},
                        }
                    ],
                },
            }
        }
    )["development"]


def test_normalization_does_not_mutate_input_or_resolve_vault_records(declaration):
    """Normalization does not mutate input or resolve vault records."""
    config = declaration
    original = deepcopy(config)
    normalized = AiToolsNormalizer().normalize(config)
    assert config == original
    server = normalized["mcp_servers"][0]
    assert server["npm"] == {"package": "@example/server", "version": "1.2.3", "binary": "example-mcp"}
    assert server["env"]["TOKEN"]["bitwarden_item_id"] == UUID
    assert AiToolsRuntime.credential_ids(normalized["mcp_servers"]) == [UUID]
    result = AiToolsRuntime().servers(
        normalized["mcp_servers"], "/home/fixture", [{"id": UUID, "login": {"password": "synthetic-secret"}}]
    )["example"]
    assert result["command"].endswith("/npm/example/current/node_modules/.bin/example-mcp")
    assert result["env"]["TOKEN"] == "synthetic-secret"
    assert "npx" not in result["command"]
    assert "synthetic-secret" not in str(normalized)


@pytest.mark.parametrize(
    "changes",
    [
        {"providers": {"../escape": {}}},
        {"providers": {"codex": "invalid"}},
        {"mcp_servers": [{"name": "a", "command": "npx"}]},
        {"mcp_servers": [{"name": "a", "command": "/bin/true", "args": [42]}]},
        {"mcp_servers": [{"name": "a", "command": "/bin/true", "env": {"TOKEN": {"bitwarden_item_id": "invalid"}}}]},
        {"mcp_servers": [{"name": "a", "command": "/bin/true", "playwright": {"browser": []}}]},
        {
            "mcp_servers": [
                {"name": "a", "command": "/bin/true", "env": {"TOKEN": {"bitwarden_item_id": UUID, "field": []}}}
            ]
        },
    ],
)
def test_invalid_declarations_fail_at_the_configuration_boundary(changes, declaration):
    """Invalid declarations fail at the configuration boundary."""
    config = declaration
    config["ai_tools"].update(changes)
    with pytest.raises(ValueError):
        AiToolsNormalizer().normalize(config)


@pytest.mark.parametrize("field", ["npm", "version", "binary"])
def test_npm_servers_require_their_own_installation_details(declaration, field):
    """Each npm server must declare its package, stable release and exported binary."""
    del declaration["ai_tools"]["mcp_servers"][0][field]
    with pytest.raises(ValueError):
        AiToolsNormalizer().normalize(declaration)


@pytest.mark.parametrize(
    "changes",
    [
        {"npm": "--global"},
        {"npm": "https://example.test/server.tgz"},
        {"version": "latest"},
        {"version": "1.2.3-rc.1"},
        {"binary": "../server"},
        {"command": "/installed/server"},
    ],
)
def test_mcp_installation_details_are_validated_before_provisioning(declaration, changes):
    """Inline npm metadata must be safe, pinned and unambiguous about launch ownership."""
    declaration["ai_tools"]["mcp_servers"][0].update(changes)
    with pytest.raises(ValueError):
        AiToolsNormalizer().normalize(declaration)


def test_installed_mcp_commands_require_no_npm_metadata(declaration):
    """An installed absolute command keeps its arguments without requesting npm provisioning."""
    declaration["ai_tools"]["mcp_servers"] = [{"name": "local", "command": "/installed/server", "args": ["--stdio"]}]
    normalized = AiToolsNormalizer().normalize(declaration)["mcp_servers"]
    assert normalized[0]["npm"] == {}
    server = AiToolsRuntime().servers(normalized, "/home/fixture", [])["local"]
    assert server["command"] == "/installed/server"
    assert server["args"] == ["--stdio"]


@pytest.mark.parametrize("metadata", [{"version": "1.2.3"}, {"binary": "server"}])
def test_installed_mcp_commands_reject_unused_installation_details(declaration, metadata):
    """Package-only fields cannot silently accompany an already installed command."""
    declaration["ai_tools"]["mcp_servers"] = [{"name": "local", "command": "/installed/server", **metadata}]
    with pytest.raises(ValueError, match="require an npm package"):
        AiToolsNormalizer().normalize(declaration)


@pytest.mark.parametrize("prefix", ["", "https://github.com/"])
def test_name_and_source_resolve_local_skills_and_pinned_remote_skills(declaration, prefix):
    """Native source strings preserve local files and give each remote pin its own cache."""
    source = f"{prefix}example/skills/tree/{'a' * 40}/skills/review"
    declaration["ai_tools"]["skills"] = [
        {"name": "local", "source": "~/.agents/skills/local"},
        {"name": "review", "source": source},
    ]
    original = deepcopy(declaration)
    normalized = AiToolsNormalizer().normalize(declaration)["skills"]
    assert declaration == original
    runtime = AiToolsRuntime.skills(normalized, "/home/fixture")
    assert runtime == [
        {"name": "local", "root": "/home/fixture", "subdirectory": ".agents/skills/local"},
        {
            "name": "review",
            "root": (
                "/home/fixture/.local/share/workstation-manager/ai-tools/skillshare/"
                f"{sha256(source.encode()).hexdigest()}/skills"
            ),
            "subdirectory": "review",
        },
    ]
    declaration["ai_tools"]["skills"][1]["source"] = source.replace("a" * 40, "b" * 40)
    updated = AiToolsNormalizer().normalize(declaration)["skills"]
    assert AiToolsRuntime.skills(updated, "/home/fixture")[1]["root"] != runtime[1]["root"]


@pytest.mark.parametrize(
    "source",
    [
        [],
        "",
        "~/../escape",
        "/other/home/skill",
        "~/skill\x00",
        "example/skills/tree/main/skill",
        f"https://token@github.com/example/skills/tree/{'a' * 40}/skill",
        f"example/skills/tree/{'a' * 40}/../escape",
        f"example/skills/tree/{'a' * 40}/%2e%2e/escape",
        f"example/skills/tree/{'a' * 40}/skill?token=private",
    ],
)
def test_skill_sources_require_portable_local_paths_or_pinned_remote_urls(declaration, source):
    """Validate source types, traversal, immutable pins and credential-free URLs before downloads."""
    declaration["ai_tools"]["skills"] = [{"name": "example", "source": source}]
    with pytest.raises(ValueError):
        AiToolsNormalizer().normalize(declaration)


@pytest.mark.parametrize("pin", [None, "", "latest"])
def test_remote_skills_require_a_pinned_skillshare_tool(declaration, pin):
    """Remote provisioning cannot depend on an implicit or floating installer version."""
    declaration["mise"]["tools"]["github:runkids/skillshare"] = pin
    declaration["ai_tools"]["skills"] = [{"name": "example", "source": f"example/skills/tree/{'a' * 40}/skill"}]
    with pytest.raises(ValueError, match="skillshare"):
        AiToolsNormalizer().normalize(declaration)


def test_local_skills_do_not_require_a_skill_installer(declaration):
    """Existing local content can be linked without provisioning a downloader."""
    declaration["mise"]["tools"].pop("github:runkids/skillshare")
    declaration["ai_tools"]["skills"] = [{"name": "example", "source": "~/.agents/skills/example"}]
    assert AiToolsNormalizer().normalize(declaration)["skills"][0]["kind"] == "local"


@pytest.mark.parametrize(
    "record",
    [
        {"id": UUID, "login": {}},
        {"id": UUID, "login": {"password": ""}},
        {"id": "different", "login": {"password": "synthetic-secret"}},
    ],
)
def test_invalid_credentials_do_not_expose_values(record):
    """Invalid credentials do not expose values."""
    with pytest.raises(ValueError) as error:
        AiToolsRuntime.credential({"bitwarden_item_id": UUID, "field": "login.password"}, [record])
    assert "synthetic-secret" not in str(error.value)


def test_custom_credential_fields_require_a_unique_field_and_expected_collection():
    """Custom credential fields require a unique field and expected collection."""
    reference = {"bitwarden_item_id": UUID, "bitwarden_collection_id": UUID, "field": "fields.token"}
    record = {"id": UUID, "collectionIds": [UUID], "fields": [{"name": "token", "value": "synthetic-secret"}]}
    assert AiToolsRuntime.credential(reference, [record]) == "synthetic-secret"
    with pytest.raises(ValueError):
        AiToolsRuntime.credential(reference, [record, record])
    record["fields"].append(record["fields"][0])
    with pytest.raises(ValueError):
        AiToolsRuntime.credential(reference, [record])
    record["collectionIds"] = []
    with pytest.raises(ValueError, match="collection"):
        AiToolsRuntime.credential(reference, [record])


def test_playwright_launch_uses_the_browser_cache_for_its_pinned_server(with_tool_versions):
    """Playwright launch uses the browser cache for its pinned server."""
    normalized = AiToolsNormalizer().normalize(
        with_tool_versions(
            {
                "development": {
                    "ai_tools": {
                        "mcp_servers": [
                            {
                                "name": "browser",
                                "npm": "@playwright/mcp",
                                "version": "1.2.3",
                                "binary": "playwright-mcp",
                                "playwright": {"browser": "chromium"},
                            }
                        ]
                    }
                }
            }
        )["development"]
    )
    server = AiToolsRuntime().servers(normalized["mcp_servers"], "/home/fixture", [])["browser"]
    assert server["args"] == ["--browser", "chromium"]
    assert server["env"]["PLAYWRIGHT_BROWSERS_PATH"].endswith("/browsers/browser/current")


def test_provider_entries_preserve_installation_pins_and_adapter_names(with_tool_versions):
    """The declared provider name and CLI details resolve together without a shared registry."""
    config = with_tool_versions(
        {
            "development": {
                "ai_tools": {
                    "orca": {"version": "9.8.7", "settings": {"theme": "system"}},
                    "providers": {"agent": {"npm": "@example/agent-cli", "version": "4.5.6", "command": "agent-cli"}},
                }
            }
        }
    )["development"]
    original = deepcopy(config)
    result = AiToolsNormalizer().normalize(config)
    assert result["orca"] == config["ai_tools"]["orca"]
    assert result["providers"] == config["ai_tools"]["providers"]
    assert "agent" in result["providers"]
    assert config == original


@pytest.mark.parametrize("field", ["npm", "version", "command"])
def test_each_provider_requires_explicit_installation_details(with_tool_versions, field):
    """Selected providers cannot omit their package, release pin or verification command."""
    config = with_tool_versions({})["development"]
    del config["ai_tools"]["providers"]["codex"][field]
    with pytest.raises(ValueError):
        AiToolsNormalizer().normalize(config)


@pytest.mark.parametrize(
    "changes",
    [
        {"version": "latest"},
        {"version": "1.2.3-rc.1"},
        {"npm": "--global"},
        {"npm": "https://example.test/agent.tgz"},
        {"command": "../agent"},
        {"unexpected": "synthetic-private-value"},
    ],
)
def test_provider_installation_details_are_validated(with_tool_versions, changes):
    """Provider installations require safe package names, stable releases and executable names."""
    config = with_tool_versions({})["development"]
    config["ai_tools"]["providers"]["codex"].update(changes)
    with pytest.raises(ValueError) as error:
        AiToolsNormalizer().normalize(config)
    assert "synthetic-private-value" not in str(error.value)


def test_an_empty_provider_mapping_keeps_orca_without_selecting_any_cli(with_tool_versions):
    """An empty provider selection leaves only the separately managed Orca application."""
    config = with_tool_versions({})["development"]
    config["ai_tools"]["providers"] = {}
    result = AiToolsNormalizer().normalize(config)
    assert result["providers"] == {}
    assert result["orca"]["version"] == config["ai_tools"]["orca"]["version"]


def test_provider_authentication_is_required_unless_explicitly_deferred(declaration):
    """Installation-only runs defer login without dropping providers, skills or MCP checks."""
    normalizer = AiToolsNormalizer()
    expected = normalizer.normalize(declaration)
    assert expected["authenticate"] is True
    declaration["ai_tools"]["authenticate"] = False
    assert normalizer.normalize(declaration) == {**expected, "authenticate": False}


@pytest.mark.parametrize("value", ["false", 0, {}, []])
def test_provider_authentication_setting_requires_a_boolean(declaration, value):
    """Ambiguous values cannot accidentally disable native sign-in validation."""
    declaration["ai_tools"]["authenticate"] = value
    with pytest.raises(ValueError, match="boolean"):
        AiToolsNormalizer().normalize(declaration)


@pytest.mark.parametrize("orca", [{}, {"version": "latest"}, {"version": "1.2.3-rc.1"}])
def test_orca_requires_a_configured_stable_release(with_tool_versions, orca):
    """Orca must have an explicit stable version before installation."""
    config = with_tool_versions({})["development"]
    config["ai_tools"]["orca"] = orca
    with pytest.raises(ValueError, match=r"development\.ai_tools\.orca\.version must be a stable release"):
        AiToolsNormalizer().normalize(config)


def test_mcp_authentication_checks_preserve_explicit_arguments(declaration):
    """Only explicitly declared service checks run, with normalized optional fields."""
    server = declaration["ai_tools"]["mcp_servers"][0]
    assert AiToolsNormalizer().normalize(declaration)["mcp_servers"][0]["auth_check"] == {}
    check = {"tool": "whoami", "arguments": {"scope": "read"}, "expect_text": "authorized"}
    server["auth_check"] = deepcopy(check)
    assert AiToolsNormalizer().normalize(declaration)["mcp_servers"][0]["auth_check"] == check
    server["auth_check"] = {"tool": "whoami"}
    assert AiToolsNormalizer().normalize(declaration)["mcp_servers"][0]["auth_check"] == {
        "tool": "whoami",
        "arguments": {},
        "expect_text": "",
    }


@pytest.mark.parametrize(
    "check",
    [
        "whoami",
        {"tool": ""},
        {"tool": "read", "arguments": []},
        {"tool": "read", "expect_text": 42},
        {"tool": "read", "unknown": "synthetic-secret"},
    ],
)
def test_mcp_authentication_checks_reject_invalid_declarations(declaration, check):
    """Invalid service check metadata fails before credentials or clients are accessed."""
    declaration["ai_tools"]["mcp_servers"][0]["auth_check"] = check
    with pytest.raises(ValueError) as error:
        AiToolsNormalizer().normalize(declaration)
    assert "synthetic-secret" not in str(error.value)


def test_named_bitwarden_selector_resolves_before_runtime_credentials(declaration):
    """Named private item IDs reach the existing credential resolver without mutating declarations."""
    declaration["ai_tools"]["mcp_servers"][0]["env"]["TOKEN"] = {"bitwarden_secret": "example-key"}
    original = deepcopy(declaration)
    servers = AiToolsNormalizer().normalize(declaration, bitwarden={"example-key": UUID})["mcp_servers"]
    assert declaration == original
    assert servers[0]["env"]["TOKEN"] == {"bitwarden_item_id": UUID, "field": "login.password"}
    assert AiToolsRuntime.credential_ids(servers) == [UUID]
    runtime = AiToolsRuntime().servers(servers, "/home/fixture", [{"id": UUID, "login": {"password": "synthetic-key"}}])
    assert runtime["example"]["env"]["TOKEN"] == "synthetic-key"


@pytest.mark.parametrize("identifier", [None, "", " "])
def test_empty_named_selector_rejects_unauthenticated_configuration(declaration, identifier):
    """Declared credentials require a vault item before any clients are configured."""
    declaration["ai_tools"]["mcp_servers"][0]["env"]["TOKEN"] = {"bitwarden_secret": "example-key"}
    with pytest.raises(ValueError, match="Bitwarden UUID"):
        AiToolsNormalizer().normalize(declaration, bitwarden={"example-key": identifier})


@pytest.mark.parametrize(
    "reference",
    [
        {"bitwarden_secret": "unknown"},
        {"bitwarden_secret": []},
        {"bitwarden_secret": "example-key", "bitwarden_item_id": UUID},
        {"bitwarden_secret": "example-key", "field": []},
        {"bitwarden_item_id": None},
        {"bitwarden_item_id": ""},
        {},
    ],
)
def test_invalid_named_or_direct_credential_references_fail(declaration, reference):
    """Unknown names, ambiguous selectors and invalid fields cannot silently disable credentials."""
    declaration["ai_tools"]["mcp_servers"][0]["env"]["TOKEN"] = reference
    with pytest.raises(ValueError):
        AiToolsNormalizer().normalize(declaration, bitwarden={"example-key": ""})
