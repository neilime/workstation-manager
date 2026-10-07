"""Regression tests for collection installation in the shell entrypoint."""

# These collection-install fixtures intentionally mirror the entrypoint's
# broader shell-wrapper tests while focusing on ansible-galaxy retry behavior.
# pylint: disable=duplicate-code

from __future__ import annotations

import pathlib
import subprocess
import tempfile
import unittest

from entrypoint_test_helpers import entrypoint_source_with_mock_controller

ENTRYPOINT_PATH = pathlib.Path(__file__).parents[2] / "workstation.sh"


class CollectionInstallRetryTests(unittest.TestCase):
    """Retry collection bootstrap failures without leaking temporary manifests."""

    def test_collection_install_retries_after_transient_failure(self) -> None:
        """Collection bootstrap should retry transient ansible-galaxy failures."""

        definitions = entrypoint_source_with_mock_controller().splitlines()
        self.assertEqual(definitions.pop(), 'main "$@"')
        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            repository = fixture / "repository"
            requirements = repository / "ansible/collections/requirements.yml"
            requirements.parent.mkdir(parents=True)
            requirements.write_text("collections: []\n")
            wrapper = fixture / "wrapper-definitions.sh"
            wrapper.write_text("\n".join(definitions) + "\n")
            ansible_galaxy_log = fixture / "ansible-galaxy.log"
            ansible_galaxy_attempts = fixture / "ansible-galaxy-attempts.txt"
            ansible_galaxy = fixture / "ansible-galaxy"
            ansible_galaxy.write_text(
                "#!/bin/sh\n"
                "attempt=0\n"
                'if [ -f "$TEST_ANSIBLE_GALAXY_ATTEMPTS" ]; then\n'
                '  attempt="$(cat "$TEST_ANSIBLE_GALAXY_ATTEMPTS")"\n'
                "fi\n"
                "attempt=$((attempt + 1))\n"
                'printf "%s\\n" "$attempt" >"$TEST_ANSIBLE_GALAXY_ATTEMPTS"\n'
                'printf "%s\\n" "$*" >>"$TEST_ANSIBLE_GALAXY_LOG"\n'
                'if [ "$attempt" -lt 2 ]; then\n'
                '  printf "%s\\n" "synthetic transient failure" >&2\n'
                "  exit 1\n"
                "fi\n"
                "exit 0\n"
            )
            ansible_galaxy.chmod(0o700)
            sleep = fixture / "sleep"
            sleep.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >>"$TEST_SLEEP_LOG"\n')
            sleep.chmod(0o700)
            for name in ("wget", "curl"):
                downloader = fixture / name
                downloader.write_text("#!/bin/sh\nexit 99\n")
                downloader.chmod(0o700)
            sleep_log = fixture / "sleep.log"
            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    '. "$1"\n'
                    'REPOSITORY_URL="$2"\n'
                    'COLLECTIONS_INSTALL_DIR="/tmp/collections"\n'
                    "install_collection_requirements\n",
                    "entrypoint-test",
                    str(wrapper),
                    str(repository),
                ],
                env={
                    "PATH": f"{fixture}:/usr/bin:/bin",
                    "HOME": temporary_dir,
                    "TEST_ANSIBLE_GALAXY_LOG": str(ansible_galaxy_log),
                    "TEST_ANSIBLE_GALAXY_ATTEMPTS": str(ansible_galaxy_attempts),
                    "TEST_SLEEP_LOG": str(sleep_log),
                },
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(ansible_galaxy_attempts.read_text().strip(), "2")
            self.assertEqual(sleep_log.read_text().splitlines(), ["5"])
            self.assertIn(
                f"collection install -r {requirements} -p /tmp/collections",
                ansible_galaxy_log.read_text(),
            )
            self.assertIn(
                "Ansible collection install failed; retrying (attempt 2/3)",
                result.stdout,
            )

    def test_remote_collection_install_cleans_up_temp_manifest_on_retry_failure(
        self,
    ) -> None:
        """A failed remote collection install should still remove its temporary manifest."""

        definitions = entrypoint_source_with_mock_controller().splitlines()
        self.assertEqual(definitions.pop(), 'main "$@"')
        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            wrapper = fixture / "wrapper-definitions.sh"
            wrapper.write_text("\n".join(definitions) + "\n")
            tmpdir = fixture / "tmp"
            tmpdir.mkdir()
            ansible_galaxy_attempts = fixture / "ansible-galaxy-attempts.txt"
            ansible_galaxy = fixture / "ansible-galaxy"
            ansible_galaxy.write_text(
                "#!/bin/sh\n"
                "attempt=0\n"
                'if [ -f "$TEST_ANSIBLE_GALAXY_ATTEMPTS" ]; then\n'
                '  attempt="$(cat "$TEST_ANSIBLE_GALAXY_ATTEMPTS")"\n'
                "fi\n"
                "attempt=$((attempt + 1))\n"
                'printf "%s\\n" "$attempt" >"$TEST_ANSIBLE_GALAXY_ATTEMPTS"\n'
                'printf "%s\\n" "synthetic persistent failure" >&2\n'
                "exit 1\n"
            )
            ansible_galaxy.chmod(0o700)
            for name, output_option in (("wget", "-O"), ("curl", "-o")):
                downloader = fixture / name
                downloader.write_text(
                    "#!/bin/sh\n"
                    'destination=""\n'
                    'while [ "$#" -gt 0 ]; do\n'
                    f'  if [ "$1" = "{output_option}" ]; then\n'
                    '    destination="$2"\n'
                    "    shift 2\n"
                    "    continue\n"
                    "  fi\n"
                    "  shift\n"
                    "done\n"
                    'printf "%s\\n" "collections: []" >"$destination"\n'
                )
                downloader.chmod(0o700)
            sleep = fixture / "sleep"
            sleep.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >>"$TEST_SLEEP_LOG"\n')
            sleep.chmod(0o700)
            sleep_log = fixture / "sleep.log"
            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    '. "$1"\n'
                    'REPOSITORY_URL="https://github.com/example/workstation-manager.git"\n'
                    'REPOSITORY_BRANCH="main"\n'
                    'COLLECTIONS_INSTALL_DIR="/tmp/collections"\n'
                    "install_collection_requirements\n",
                    "entrypoint-test",
                    str(wrapper),
                ],
                env={
                    "PATH": f"{fixture}:/usr/bin:/bin",
                    "HOME": temporary_dir,
                    "TEST_ANSIBLE_GALAXY_ATTEMPTS": str(ansible_galaxy_attempts),
                    "TEST_SLEEP_LOG": str(sleep_log),
                    "TMPDIR": str(tmpdir),
                },
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(ansible_galaxy_attempts.read_text().strip(), "3")
            self.assertEqual(sleep_log.read_text().splitlines(), ["5", "5"])
            self.assertEqual(list(tmpdir.glob("workstation-manager-requirements-*")), [])
