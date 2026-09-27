"""Shared arguments for native browser profile initialization and inspection."""

from __future__ import annotations


def browser_profile_argument_spec() -> dict:
    """Return a fresh schema with encrypted avatar data protected from logs."""

    return {
        "user_data_dir": {"type": "path", "required": True},
        "profiles": {
            "type": "list",
            "elements": "dict",
            "default": [],
            "options": {
                "id": {"type": "str", "required": True},
                "label": {"type": "str"},
                "directory": {"type": "str"},
                "item_id": {"type": "str", "required": True},
                "theme_colors": {"type": "list", "elements": "str"},
                "avatar_attachment_id": {"type": "str"},
                "avatar_png": {"type": "str", "no_log": True},
            },
        },
    }
