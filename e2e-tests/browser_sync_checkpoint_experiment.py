"""Qualify the experimental download checkpoint with synthetic data in a Lima VM."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import time
from pathlib import Path

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser.cdp import (
    BrowserPipe,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser.lifecycle import (
    automation_arguments,
    browser_processes,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser.profiles.preferences import (
    PROFILE_PREFERENCES_SCRIPT,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser.sync.native import (
    NativeSync,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desktop.session import (
    DesktopSession,
)
from browser_recovery_checkpoint_probe import CheckpointProbe
from browser_sync_fixture import BrowserSyncFixture, device_identity
from browser_sync_network_gate import SyncNetworkGate

# EntitySpecifics field numbers identify protocol types, not browser releases.
_TYPES = [32904, 37702]  # Bookmarks, Preferences.
_PREFERENCE = {"browser.show_home_button": True}


class SyntheticProfile:
    """Read actual bookmark and preference APIs without exporting their contents."""

    def __init__(self, pipe: BrowserPipe, root: Path) -> None:
        self.pipe = pipe
        self.native = NativeSync(pipe, str(root / "Default"))
        self.bookmarks = pipe.page("brave://bookmarks")

    def create(self, marker: str) -> None:
        """Create a unique synthetic bookmark; the caller owns the fresh profile."""

        value = json.dumps({"title": marker, "url": "https://example.invalid/" + marker})
        if (
            self.pipe.evaluate(
                self.bookmarks,
                f"(async () => {{ await chrome.bookmarks.create({value}); return true; }})()",
            )
            is not True
        ):
            raise ValueError("Synthetic bookmark creation failed")

    def preference(self, *, apply: bool) -> bool:
        """Read or set one synced preference using the native settings API."""

        result = self.pipe.evaluate(
            self.native.settings,
            f"{PROFILE_PREFERENCES_SCRIPT}({json.dumps(_PREFERENCE)}, {json.dumps(apply)})",
        )
        if not isinstance(result, dict) or result.get("supported") is not True:
            raise ValueError("Synthetic preference interface is unavailable")
        return result.get("matches") is True

    def matches(self, marker: str) -> bool:
        """Require the expected title, URL, and preference in the receiving models."""

        return self.pipe.evaluate(
            self.bookmarks,
            "(async marker => {"
            " const nodes = await chrome.bookmarks.search({url: 'https://example.invalid/' + marker});"
            " return nodes.length === 1 && nodes[0].title === marker;"
            f"}})({json.dumps(marker)})",
        ) is True and self.preference(apply=False)

    def activity(self) -> None:
        """Keep an unrelated bookmark changing while the receiver verifies fixed data."""

        if (
            self.pipe.evaluate(
                self.bookmarks,
                "(async () => {"
                " const nodes = await chrome.bookmarks.search({url: 'https://example.invalid/noise'});"
                " if (nodes.length !== 1) return false;"
                " await chrome.bookmarks.update(nodes[0].id, {title: 'noise-' + Date.now()});"
                " return true;"
                "})()",
            )
            is not True
        ):
            raise ValueError("Synthetic background activity failed")


def fixture(directory: Path, name: str) -> BrowserSyncFixture:
    """Keep each profile's ownership record outside its browser data tree."""

    return BrowserSyncFixture(directory / name / "browser", directory / name / "devices.json")


def arguments(root: Path, network: SyncNetworkGate | None = None) -> list[str]:
    """Use the installed browser, desktop keyring, sandbox, and bounded test scheduling."""

    result = automation_arguments("/usr/bin/brave-browser", str(root), "Default")
    result += ["--sync-short-nudge-delay-for-test", "--sync-short-initial-retry-override"]
    if network is not None:
        result += [f"--proxy-server={network.proxy_url}", "--disable-quic"]
    return result


def experiment(directory: Path) -> None:
    """Exercise fresh recovery, interruption, continuation, and persistent device identity."""

    source, receiver = (fixture(directory, name) for name in ("source", "receiver"))
    source.prepare()
    receiver.prepare()
    environment = DesktopSession.environment()
    started = time.monotonic()
    with BrowserPipe(arguments(source.root), environment) as source_pipe:
        author = SyntheticProfile(source_pipe, source.root)
        code = author.native.code()
        author.native.restore(code)
        author.create("checkpoint-first")
        author.create("noise")
        if not author.preference(apply=True):
            raise ValueError("Could not set the synthetic synced preference")
        print("Source created; testing fresh receiver with concurrent bookmark changes.", flush=True)
        with BrowserPipe(arguments(receiver.root), environment) as receiver_pipe:
            reader = SyntheticProfile(receiver_pipe, receiver.root)
            reader.native.restore(code)
            probe = CheckpointProbe(receiver_pipe, _TYPES)
            if not probe.wait(lambda: reader.matches("checkpoint-first"), timeout=120, activity=author.activity):
                raise ValueError(f"Fresh receiver did not verify the expected synthetic data: {probe.summary()}")
            if not reader.native.wait(timeout=30):
                raise ValueError(f"Production recovery incomplete: {reader.native.pending_reason}")
            print(
                f"Fresh receiver passed; busy cycle sampled: {probe.busy_observed}; "
                f"busy at completion: {probe.busy_at_success}.",
                flush=True,
            )
        identity = device_identity(receiver.root / "Default", require_initialized=True)
        author.create("checkpoint-after-interruption")
        with SyncNetworkGate() as network, BrowserPipe(arguments(receiver.root, network), environment) as receiver_pipe:
            reader = SyntheticProfile(receiver_pipe, receiver.root)
            if reader.native.code() != code:
                raise ValueError("Receiver lost its encrypted recovery state on restart")
            probe = CheckpointProbe(receiver_pipe, _TYPES)
            if reader.matches("checkpoint-after-interruption") or probe.wait(
                lambda: reader.matches("checkpoint-after-interruption"), timeout=10
            ):
                raise ValueError("Blocked receiver incorrectly accepted stale recovery evidence")
            if reader.native.wait(timeout=3):
                raise ValueError("Production recovery accepted a blocked receiver")
            print("Blocked receiver rejected stale data; restoring network access.", flush=True)
            network.release()
            receiver_pipe.evaluate(probe.page, "chrome.send('triggerRefresh'); true")
            if not probe.wait(lambda: reader.matches("checkpoint-after-interruption"), timeout=120):
                raise ValueError(f"Receiver did not finish after network access returned: {probe.summary()}")
            if not reader.native.wait(timeout=30) or not reader.matches("checkpoint-after-interruption"):
                raise ValueError(f"Production recovery did not resume: {reader.native.pending_reason}")
        if device_identity(receiver.root / "Default", require_initialized=True) != identity:
            raise ValueError("Recovery changed the receiver device identity")
    print(
        f"Synthetic recovery, interruption, and identity checks passed in {time.monotonic() - started:.1f}s.",
        flush=True,
    )


def cleanup(directory: Path) -> None:
    """Require server-confirmed removal before deleting any fixture recovery state."""

    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Fixture cleanup requires its original directory")
    failures = []
    completed = []
    for name in ("receiver", "source"):
        owned = fixture(directory, name)
        if owned.manifest.parent.is_symlink():
            raise ValueError("Refusing a linked fixture directory")
        if not owned.manifest.exists():
            continue
        try:
            if browser_processes(owned.root):
                raise ValueError("A fixture browser is still running; retain its recovery state and VM")
            if owned.load().get("phase") == "prepared":
                owned.capture(require_initialized=True)
            owned.leave()
            completed.append(owned.manifest.parent)
        except (OSError, ValueError) as error:
            failures.append(error)
    if failures:
        raise ExceptionGroup("Fixture teardown incomplete; retain this directory and VM for cleanup", failures)
    for owned_directory in completed:
        shutil.rmtree(owned_directory)
    directory.rmdir()


def main() -> None:
    """Keep live service work opt-in and restricted to a disposable Lima guest."""

    if not platform.node().startswith("lima-"):
        raise SystemExit("Run this experiment inside the Lima VM.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "cleanup"))
    parser.add_argument("--directory", type=Path, required=True)
    options = parser.parse_args()
    directory = options.directory.expanduser().absolute()
    if options.action == "cleanup":
        cleanup(directory)
        return
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        experiment(directory)
    finally:
        cleanup(directory)


if __name__ == "__main__":
    main()
