"""Keep collection metadata and the maintained CI image aligned with the runtime."""

import ast
import re
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet

ROOT = Path(__file__).resolve().parents[2]


def test_first_party_collections_support_the_pinned_controller():
    """A controller upgrade must remain inside every first-party support declaration."""
    requirement = Requirement((ROOT / "ansible/requirements.txt").read_text().strip())
    core_version = next(iter(requirement.specifier)).version
    runtime_files = list((ROOT / "ansible/collections/ansible_collections/neilime").glob("*/meta/runtime.yml"))
    assert runtime_files
    for runtime_file in runtime_files:
        runtime = DataLoader().load_from_file(str(runtime_file))
        assert core_version in SpecifierSet(runtime["requires_ansible"]), runtime_file


def test_sanity_image_update_rule_extracts_the_configured_tag_and_digest():
    """Renovate must update the actual CI image without crossing Core release series."""
    filename = ".github/workflows/__shared-ci.yml"
    configuration = (ROOT / ".github/renovate/renovate-config.json5").read_text()
    manager = re.search(
        r"managerFilePatterns: (\[[^\n]+\]),\n\s+matchStrings: \[\n\s+"
        r'("sanity-image: [^\n]+),\n\s+\],\n\s+datasourceTemplate: "docker",\n\s+'
        r'versioningTemplate: "regex:([^"\n]+)"',
        configuration,
    )
    assert manager is not None
    assert any(re.search(pattern.strip("/"), filename) for pattern in ast.literal_eval(manager.group(1)))
    pattern = ast.literal_eval(manager.group(2)).replace("(?<", "(?P<")
    content = (ROOT / filename).read_text()
    extracted = [match.groupdict() for match in re.finditer(pattern, content)]
    assert len(extracted) == 1
    dependency = extracted[0]
    workflow = DataLoader().load(content)
    step = next(step for step in workflow["jobs"]["static-ansible"]["steps"] if "sanity-image" in step.get("with", {}))
    assert step["with"]["sanity-image"] == (
        f"{dependency['depName']}:{dependency['currentValue']}@{dependency['currentDigest']}"
    )
    versioning = ast.literal_eval(f'"{manager.group(3)}"').replace("(?<", "(?P<")
    version = re.fullmatch(versioning, dependency["currentValue"])
    assert version is not None
    core_version = (ROOT / "ansible/requirements.txt").read_text().strip().split("==")[1]
    assert version["compatibility"] == "v" + core_version.rsplit(".", 1)[0]
    assert re.fullmatch(versioning, "v99.7-12").groupdict() == {"compatibility": "v99.7", "patch": "12"}
