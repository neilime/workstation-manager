"""End-to-end checks for configured Flatpak applications and update ownership."""


def test_gnome_software_owns_flatpak_updates(host) -> None:
    """GNOME Software manages updates for the installed Flatpak applications."""
    assert host.package("gnome-software").is_installed
    assert host.package("gnome-software-plugin-flatpak").is_installed
    assert host.check_output("dbus-run-session -- gsettings get org.gnome.software download-updates") == "true"


def test_declared_flatpak_remote_and_applications(host, workstation_config) -> None:
    """One inventory query covers desktop applications."""
    config = workstation_config["desktop"]["flatpak"]
    remotes = host.check_output("flatpak remotes --system --columns=name").splitlines()
    assert config["remote"] in remotes
    expected = set(config["packages"])
    installed = set(host.check_output("flatpak list --system --app --columns=application").splitlines())
    assert not expected - installed, f"Missing Flatpak applications: {sorted(expected - installed)}"
