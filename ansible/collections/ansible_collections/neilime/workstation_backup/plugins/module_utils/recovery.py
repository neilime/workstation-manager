"""Validate and render the shared backup recovery decision contract."""

from __future__ import annotations

import re
import textwrap

RECOVERY_SCOPES = frozenset(("chezmoi", "ssh-keys", "gpg-keys", "browser-recovery", "browser-sync"))


def recovery_decision_id(value: object) -> str:
    """Accept stable internal decision IDs without admitting arbitrary fact names."""

    if not isinstance(value, str) or re.fullmatch(r"[a-z][a-z0-9-]*", value) is None:
        raise ValueError("Recovery decision IDs must use lowercase letters, digits, and dashes")
    return value


def _message(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Recovery decision messages must be nonempty text")
    return "".join(character if character.isprintable() or character == "\n" else " " for character in value).strip()


def recovery_decision(request: dict) -> dict:
    """Build a safe prompt with explicit actions, skip, and abort; never a default approval."""

    fields = {"scope", "summary", "actions", "skip", "abort_message"}
    if not isinstance(request, dict) or set(request) != fields:
        raise ValueError("Recovery decisions require only scope, summary, actions, skip, and abort_message")
    scope = request["scope"]
    if not isinstance(scope, str) or scope not in RECOVERY_SCOPES:
        raise ValueError("Recovery decisions must identify a known recovery category")
    actions = request["actions"]
    if not isinstance(actions, dict) or not actions:
        raise ValueError("Recovery decisions require at least one explicit action")
    choices = []
    action_lines = []
    for action, description in actions.items():
        recovery_decision_id(action)
        if action in {"skip", "abort"}:
            raise ValueError("Skip and abort are supplied by the shared recovery decision flow")
        choices.append(action)
        action_lines.extend(textwrap.wrap(f"{action} = {_message(description)}", width=88, subsequent_indent="  "))
    action_lines.extend(textwrap.wrap(f"skip = {_message(request['skip'])}", width=88, subsequent_indent="  "))
    action_lines.extend(
        (
            "  Recovery stays unverified; local changes are not added to the archive.",
            "abort = stop backup without creating an archive",
        )
    )
    choices.extend(("skip", "abort"))
    summary = _message(request["summary"])
    return {
        "scope": scope,
        "summary": summary,
        "choices": choices,
        "prompt": "\n\n".join((summary, "\n".join(action_lines), f"Choose [{'/'.join(choices)}]")),
        "abort_message": _message(request["abort_message"]),
    }
