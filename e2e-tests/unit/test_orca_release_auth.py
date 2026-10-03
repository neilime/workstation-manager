"""Exercise Orca release authentication with real Ansible and a local HTTP fixture."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ansible.parsing.dataloader import DataLoader

TASK_FILE = (
    pathlib.Path(__file__).parents[2]
    / "ansible/collections/ansible_collections/neilime/workstation_setup/roles/orca/tasks/main.yml"
)
TOKEN = "synthetic-orca-release-token"


class OrcaReleaseAuthTests(unittest.TestCase):
    """Release reads must authenticate safely without installing or downloading Orca."""

    def setUp(self) -> None:
        # pylint: disable-next=consider-using-with
        self.fixture = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.requests: list[tuple[str, str | None]] = []
        requests = self.requests

        class ReleaseHandler(BaseHTTPRequestHandler):
            """Model GitHub's anonymous rate limit, redirects, and error responses."""

            def do_GET(self) -> None:  # pylint: disable=invalid-name
                """Record only synthetic request credentials and return fixture metadata."""
                authorization = self.headers.get("Authorization")
                requests.append((self.path, authorization))
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/release")
                    self.end_headers()
                    return
                status = 200
                payload = {
                    "tag_name": "v1.2.3",
                    "assets": [
                        {
                            "name": "orca-ide_1.2.3_amd64.deb",
                            "browser_download_url": "https://example.invalid/orca.deb",
                            "digest": "sha256:" + "a" * 64,
                        }
                    ],
                }
                if self.path == "/failure" or (self.path == "/auth" and authorization != "Bearer " + TOKEN):
                    status = 403
                    payload = {"message": "API rate limit exceeded; received " + str(authorization)}
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

            # Match the standard-library callback signature, including its parameter name.
            def log_message(self, format, *args) -> None:  # pylint: disable=redefined-builtin
                """Keep the HTTP fixture quiet; assertions inspect requests directly."""

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ReleaseHandler)
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)

    def fetch(self, *, token: str | None, path: str = "/auth", check: bool = False) -> subprocess.CompletedProcess[str]:
        """Execute the production release lookup and asset checks against the local fixture."""
        tasks = DataLoader().load_from_file(str(TASK_FILE))
        uri_task = next(task for task in tasks if "ansible.builtin.uri" in task)
        end = next(index for index, task in enumerate(tasks) if "ansible.builtin.package_facts" in task)
        tasks = tasks[:end]
        uri_task["ansible.builtin.uri"]["url"] = f"http://127.0.0.1:{self.server.server_port}{path}"
        variables = {
            "ansible_python_interpreter": sys.executable,
            "ansible_facts": {"architecture": "x86_64"},
            "workstation_manager": {"development": {"orca": {"settings": {}}}},
            "workstation_manager_resolved": {
                "user": {
                    "projects_directory": "/home/fixture/Documents/dev-projects",
                    "home": "/home/fixture",
                }
            },
        }
        playbook = self.fixture / "playbook.json"
        play = {
            "name": "Resolve Orca release metadata from the local fixture",
            "hosts": "localhost",
            "gather_facts": False,
            "vars": variables,
            "tasks": tasks,
        }
        playbook.write_text(json.dumps([play]))
        config = self.fixture / "ansible.cfg"
        config.write_text("[defaults]\n")
        environment = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.fixture),
            "LC_ALL": "C.UTF-8",
            "ANSIBLE_CONFIG": str(config),
            "ANSIBLE_HOME": str(self.fixture / ".ansible"),
        }
        if token is not None:
            environment["WORKSTATION_MANAGER_GITHUB_TOKEN"] = token
        # Verbose output must not reveal even the request headers on failure.
        command = ["ansible-playbook", "-vvv", "-i", "localhost,", "-c", "local", str(playbook)]
        if check:
            command.append("--check")
        return subprocess.run(
            command, cwd=self.fixture, env=environment, check=False, capture_output=True, text=True, timeout=60
        )

    def test_token_authenticates_release_lookup_in_normal_and_check_mode(self) -> None:
        """Both setup and preview can resolve releases when anonymous API access is exhausted."""
        for check in (False, True):
            with self.subTest(check=check):
                result = self.fetch(token=TOKEN, check=check)
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, 0, output)
                self.assertEqual(self.requests[-1], ("/auth", "Bearer " + TOKEN))
                self.assertNotIn(TOKEN, output)
                self.assertRegex(output, r"changed=0\s")

    def test_optional_token_preserves_anonymous_requests(self) -> None:
        """Missing and empty tokens must not send an empty Authorization header."""
        for token in (None, ""):
            with self.subTest(token=token):
                result = self.fetch(token=token, path="/release")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.requests[-1], ("/release", None))

    def test_supplied_token_takes_precedence_over_netrc(self) -> None:
        """An unrelated netrc login must not replace the explicit manager token."""
        netrc = self.fixture / ".netrc"
        netrc.write_text("machine 127.0.0.1 login fixture password synthetic-netrc-password\n")
        netrc.chmod(0o600)
        result = self.fetch(token=TOKEN)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.requests, [("/auth", "Bearer " + TOKEN)])

    def test_redirect_does_not_forward_token(self) -> None:
        """Only the original release endpoint should receive the manager credential."""
        result = self.fetch(token=TOKEN, path="/redirect")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.requests, [("/redirect", "Bearer " + TOKEN), ("/release", None)])

    def test_authenticated_failure_is_redacted(self) -> None:
        """A failed response echoing its credential must not expose it in Ansible output."""
        result = self.fetch(token=TOKEN, path="/failure")
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.requests, [("/failure", "Bearer " + TOKEN)])
        self.assertIn("censored", output)
        self.assertNotIn(TOKEN, output)

    def test_failure_without_token_remains_diagnosable(self) -> None:
        """Anonymous API failures must still fail and retain actionable error details."""
        result = self.fetch(token=None, path="/failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("API rate limit exceeded", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
