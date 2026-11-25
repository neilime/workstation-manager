"""Qualify actual extension and web-app installation readback without a remote chain."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser.cdp import (
    BrowserPipe,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser.sync.installed_data import (
    BrowserInstalledData,
)


class _Application(BaseHTTPRequestHandler):
    """Serve an installable synthetic application exclusively on the VM loopback interface."""

    # Match BaseHTTPRequestHandler's keyword-compatible signature.
    def log_message(self, format, *args) -> None:  # pylint: disable=redefined-builtin
        """Suppress request logs; the fixture reports only verification outcomes."""

    def do_GET(self) -> None:  # pylint: disable=invalid-name
        """Provide the manifest, icon, and minimal HTML needed by native installation."""

        if self.path == "/manifest.json":
            data = json.dumps(
                {
                    "name": "Recovery fixture",
                    "id": "/identity",
                    "start_url": "/",
                    "display": "standalone",
                    "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}],
                }
            ).encode()
            mime = "application/manifest+json"
        elif self.path == "/icon.svg":
            data = (
                b'<svg xmlns="http://www.w3.org/2000/svg" width="192" height="192"><rect width="192" he'
                b'ight="192" fill="blue"/></svg>'
            )
            mime = "image/svg+xml"
        else:
            data = (
                b'<!doctype html><html><head><link rel="manifest" href="/manifest.json"><title>Recovery'
                b" fixture</title></head><body>Fixture</body></html>"
            )
            mime = "text/html"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def installed_applications(pipe: BrowserPipe) -> None:
    """Downloaded metadata must not pass until real installation APIs confirm each item."""

    extensions_page = pipe.page("brave://extensions")
    extensions = pipe.evaluate(
        extensions_page,
        "(async () => (await chrome.developerPrivate.getExtensionsInfo({includeDisabled:true}))"
        ".filter(item => item.name === 'Recovery fixture').map(item => item.id))()",
    )
    assert isinstance(extensions, list) and len(extensions) == 1, "The synthetic extension did not load"
    extension_id = extensions[0]
    with ThreadingHTTPServer(("127.0.0.1", 0), _Application) as server:
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        try:
            origin = f"http://127.0.0.1:{server.server_port}"
            groups = [
                {
                    "type": "Extensions",
                    "nodes": [
                        {
                            "metadata": {},
                            "SPECIFICS": {
                                "extension": {"id": extension_id, "enabled": True},
                            },
                        }
                    ],
                },
                {
                    "type": "Web Apps",
                    "nodes": [
                        {
                            "metadata": {},
                            "SPECIFICS": {
                                "web_app": {"start_url": origin + "/", "relative_manifest_id": "identity"},
                            },
                        }
                    ],
                },
            ]
            installed = BrowserInstalledData(pipe, "(async()=>" + json.dumps(groups) + ")")
            page = pipe.page("brave://sync-internals")
            assert not installed.matches(page), "A missing application was accepted as installed"
            assert installed.pending_reason == "Installed web apps", "The loaded extension did not pass native readback"
            pipe.call("PWA.install", {"manifestId": origin + "/identity", "installUrlOrBundleUrl": origin + "/"})
            assert installed.matches(page), "A completed installation failed native readback"
            pipe.call("PWA.uninstall", {"manifestId": origin + "/identity"})
            assert not installed.matches(page), "A removed application remained verified"
        finally:
            server.shutdown()
            worker.join()
    print("Real extension and web-app installation readback rejected missing and removed applications.", flush=True)
