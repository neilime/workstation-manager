"""Verify native Sync traffic gating with real sockets and synthetic opaque payloads."""

from __future__ import annotations

import importlib.util
import socket
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

import pytest

MODULE_PATH = Path(__file__).parents[2] / "e2e-tests/browser_sync_network_gate.py"
SPEC = importlib.util.spec_from_file_location("browser_sync_network_gate", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
network_gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(network_gate)


def connect_proxy(gate) -> socket.socket:
    """Open the fixture's real loopback listener without any external service."""

    endpoint = urlsplit(gate.proxy_url)
    return socket.create_connection((endpoint.hostname, endpoint.port), timeout=1)


def test_gate_defers_connections_then_relays_opaque_bytes(monkeypatch, capsys) -> None:
    """No upstream socket opens before release; afterwards TLS bytes pass unchanged both ways."""

    threads = set(threading.enumerate())
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        server.settimeout(0.1)
        with network_gate.SyncNetworkGate() as gate:
            connector = mock.Mock(side_effect=lambda _host: socket.create_connection(server.getsockname(), timeout=1))
            monkeypatch.setattr(gate, "connect", connector)
            with connect_proxy(gate) as client:
                client.sendall(b"CONNECT sync.example.invalid:443 HTTP/1.1\r\nHost: sync.example.invalid:443\r\n\r\n")
                with pytest.raises(TimeoutError):
                    server.accept()
                connector.assert_not_called()
                gate.release()
                assert client.recv(4096) == b"HTTP/1.1 200 Connection Established\r\n\r\n"
                upstream, _address = server.accept()
                with upstream:
                    upstream.settimeout(1)
                    client.sendall(b"\x16\x03\x03synthetic-private-request")
                    assert upstream.recv(4096) == b"\x16\x03\x03synthetic-private-request"
                    upstream.sendall(b"\x17\x03\x03synthetic-private-response")
                    assert client.recv(4096) == b"\x17\x03\x03synthetic-private-response"
                connector.assert_called_once_with("sync.example.invalid")
    assert not set(threading.enumerate()) - threads
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "request_line",
    [
        b"GET https://sync.example.invalid/ HTTP/1.1",
        b"CONNECT sync.example.invalid:80 HTTP/1.1",
        b"CONNECT user:private@sync.example.invalid:443 HTTP/1.1",
        b"CONNECT sync.example.invalid:443/path HTTP/1.1",
        b"CONNECT malformed:443:443 HTTP/1.1",
        b"CONNECT \xff:443 HTTP/1.1",
    ],
)
def test_gate_rejects_unsupported_requests_without_connecting(request_line, monkeypatch, capsys) -> None:
    """Only well-formed HTTPS authorities can initiate a tunnel, and rejected traffic stays private."""

    with network_gate.SyncNetworkGate() as gate:
        connector = mock.Mock(side_effect=AssertionError("Unexpected upstream connection"))
        monkeypatch.setattr(gate, "connect", connector)
        gate.release()
        with connect_proxy(gate) as client:
            client.sendall(request_line + b"\r\n\r\n")
            assert client.recv(4096).startswith(b"HTTP/1.1 400 ")
        connector.assert_not_called()
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("headers_complete", [False, True])
def test_gate_shutdown_closes_waiting_connections_and_joins_threads(headers_complete) -> None:
    """Closing the gate interrupts partial headers and pending CONNECTs without waiting for their deadlines."""

    threads = set(threading.enumerate())
    started = time.monotonic()
    with ExitStack() as connections:
        with network_gate.SyncNetworkGate() as gate:
            client = connections.enter_context(connect_proxy(gate))
            client.sendall(b"CONNECT sync.example.invalid:443 HTTP/1.1" + (b"\r\n\r\n" if headers_complete else b""))
        try:
            assert client.recv(4096) == b""
        except ConnectionResetError:
            # Shutdown can reject a connection before its headers are consumed.
            pass
    assert time.monotonic() - started < 2
    assert not set(threading.enumerate()) - threads


def test_gate_bounds_pending_connections_and_reuses_closed_slots(monkeypatch) -> None:
    """An overfull gate rejects sockets promptly and admits new requests after existing clients close."""

    monkeypatch.setattr(network_gate, "_MAX_CONNECTIONS", 2)
    with network_gate.SyncNetworkGate() as gate, ExitStack() as connections:
        first = connections.enter_context(connect_proxy(gate))
        connections.enter_context(connect_proxy(gate))
        with connect_proxy(gate) as overflow:
            assert overflow.recv(4096) == b""
        first.close()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with connect_proxy(gate) as replacement:
                try:
                    replacement.sendall(b"GET / HTTP/1.1\r\n\r\n")
                    response = replacement.recv(4096)
                except ConnectionResetError, BrokenPipeError:
                    response = b""
                if response.startswith(b"HTTP/1.1 400 "):
                    break
            time.sleep(0.01)
        else:
            pytest.fail("The gate did not release its closed connection slot")


def test_gate_times_out_incomplete_headers_without_connecting(monkeypatch) -> None:
    """An unfinished CONNECT request cannot keep a worker indefinitely or open an upstream connection."""

    monkeypatch.setattr(network_gate, "_IO_TIMEOUT", 0.05)
    with network_gate.SyncNetworkGate() as gate:
        connector = mock.Mock(side_effect=AssertionError("Unexpected upstream connection"))
        monkeypatch.setattr(gate, "connect", connector)
        with connect_proxy(gate) as client:
            client.sendall(b"CONNECT sync.example.invalid:443 HTTP/1.1")
            assert client.recv(4096) == b""
        connector.assert_not_called()
