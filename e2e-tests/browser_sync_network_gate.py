"""Hold native browser HTTPS connections until the E2E Sync observer is installed."""

from __future__ import annotations

import ipaddress
import re
import select
import socket
import socketserver
import threading
import time
from types import TracebackType
from typing import Self
from urllib.parse import urlsplit

_IO_TIMEOUT = 5
_HEADER_LIMIT = 8192
_MAX_CONNECTIONS = 32


def _connect_host(request: bytes) -> str:
    """Accept only an unambiguous HTTPS CONNECT authority, without logging it."""

    method, authority, version = request.decode("ascii").split(" ")
    target = urlsplit("//" + authority)
    host = target.hostname
    if method != "CONNECT" or version != "HTTP/1.1" or not host or target.port != 443:
        raise ValueError("Unsupported tunnel request")
    if any((target.username is not None, target.password is not None, target.path, target.query, target.fragment)):
        raise ValueError("Unsupported tunnel authority")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
        if len(host) > 253 or not re.fullmatch(rf"(?:{label}\.)*{label}\.?", host):
            raise ValueError("Invalid tunnel host") from None
    return host


def _read_request(client: socket.socket) -> tuple[str, bytes]:
    """Bound HTTP headers and retain any bytes already sent for the opaque tunnel."""

    header = bytearray()
    deadline = time.monotonic() + _IO_TIMEOUT
    while b"\r\n\r\n" not in header:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Tunnel headers did not complete")
        client.settimeout(remaining)
        chunk = client.recv(min(4096, _HEADER_LIMIT - len(header)))
        if not chunk:
            raise ValueError("Incomplete tunnel headers")
        header.extend(chunk)
        if len(header) >= _HEADER_LIMIT:
            raise ValueError("Tunnel headers exceeded their limit")
    headers, pending = bytes(header).split(b"\r\n\r\n", 1)
    return _connect_host(headers.split(b"\r\n", 1)[0]), pending


def _relay(client: socket.socket, upstream: socket.socket, stopped: threading.Event) -> None:
    """Copy opaque bytes in either direction until closure or fixture shutdown."""

    while not stopped.is_set():
        readable, _, _ = select.select([client, upstream], [], [], 0.1)
        for source in readable:
            data = source.recv(65536)
            if not data:
                return
            (upstream if source is client else client).sendall(data)


class _ConnectHandler(socketserver.BaseRequestHandler):
    """Relay opaque TLS bytes without interpreting or reporting browser traffic."""

    server: _GateServer
    request: socket.socket

    def handle(self) -> None:
        gate = self.server.gate
        client = self.request
        if not gate.track(client):
            return
        try:
            client.settimeout(_IO_TIMEOUT)
            try:
                host, pending = _read_request(client)
            except ValueError:
                client.sendall(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
                return
            client.settimeout(_IO_TIMEOUT)
            if not gate.released.wait(120) or gate.stopped.is_set():
                return
            with gate.connect(host) as upstream:
                if not gate.track(upstream):
                    return
                try:
                    client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    if pending:
                        upstream.sendall(pending)
                    _relay(client, upstream, gate.stopped)
                finally:
                    gate.untrack(upstream)
        except OSError, ValueError:
            # Closing or malformed connections are expected. Never include
            # authorities, request headers, or protocol payloads in diagnostics.
            return
        finally:
            gate.untrack(client)


class _GateServer(socketserver.ThreadingTCPServer):
    """Keep an OS DNS lookup from preventing bounded fixture shutdown."""

    daemon_threads = True

    def __init__(self, gate: SyncNetworkGate) -> None:
        self.gate = gate
        self._slots = threading.BoundedSemaphore(_MAX_CONNECTIONS)
        super().__init__(("127.0.0.1", 0), _ConnectHandler)

    def process_request(
        self, request: socket.socket | tuple[bytes, socket.socket], client_address: tuple[str, int]
    ) -> None:
        if not isinstance(request, socket.socket):
            raise TypeError("The HTTPS gate requires a TCP connection")
        # Nonblocking admission hands the slot to the worker, which releases it.
        # pylint: disable-next=consider-using-with
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(
        self, request: socket.socket | tuple[bytes, socket.socket], client_address: tuple[str, int]
    ) -> None:
        worker = threading.current_thread()
        with self.gate.lock:
            self.gate.workers.add(worker)
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self.gate.lock:
                self.gate.workers.discard(worker)
            self._slots.release()


class SyncNetworkGate:
    """Expose a loopback CONNECT proxy that preserves browser TLS verification."""

    def __init__(self) -> None:
        self.released = threading.Event()
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self.workers: set[threading.Thread] = set()
        self._connections: set[socket.socket] = set()
        self._server = _GateServer(self)
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05})

    @property
    def proxy_url(self) -> str:
        """Return the loopback address used by the browser's proxy flag."""

        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(
        self, _kind: type[BaseException] | None, _error: BaseException | None, _traceback: TracebackType | None
    ) -> None:
        self.stopped.set()
        self.released.set()
        self._server.shutdown()
        with self.lock:
            for connection in self._connections:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            workers = list(self.workers)
        self._server.server_close()
        self._thread.join()
        deadline = time.monotonic() + _IO_TIMEOUT
        for worker in workers:
            worker.join(max(0, deadline - time.monotonic()))

    def release(self) -> None:
        """Allow upstream connections only after the caller has installed its observer."""

        self.released.set()

    def track(self, connection: socket.socket) -> bool:
        """Register each socket so shutdown can interrupt pending reads and writes."""

        with self.lock:
            if self.stopped.is_set():
                return False
            self._connections.add(connection)
        return True

    def untrack(self, connection: socket.socket) -> None:
        """Forget a connection only after its relay has finished."""

        with self.lock:
            self._connections.discard(connection)

    @staticmethod
    def connect(host: str) -> socket.socket:
        """Connect to the requested HTTPS endpoint with a finite connection timeout."""

        # Socket timeouts do not bound libc DNS. A delayed daemon worker checks
        # stopped after connecting and cannot relay data after fixture shutdown.
        return socket.create_connection((host, 443), timeout=_IO_TIMEOUT)
