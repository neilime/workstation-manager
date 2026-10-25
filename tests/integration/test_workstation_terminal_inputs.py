"""Check supplied bootstrap inputs with a real controlling terminal."""

import pytest
from entrypoint_input_helpers import assert_supplied_inputs, prepare_input_runner


@pytest.mark.parametrize("pipelining", [None, "false"])
def test_supplied_inputs_preserve_terminal_context(tmp_path, pipelining):
    """Credentials and pipelining survive terminal capture and sudo without leaking secrets."""
    input_runner = prepare_input_runner(tmp_path)
    if pipelining is not None:
        input_runner[1]["ANSIBLE_PIPELINING"] = pipelining
    assert_supplied_inputs(input_runner, [], terminal=True, status=0)
