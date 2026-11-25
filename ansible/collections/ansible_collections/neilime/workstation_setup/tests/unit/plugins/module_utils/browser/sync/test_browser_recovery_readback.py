"""Recovery must verify actual extension and application installation."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser.cdp import (
    BrowserProtocolError,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser.sync.installed_data import (
    BrowserInstalledData,
)


def test_downloaded_apps_require_actual_installation_readback() -> None:
    """A downloaded request must remain incomplete until both native installation APIs confirm it."""

    inventory = {"extensions": [{"id": "a" * 32, "enabled": False}], "webApps": ["b" * 32]}
    pipe = Mock()
    pipe.evaluate.side_effect = [inventory, False, inventory, True, False, inventory, True, True]
    installed = BrowserInstalledData(pipe, "syntheticNodes")
    assert not installed.matches("diagnostics")
    assert installed.pending_reason == "Installed extensions and apps"
    assert not installed.matches("diagnostics")
    assert installed.pending_reason == "Installed web apps"
    assert installed.matches("diagnostics")


def test_unsupported_inventory_is_rejected_without_reporting_browser_data() -> None:
    """Native data must satisfy the identifier schema before it enters another browser page."""

    pipe = Mock()
    pipe.evaluate.return_value = {"extensions": [{"id": "private-value", "enabled": True}], "webApps": []}
    with pytest.raises(BrowserProtocolError, match="unsupported application inventory") as error:
        BrowserInstalledData(pipe, "syntheticNodes").matches("diagnostics")
    assert "private-value" not in str(error.value)
    pipe.page.assert_not_called()
