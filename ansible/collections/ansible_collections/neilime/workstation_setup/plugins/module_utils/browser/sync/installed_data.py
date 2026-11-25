"""Read back asynchronous extension and web-app installation after Sync applies data."""

from __future__ import annotations

import json
import re

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser.cdp import (
    BrowserPipe,
    BrowserProtocolError,
)

_EXPECTED = r"""(async () => {
  const groups = await GET_NODES(1000);
  if (!Array.isArray(groups)) return null;
  const extensions = [];
  const webApps = [];
  for (const group of groups) {
    if (!['Extensions', 'Apps', 'Web Apps'].includes(group.type)) continue;
    for (const node of group.nodes) {
      if (!node.metadata) continue;
      const specifics = node.SPECIFICS;
      if (group.type === 'Web Apps') {
        const app = specifics?.web_app;
        if (typeof app?.start_url !== 'string') return null;
        const start = new URL(app.start_url);
        const manifest = Object.hasOwn(app, 'relative_manifest_id')
          ? new URL('/' + app.relative_manifest_id, start) : start;
        manifest.hash = '';
        const first = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(manifest.href));
        const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', first));
        webApps.push([...digest.slice(0, 16)].map(byte =>
          String.fromCharCode(97 + (byte >> 4), 97 + (byte & 15))).join(''));
      } else {
        const extension = group.type === 'Apps' ? specifics?.app?.extension : specifics?.extension;
        if (typeof extension?.id !== 'string' || typeof extension.enabled !== 'boolean') return null;
        extensions.push({id: extension.id, enabled: extension.enabled});
      }
    }
  }
  return {extensions, webApps};
})()"""


# This reader retains native page handles between bounded installation polls.
# pylint: disable-next=too-few-public-methods
class BrowserInstalledData:
    """Keep app identifiers in private IPC memory; names, URLs and contents never leave their page."""

    def __init__(self, pipe: BrowserPipe, nodes_script: str) -> None:
        self.pipe = pipe
        self.expected_script = _EXPECTED.replace("GET_NODES", nodes_script)
        self.extensions_page: str | None = None
        self.web_apps_page: str | None = None
        self.pending_reason = "Application inventory"

    def matches(self, diagnostics: str) -> bool:
        """Do not count downloaded installation requests or pending web-app stubs as restored applications."""

        expected = self.pipe.evaluate(diagnostics, self.expected_script, timeout=5)
        if expected is None:
            self.pending_reason = "Application inventory"
            return False
        if not isinstance(expected, dict) or set(expected) != {"extensions", "webApps"}:
            raise BrowserProtocolError("Brave returned unsupported application inventory")
        extensions, web_apps = expected["extensions"], expected["webApps"]
        if (
            not isinstance(extensions, list)
            or not isinstance(web_apps, list)
            or any(
                not isinstance(item, dict) or set(item) != {"id", "enabled"} or not isinstance(item["enabled"], bool)
                for item in extensions
            )
            or any(
                not isinstance(identity, str) or not re.fullmatch(r"[a-p]{32}", identity)
                for identity in [*(item["id"] for item in extensions), *web_apps]
            )
        ):
            raise BrowserProtocolError("Brave returned unsupported application inventory")
        if extensions:
            self.extensions_page = self.extensions_page or self.pipe.page("brave://extensions")
            script = (
                "(async () => {"
                " const installed = await chrome.developerPrivate.getExtensionsInfo({includeDisabled: true,"
                " includeTerminated: true});"
                f" return {json.dumps(extensions)}.every(expected => installed.some(item =>"
                " item.id === expected.id && item.state === (expected.enabled ? 'ENABLED' : 'DISABLED')));"
                "})()"
            )
            if self.pipe.evaluate(self.extensions_page, script) is not True:
                self.pending_reason = "Installed extensions and apps"
                return False
        if web_apps:
            self.web_apps_page = self.web_apps_page or self.pipe.page("brave://web-app-internals")
            script = (
                "(async () => { const {browserProxyFactory} = await import('./web_app_internals.mojom-webui.js');"
                " const response = await browserProxyFactory.getInstance().handler.getDebugInfoAsJsonString();"
                " const details = JSON.parse(response.result)?.InstalledWebApps?.Details;"
                f" return Array.isArray(details) && {json.dumps(web_apps)}.every(id => details.some(app =>"
                " app['!app_id'] === id && app.is_from_sync_and_pending_installation === false"
                # WebApp::AsDebugValue serializes the proto enum numerically.
                # 0 is a completed synced registration without OS integration;
                # 1 and 2 are installed apps with and without OS integration.
                " && app.is_uninstalling === false && ['0', '1', '2'].includes(app.install_state))); })()"
            )
            if self.pipe.evaluate(self.web_apps_page, script) is not True:
                self.pending_reason = "Installed web apps"
                return False
        self.pending_reason = ""
        return True
