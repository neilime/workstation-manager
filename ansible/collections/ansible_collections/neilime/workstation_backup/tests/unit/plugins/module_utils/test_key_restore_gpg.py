"""Exercise remote GPG restoration with disposable real keys when GPG is available."""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile
import unittest

from ansible_collections.neilime.workstation_backup.plugins.module_utils.key_restore import (
    restore_key,
)
from ansible_collections.neilime.workstation_backup.plugins.module_utils.key_sync import (
    BitwardenGpgKeySyncPlanner,
)

GPG_FINGERPRINT_PREFIX = "fpr:"  # codespell:ignore fpr


@unittest.skipUnless(shutil.which("gpg") and shutil.which("gpgconf"), "real GPG tests run in the Lima VM")
class GpgRestoreTests(unittest.TestCase):
    """Verified import must preserve other keys and must not silently keep stale trust."""

    def setUp(self) -> None:
        # Keep generated keys private and register cleanup even if fixture setup fails.
        # pylint: disable-next=consider-using-with
        self.root = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = self.root / "source"
        self.source.mkdir(mode=0o700)
        self.home = self.root / "home"
        self.home.mkdir()
        self.local = self.home / ".gnupg"
        self.addCleanup(self.stop_agents)
        self.gpg(
            self.source,
            "--passphrase",
            "",
            "--quick-generate-key",
            "Fixture <fixture@example.invalid>",
            "ed25519",
            "sign",
            "0",
        )
        listing = self.gpg(self.source, "--with-colons", "--list-secret-keys")
        self.fingerprint = next(
            line.split(":")[9] for line in listing.splitlines() if line.startswith(GPG_FINGERPRINT_PREFIX)
        )
        self.item: dict = {
            "id": "fixture-gpg",
            "name": "Fixture",
            "fields": [
                {"name": "fingerprint", "value": self.fingerprint},
                {
                    "name": "private_key",
                    "value": self.gpg(self.source, "--armor", "--export-secret-keys", self.fingerprint),
                },
                {"name": "public_key", "value": self.gpg(self.source, "--armor", "--export", self.fingerprint)},
                {"name": "ownertrust", "value": self.fingerprint + ":6:\n"},
            ],
        }

    def stop_agents(self) -> None:
        """Stop only agents associated with this test's disposable keyrings."""

        for home in (self.source, self.local):
            subprocess.run(
                ["gpgconf", "--homedir", str(home), "--kill", "all"], check=False, capture_output=True, timeout=10
            )

    @staticmethod
    def gpg(home: pathlib.Path, *arguments: str) -> str:
        """Keep generated material in process memory rather than test output."""

        result = subprocess.run(
            ["gpg", "--homedir", str(home), "--batch", "--pinentry-mode", "loopback", *arguments],
            capture_output=True,
            check=True,
            timeout=30,
        )
        return result.stdout.decode()

    @staticmethod
    def run_command(arguments: list[str], *, data=None, binary_data=True, encoding=None) -> tuple[int, bytes, bytes]:
        """Match the Ansible runner contract using only disposable keyring commands."""

        assert binary_data and encoding is None
        result = subprocess.run(arguments, input=data, capture_output=True, check=False, timeout=60)
        return result.returncode, result.stdout, result.stderr

    def restore(self, *, check=False) -> bool:
        """Invoke the same restore helper used by the production Ansible module."""

        return restore_key(
            "gpg", str(self.home), self.item, self.fingerprint, run_command=self.run_command, check_mode=check
        )

    def test_restore_is_verified_and_idempotent(self) -> None:
        """Private/public material and ownertrust must converge without repeated writes."""

        self.assertTrue(self.restore())
        self.assertFalse(self.restore())
        self.assertIn(self.fingerprint + ":6:", self.gpg(self.local, "--export-ownertrust"))
        self.assertEqual(
            self.gpg(self.local, "--armor", "--export", self.fingerprint),
            self.gpg(self.source, "--armor", "--export", self.fingerprint),
        )

    def test_missing_key_preview_does_not_create_a_keyring(self) -> None:
        """Check mode validates the remote key in staging without creating local state."""

        self.assertTrue(self.restore(check=True))
        self.assertFalse(self.local.exists())

    def test_absent_remote_trust_clears_old_local_trust_and_converges(self) -> None:
        """Undefined trust must not reappear as drift on the next backup."""

        self.restore()
        self.item["fields"] = [field for field in self.item["fields"] if field["name"] != "ownertrust"]
        self.assertTrue(self.restore())
        trust = next(
            line
            for line in self.gpg(self.local, "--export-ownertrust").splitlines()
            if line.startswith(self.fingerprint + ":")
        )
        self.assertEqual(trust, self.fingerprint + ":2:")
        local: dict = {
            "fingerprint": self.fingerprint,
            "private_key": self.gpg(self.local, "--armor", "--export-secret-keys", self.fingerprint),
            "public_key": self.gpg(self.local, "--armor", "--export", self.fingerprint),
            "ownertrust": trust,
        }
        self.assertEqual(BitwardenGpgKeySyncPlanner().build([local], [self.item]), [])
        self.assertFalse(self.restore())

    def test_extra_local_packets_are_preserved_but_fail_verification(self) -> None:
        """Remote import must not delete local-only identities or claim they were replaced."""

        self.restore()
        self.gpg(self.local, "--passphrase", "", "--quick-add-uid", self.fingerprint, "Local <local@example.invalid>")
        before = self.gpg(self.local, "--armor", "--export", self.fingerprint)
        with self.assertRaisesRegex(ValueError, "Local-only key packets were preserved"):
            self.restore()
        self.assertEqual(before, self.gpg(self.local, "--armor", "--export", self.fingerprint))

    def test_fingerprint_mismatch_does_not_create_local_state(self) -> None:
        """Untrusted vault armor must match the declared approved fingerprint before import."""

        wrong = "A" * 40
        self.item["fields"][0]["value"] = wrong
        self.item["fields"][-1]["value"] = wrong + ":6:\n"
        with self.assertRaisesRegex(ValueError, "does not match"):
            restore_key("gpg", str(self.home), self.item, wrong, run_command=self.run_command)
        self.assertFalse(self.local.exists())


if __name__ == "__main__":
    unittest.main()
