"""Check configured APT packages against the VM's cached repository candidates."""

import json


def test_declared_apt_packages_are_current(host, workstation_config) -> None:
    """Setup installs configured packages and applies available updates without requiring downgrades."""
    system = workstation_config["system"]["packages"]
    expected = set(
        system["prerequisites"]
        + system["apt"]
        + workstation_config["development"]["packages"]
        + workstation_config["development"]["editor_packages"]
    )
    script = """
import apt
import apt_pkg
import json
import sys

cache = apt.Cache()
failures = {}
for specification in json.loads(sys.argv[1]):
    name, separator, version = specification.partition("=")
    package = cache[name] if name in cache else None
    if package is None or package.installed is None:
        failures[name] = "not installed"
    elif separator and package.installed.version != version:
        failures[name] = {"installed": package.installed.version, "required": version}
    elif not separator and package.candidate is not None:
        if apt_pkg.version_compare(package.installed.version, package.candidate.version) < 0:
            failures[name] = {"installed": package.installed.version, "candidate": package.candidate.version}
print(json.dumps(failures))
"""
    failures = json.loads(host.check_output("/usr/bin/python3 -c %s %s", script, json.dumps(sorted(expected))))
    assert not failures, f"APT packages outside the desired state: {failures}"
