"""End-to-end checks for workstation data preservation during cleanup."""


def test_cleanup_preserves_all_native_browser_profiles_and_internal_data(host) -> None:
    """Undeclared native profiles and Brave internal directories must survive cleanup."""

    user_home = host.check_output("printf '%s' \"$HOME\"")
    root = f"{user_home}/.config/BraveSoftware/Brave-Browser"
    unmanaged_paths = [f"{root}/managed-e2e-stale", f"{root}/Profile 9999"]
    internal_path = f"{root}/e2e-component-cache"
    for profile_path in unmanaged_paths:
        assert host.file(f"{profile_path}/Preferences").exists
        assert host.file(f"{profile_path}/e2e-preserve-marker").content_string == "preserve\n"
    assert host.file(f"{internal_path}/e2e-preserve-marker").content_string == "preserve\n"
