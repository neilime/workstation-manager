"""Exercise the stdio probe against disposable synthetic MCP processes."""

import sys

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.mcp_stdio import (
    McpStdioSession,
)

SERVER = r"""
import json, os, sys, time
if os.environ.get('HOME') and os.getcwd() != os.environ['HOME']:
    sys.exit(4)
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method = request['method']
    if method == 'initialize':
        result = {'protocolVersion': '2025-11-25', 'capabilities': {'tools': {}}}
    elif sys.argv[1] == 'timeout':
        time.sleep(10)
    elif sys.argv[1] == 'error':
        print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'error': {'message': 'synthetic-secret'}}), flush=True)
        continue
    elif method == 'tools/call':
        assert request['params'] == {'name': 'fixture', 'arguments': {'scope': 'read'}}
        result = {'content': [{'type': 'text', 'text': 'authorized'}]}
        if sys.argv[1] == 'denied':
            result = {'isError': True, 'content': [{'type': 'text', 'text': 'synthetic-secret'}]}
        elif sys.argv[1] == 'text-error':
            result = {'content': [{'type': 'text', 'text': 'synthetic-secret: invalid API key'}]}
        elif sys.argv[1] == 'malformed':
            result = {'content': [{'type': 'text', 'text': {'private': 'synthetic-secret'}}]}
    else:
        result = {'tools': [{'name': 'fixture'}]}
    notification = {'jsonrpc': '2.0', 'method': 'notifications/message', 'params': {'data': 'synthetic-secret'}}
    print(json.dumps(notification), flush=True)
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
"""


def test_initialization_notifications_and_discovery_use_the_same_process(tmp_path):
    """Initialization notifications and discovery use the same process."""
    script = tmp_path / "server.py"
    script.write_text(SERVER)
    with McpStdioSession(sys.executable, [str(script), "ok"], {"HOME": str(tmp_path)}, 2) as session:
        assert session.tools() == ["fixture"]


@pytest.mark.parametrize("mode", ["error", "timeout"])
def test_server_failures_are_bounded_and_do_not_expose_output(tmp_path, mode):
    """Server failures are bounded and do not expose output."""
    script = tmp_path / "server.py"
    script.write_text(SERVER)
    with McpStdioSession(sys.executable, [str(script), mode], {}, 1) as session:
        with pytest.raises(ValueError) as error:
            session.tools()
        assert "synthetic-secret" not in str(error.value)


def test_declared_authentication_check_requires_a_successful_service_response(tmp_path):
    """Successful discovery and a read-only tool call establish declared access."""
    script = tmp_path / "server.py"
    script.write_text(SERVER)
    with McpStdioSession(sys.executable, [str(script), "ok"], {}, 2) as session:
        session.check_access(
            {"tool": "fixture", "arguments": {"scope": "read"}, "expect_text": "authorized"}, session.tools()
        )


@pytest.mark.parametrize("mode", ["denied", "text-error", "malformed"])
def test_service_errors_cannot_pass_as_successful_authentication(tmp_path, mode):
    """Both MCP error flags and plain-text credential failures stop setup privately."""
    script = tmp_path / "server.py"
    script.write_text(SERVER)
    with McpStdioSession(sys.executable, [str(script), mode], {}, 2) as session:
        with pytest.raises(ValueError) as error:
            session.check_access(
                {"tool": "fixture", "arguments": {"scope": "read"}, "expect_text": "authorized"}, session.tools()
            )
        assert "synthetic-secret" not in str(error.value)


def test_authentication_check_requires_an_advertised_tool(tmp_path):
    """A misspelled or removed check cannot silently skip service validation."""
    script = tmp_path / "server.py"
    script.write_text(SERVER)
    with (
        McpStdioSession(sys.executable, [str(script), "ok"], {}, 2) as session,
        pytest.raises(ValueError, match="did not advertise"),
    ):
        session.check_access({"tool": "missing", "arguments": {}, "expect_text": ""}, session.tools())
