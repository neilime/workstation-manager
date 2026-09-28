"""Preserve status columns while formatting prompts for raw or cooked terminals."""

from __future__ import annotations

import pytest
from ansible_collections.neilime.workstation_backup.plugins.module_utils.terminal import (
    terminal_prompt,
)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_prompt_lines_include_carriage_returns(newline: str) -> None:
    """A heading, blank separator, and Git status entries must keep their columns."""

    text = newline.join(["Source changes:", " M file", "D  other", "", "Choose [retry/abort]"])
    assert terminal_prompt(text) == "\rSource changes:\n\r M file\n\rD  other\n\r\n\rChoose [retry/abort]"


def test_template_boundary_newlines_are_removed() -> None:
    """A Jinja filter block must not introduce blank lines around the prompt."""

    assert terminal_prompt("\nChoose [retry/abort]\n") == "\rChoose [retry/abort]"


def test_prompt_rejects_non_text() -> None:
    """Invalid input must fail instead of displaying an object's representation."""

    with pytest.raises(ValueError, match="must be a string"):
        terminal_prompt(None)
