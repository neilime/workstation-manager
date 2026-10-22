"""Check supplied bootstrap inputs with a real controlling terminal."""

from entrypoint_input_helpers import assert_supplied_inputs, prepare_input_runner


def test_supplied_inputs_preserve_terminal_context(tmp_path):
    """Prefilled credentials preserve the real terminal and remain absent from output."""
    assert_supplied_inputs(prepare_input_runner(tmp_path), [], terminal=True, status=0)
