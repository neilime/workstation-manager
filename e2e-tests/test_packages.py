"""Check the configured APT inventory in a single VM query."""


def test_declared_apt_packages_are_installed(host, workstation_config) -> None:
    """Package selections belong to configuration, not a copied test checklist."""
    system = workstation_config["system"]["packages"]
    expected = set(
        system["prerequisites"]
        + system["apt"]
        + workstation_config["development"]["packages"]
        + workstation_config["development"]["editor_packages"]
    )
    inventory = host.check_output("dpkg-query -W -f='${Package}\\t${db:Status-Status}\\n'")
    installed = {
        name for name, status in (line.split("\t") for line in inventory.splitlines()) if status == "installed"
    }
    assert not expected - installed, f"Missing APT packages: {sorted(expected - installed)}"
