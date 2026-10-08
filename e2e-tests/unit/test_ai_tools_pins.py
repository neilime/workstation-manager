"""Check AI package extraction against the active Renovate annotation expression."""

import ast
import re
from pathlib import Path

from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state_ai_tools import (
    AiToolsNormalizer,
)

ROOT = Path(__file__).resolve().parents[2]


def test_every_public_ai_package_and_github_tool_pin_is_extracted(public_defaults, private_overrides):
    """Use maintained versions and the real manager pattern rather than copied pins."""
    configuration = (ROOT / ".github/renovate/renovate-config.json5").read_text()
    expression = next(line.strip().rstrip(",") for line in configuration.splitlines() if "# renovate:" in line)
    # This manager uses ordinary character classes and named captures, shared by RE2 and Python.
    pattern = ast.literal_eval(expression).replace("(?<", "(?P<")
    extracted = [match.groupdict() for match in re.finditer(pattern, (ROOT / "ansible/group_vars/all.yml").read_text())]
    config = AiToolsNormalizer().normalize(
        public_defaults["development"], bitwarden=private_overrides["secrets"]["bitwarden"]
    )
    for provider in config["providers"].values():
        assert {"datasource": "npm", "depName": provider["npm"], "currentValue": provider["version"]} in extracted
    for server in config["mcp_servers"]:
        if server["npm"]:
            assert {
                "datasource": "npm",
                "depName": server["npm"]["package"],
                "currentValue": server["npm"]["version"],
            } in extracted
    assert {
        "datasource": "github-releases",
        "depName": "stablyai/orca",
        "currentValue": config["orca"]["version"],
    } in extracted
    for tool, version in public_defaults["development"]["mise"]["tools"].items():
        if tool.startswith("github:"):
            assert {
                "datasource": "github-releases",
                "depName": tool.removeprefix("github:"),
                "currentValue": version,
            } in extracted


def test_skill_source_annotations_and_public_pins_are_extracted(public_defaults, private_overrides):
    """The source annotation extracts immutable digests, including any selected public skills."""
    filename = "ansible/group_vars/all.yml"
    configuration = (ROOT / ".github/renovate/renovate-config.json5").read_text()
    manager = re.search(
        r"managerFilePatterns: (\[[^\n]+\]),\n\s+matchStrings: \[\n\s+"
        r"('# renovate: datasource=git-refs [^\n]+)",
        configuration,
    )
    assert manager is not None
    assert any(re.search(pattern.strip("/"), filename) for pattern in ast.literal_eval(manager.group(1)))
    pattern = ast.literal_eval(manager.group(2).rstrip(",")).replace("(?<", "(?P<")
    digest = "a" * 40
    for prefix in ("", "https://github.com/"):
        fixture = (
            "# renovate: datasource=git-refs depName=example/skills branch=main\n"
            f'          source: "{prefix}example/skills/tree/{digest}/skills/review"\n'
        )
        assert re.search(pattern, fixture).groupdict() == {
            "depName": "example/skills",
            "currentValue": "main",
            "currentDigest": digest,
        }
    content = (ROOT / filename).read_text()
    extracted = [match.groupdict() for match in re.finditer(pattern, content)]
    skills = AiToolsNormalizer().normalize(
        public_defaults["development"], bitwarden=private_overrides["secrets"]["bitwarden"]
    )["skills"]
    git_skills = [skill for skill in skills if skill["kind"] == "remote"]
    assert len(extracted) == len(git_skills)
    for skill in git_skills:
        assert any(
            skill["source"]
            .removeprefix("https://github.com/")
            .startswith(f"{match['depName']}/tree/{match['currentDigest']}/")
            and match["currentValue"]
            for match in extracted
        )
