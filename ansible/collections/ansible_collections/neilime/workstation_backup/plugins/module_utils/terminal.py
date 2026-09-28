"""Render interactive backup prompts independently of terminal output processing."""

from __future__ import annotations


def terminal_prompt(text: object) -> str:
    """Return each prompt line to column one, including when Ansible disables OPOST."""

    if not isinstance(text, str):
        raise ValueError("A terminal prompt must be a string")
    # ansible-pull may relay the prompt after pause has already switched stdin's
    # terminal to raw mode. Start each line with a carriage return: Display
    # normalizes CRLF to LF, so conventional CRLF endings would be lost.
    return "\n".join("\r" + line for line in text.strip("\r\n").splitlines())
