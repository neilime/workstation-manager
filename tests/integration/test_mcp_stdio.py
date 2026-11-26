"""Exercise MCP processes and private service checks using isolated fixtures."""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.ai.mcp_stdio import (
    McpStdioSession,
)
from ansible_test_helpers import (
    SETUP_ROLES,
    ansible_environment,
    managed_user,
    run_playbook,
    write_local_playbook,
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


@pytest.fixture(name="authentication_endpoint")
def authentication_endpoint_fixture():
    """Serve authenticated account metadata with exhausted query quota, without external traffic."""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        """Reject bad bearer credentials and offer a redirect that must never be followed."""

        def do_GET(self):  # pylint: disable=invalid-name
            """Keep all recorded values synthetic and outside Ansible's output."""
            authorization = self.headers.get("Authorization")
            requests.append((self.path, authorization))
            status = 200 if authorization == "Bearer synthetic-http-secret" else 401
            if self.path == "/redirect":
                status = 302
            self.send_response(status)
            if status == 302:
                self.send_header("Location", "/unexpected")
            payload = json.dumps({"remaining": 0, "account": "synthetic-private-response"}).encode()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):  # pylint: disable=redefined-builtin
            """Keep fixture request data out of the test output."""

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", requests
        finally:
            server.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive()


@pytest.mark.parametrize("scenario", ["authorized", "unauthorized", "redirect", "tool-error", "preview", "header"])
def test_service_authentication_preserves_privacy_and_requires_declared_checks(
    tmp_path, authentication_endpoint, scenario
):
    """Real Ansible verifies both check forms, rejects failures, and skips all probes in previews."""
    endpoint, requests = authentication_endpoint
    script = tmp_path / "server.py"
    script.write_text(SERVER)
    token = "invalid" if scenario == "unauthorized" else "synthetic-http-secret"
    if scenario == "header":
        token += "\rprivate-header"
    # An unrelated .netrc must never replace the explicitly selected bearer key.
    (tmp_path / ".netrc").write_text("machine 127.0.0.1 login unrelated password synthetic-netrc-secret\n")
    (tmp_path / ".netrc").chmod(0o600)
    command = "/not-installed" if scenario == "preview" else sys.executable
    path = "/redirect" if scenario == "redirect" else "/usage"
    variables = {
        "workstation_manager_resolved": {"user": managed_user(tmp_path)},
        "workstation_ai_config": {
            "mcp_servers": [
                {"name": "http", "auth_check": {"url": endpoint + path, "bearer_env": "TOKEN"}},
                {
                    "name": "tool",
                    "auth_check": {"tool": "fixture", "arguments": {"scope": "read"}, "expect_text": "authorized"},
                },
            ]
        },
        "workstation_ai_servers": {
            # Calling a tool on this server fails: HTTPS checks must use the endpoint.
            "http": {"command": command, "args": [str(script), "denied"], "env": {"TOKEN": token}},
            "tool": {
                "command": command,
                "args": [str(script), "denied" if scenario == "tool-error" else "ok"],
                "env": {},
            },
        },
    }
    # Configuration tests enforce HTTPS; only this isolated transport fixture uses loopback HTTP.
    playbook = write_local_playbook(
        tmp_path / "verify.json",
        [{"ansible.builtin.import_tasks": str(SETUP_ROLES / "ai_tools/tasks/mcp/verify.yml")}],
        variables,
    )
    argv = ["ansible-playbook", "-vvv", "-i", "localhost,", str(playbook)]
    if scenario == "preview":
        argv.append("--check")
    result = run_playbook(argv, ansible_environment(tmp_path), cwd=tmp_path)
    output = result.stdout + result.stderr
    assert (result.returncode == 0) is (scenario in {"authorized", "preview"}), output
    assert "changed=0" in output
    for marker in ("synthetic-http-secret", "synthetic-private-response", "synthetic-netrc-secret", "private-header"):
        assert marker not in output
    if scenario in {"tool-error", "preview", "header"}:
        assert requests == []
    else:
        assert requests == [(path, "Bearer " + token)]
