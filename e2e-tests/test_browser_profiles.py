"""End-to-end checks for selectable native Brave profiles."""

import json


def native_profiles(host):
    """Read the native profile registry from the isolated test workstation."""

    user_home = host.check_output("printf '%s' \"$HOME\"")
    root = f"{user_home}/.config/BraveSoftware/Brave-Browser"
    state = json.loads(host.file(f"{root}/Local State").content_string)
    profiles = state["profile"]["info_cache"]
    assert profiles
    return root, profiles


def test_primary_browser_profiles_are_registered(host) -> None:
    """Profiles loaded from Bitwarden appear in Brave's native profile picker."""
    root, profiles = native_profiles(host)
    current_user = host.check_output("whoami")
    for directory, metadata in profiles.items():
        profile = host.file(f"{root}/{directory}")
        assert profile.is_directory
        assert profile.user == current_user
        prefs = json.loads(host.file(f"{root}/{directory}/Preferences").content_string)
        assert prefs["profile"]["name"] == metadata["name"]
        assert metadata["name"]
