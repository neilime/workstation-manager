"""End-to-end checks for the system tests."""

from pathlib import Path


def test_supported_ubuntu_and_isolated_controller(host) -> None:
    """The guest and bootstrap controller use the same baseline as development tooling."""
    expected = (Path(__file__).parents[1] / "ansible/ubuntu-version").read_text().strip()
    assert host.check_output(". /etc/os-release; printf '%s' \"$VERSION_ID\"") == expected
    expected_core = (Path(__file__).parents[1] / "ansible/requirements.txt").read_text().strip().split("==")[1]
    version = host.check_output("/opt/workstation-manager/venv/bin/ansible-pull --version")
    assert f"core {expected_core}" in version
    assert host.run("/opt/workstation-manager/venv/bin/python -m pip check").succeeded


def test_snap_is_absent_and_cannot_be_reinstalled_by_apt(host) -> None:
    """Setup removes packages, services, mounts, and state and blocks dependency reinstalls."""
    for package in ("snapd", "gnome-software-plugin-snap"):
        assert not host.package(package).is_installed
    for path in ("/snap", "/var/snap", "/var/lib/snapd", "/var/cache/snapd", f"{host.user().home}/snap"):
        assert not host.file(path).exists
    assert not host.service("snapd.socket").is_running
    assert "Candidate: (none)" in host.check_output("apt-cache policy snapd")
    assert not host.run("findmnt --noheadings --types squashfs").stdout.strip()


def test_system_locale_configuration(host, workstation_config) -> None:
    """The installed machine should persist the configured locale."""
    content = host.file("/etc/default/locale").content_string
    locale = workstation_config["system"]["locale"]
    values = dict(line.split("=", 1) for line in content.splitlines() if "=" in line)
    assert values["LANG"].strip('"') == locale
    assert values["LC_ALL"].strip('"') == locale


def test_system_timezone_configuration(host, workstation_config) -> None:
    """The installed machine should persist the configured timezone."""
    timezone = workstation_config["system"]["timezone"]
    assert host.file("/etc/timezone").content_string.strip() == timezone
    assert host.check_output("readlink -f /etc/localtime") == f"/usr/share/zoneinfo/{timezone}"


def test_system_state_file(host) -> None:
    """The installation should write the system state marker."""

    # Arrange
    system_state = host.file("/etc/workstation-manager-v1/system.json")

    # Act
    is_managed = system_state.contains('"managed": true')

    # Assert
    assert system_state.exists
    assert is_managed


def test_lima_network_uses_networkd_renderer(host) -> None:
    """Desktop installation must not replace Lima's network renderer."""

    # Act
    renderer = host.check_output("sudo netplan get network.renderer")
    networkd = host.service("systemd-networkd")

    # Assert
    assert renderer == "networkd"
    assert networkd.is_running
