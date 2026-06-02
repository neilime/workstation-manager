#!/usr/bin/env python3
"""Capture a QEMU display through QMP and convert its PPM output to PNG."""

from __future__ import annotations

import json
import pathlib
import socket
import struct
import sys
import time
import zlib
from typing import Protocol

WHITESPACE = b" \t\r\n"
QEMU_INACTIVE_DISPLAY_COLORS = {b"\x00\x00\x00", b"\xaa\xaa\xaa"}


class QmpStream(Protocol):
    """Binary stream operations used by the QMP client."""

    def readline(self, size: int = -1, /) -> bytes:
        """Read one QMP response line."""

    def write(self, buffer: bytes, /) -> int:
        """Write one QMP request."""

    def flush(self) -> None:
        """Flush a pending QMP request."""


def read_qmp_message(stream: QmpStream) -> dict[str, object]:
    """Read the next non-event QMP message."""
    while line := stream.readline():
        if not line.strip():
            continue
        message = json.loads(line)
        if "event" not in message:
            return message
    raise RuntimeError("QMP closed the connection")


def send_qmp_command(
    stream: QmpStream,
    command: str,
    arguments: dict[str, object] | None = None,
) -> dict[str, object]:
    """Send one QMP command and return its matching response."""
    payload: dict[str, object] = {"execute": command, "id": command}
    if arguments is not None:
        payload["arguments"] = arguments
    stream.write(json.dumps(payload).encode() + b"\r\n")
    stream.flush()

    while True:
        response = read_qmp_message(stream)
        if response.get("id") != command:
            continue
        if "error" in response:
            raise RuntimeError(f"QMP {command} failed: {response['error']}")
        return response


def read_ppm_token(data: bytes, offset: int) -> tuple[bytes, int]:
    """Read a Netpbm header token, allowing comments between tokens."""
    while offset < len(data):
        if data[offset] in WHITESPACE:
            offset += 1
        elif data[offset] == ord("#"):
            while offset < len(data) and data[offset] not in b"\r\n":
                offset += 1
        else:
            break
    if offset >= len(data):
        raise RuntimeError("PPM header ended unexpectedly")

    start = offset
    while offset < len(data) and data[offset] not in WHITESPACE:
        offset += 1
    return data[start:offset], offset


def read_ppm(data: bytes) -> tuple[int, int, bytes]:
    """Read an 8-bit binary RGB PPM image."""
    offset = 0
    magic, offset = read_ppm_token(data, offset)
    width_token, offset = read_ppm_token(data, offset)
    height_token, offset = read_ppm_token(data, offset)
    max_value_token, offset = read_ppm_token(data, offset)

    if magic != b"P6":
        raise RuntimeError(f"Unsupported PPM magic: {magic!r}")
    width = int(width_token)
    height = int(height_token)
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Invalid PPM dimensions: {width}x{height}")
    if int(max_value_token) != 255:
        raise RuntimeError(f"Unsupported PPM max value: {max_value_token!r}")
    if offset >= len(data) or data[offset] not in WHITESPACE:
        raise RuntimeError("PPM header has no pixel-data separator")

    # The P6 header ends at one whitespace character. Accept CRLF as one logical
    # separator without consuming pixel bytes whose values happen to be whitespace.
    offset += 1
    if data[offset - 1] == ord("\r") and offset < len(data) and data[offset] == ord("\n"):
        offset += 1

    expected_size = width * height * 3
    pixels = data[offset : offset + expected_size]
    if len(pixels) != expected_size:
        raise RuntimeError("PPM pixel payload is truncated")
    return width, height, pixels


def is_qemu_inactive_display(pixels: bytes) -> bool:
    """Return whether pixels are QEMU's inactive virtio-gpu placeholder."""
    found_colors: set[bytes] = set()
    for offset in range(0, len(pixels), 3):
        color = pixels[offset : offset + 3]
        if color not in QEMU_INACTIVE_DISPLAY_COLORS:
            return False
        found_colors.add(color)
    return bool(found_colors)


def ppm_to_png(data: bytes) -> bytes:
    """Convert an active 8-bit binary RGB PPM image to PNG."""
    width, height, pixels = read_ppm(data)
    if is_qemu_inactive_display(pixels):
        raise RuntimeError("QEMU display output is not active")

    def png_chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    stride = width * 3
    rows = b"".join(b"\0" + pixels[start : start + stride] for start in range(0, len(pixels), stride))
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            png_chunk(b"IDAT", zlib.compress(rows)),
            png_chunk(b"IEND", b""),
        )
    )


def capture(qmp_socket: pathlib.Path, ppm_path: pathlib.Path) -> None:
    """Wake the guest and ask QEMU to write its display to a host path."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(5)
        connection.connect(str(qmp_socket))
        with connection.makefile("rwb") as stream:
            greeting = read_qmp_message(stream)
            if "QMP" not in greeting:
                raise RuntimeError(f"Unexpected QMP greeting: {greeting!r}")
            send_qmp_command(stream, "qmp_capabilities")
            send_qmp_command(
                stream,
                "send-key",
                {
                    "keys": [{"type": "qcode", "data": "shift"}],
                    "hold-time": 100,
                },
            )
            time.sleep(1)
            send_qmp_command(stream, "screendump", {"filename": str(ppm_path)})


def main() -> None:
    """Capture a screenshot using paths supplied on the command line."""
    if len(sys.argv) != 4:
        raise SystemExit(f"usage: {sys.argv[0]} QMP_SOCKET PPM_PATH PNG_PATH")

    qmp_socket, ppm_path, png_path = map(pathlib.Path, sys.argv[1:])
    capture(qmp_socket, ppm_path)
    ppm_data = ppm_path.read_bytes()
    png_data = ppm_to_png(ppm_data)
    temporary_png_path = png_path.with_suffix(f"{png_path.suffix}.tmp")
    temporary_png_path.write_bytes(png_data)
    temporary_png_path.replace(png_path)
    print(f"captured {len(ppm_data)} PPM bytes as {len(png_data)} PNG bytes")


if __name__ == "__main__":
    main()
