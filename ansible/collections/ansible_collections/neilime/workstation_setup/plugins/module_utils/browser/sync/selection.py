"""The managed Brave recovery scope, shared by inspection and native setup."""

from __future__ import annotations

# These are Chromium preference names, not diagnostic model names. History uses
# the persisted typed_urls key even though the current model is named History.
SYNC_SELECTION = {
    "apps": True,
    "bookmarks": True,
    "extensions": True,
    "preferences": True,
    "themes": True,
    "typed_urls": True,
    "autofill": False,
    "cookies": False,
    "passwords": False,
    "payments": False,
    "product_comparison": False,
    "reading_list": False,
    "saved_tab_groups": False,
    "tabs": False,
}

NATIVE_SELECTED_TYPES = ("apps", "bookmarks", "extensions", "preferences", "themes", "typedUrls")


def selection_matches(state: dict) -> bool:
    """Require explicit selection; omitted individual preferences default to false."""

    selected = state.get("selected_types", {})
    return state.get("keep_everything_synced") is False and all(
        selected.get(name, False) is enabled for name, enabled in SYNC_SELECTION.items()
    )
