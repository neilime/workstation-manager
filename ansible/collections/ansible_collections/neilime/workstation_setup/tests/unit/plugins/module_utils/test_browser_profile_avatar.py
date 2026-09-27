"""Bounded validation of company-logo PNG attachments."""

from __future__ import annotations

import base64
import struct
import zlib

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_avatar import (
    MAX_AVATAR_BYTES,
    decode_avatar_png,
)


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _png(width: int = 1, height: int = 1, depth: int = 8, color: int = 6) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, depth, color, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(b"\0\xff\0\xff\xff"))
        + _chunk(b"IEND", b"")
    )


def test_png_is_decoded_without_modifying_its_bytes() -> None:
    """The restored logo must be the exact attachment that was validated."""

    data = _png()
    assert decode_avatar_png(base64.b64encode(data).decode()) == data


@pytest.mark.parametrize(
    "value", [None, b"abc", "", "%%%", "💥", "c2VjcmV0", "A" * (4 * ((MAX_AVATAR_BYTES + 2) // 3) + 1)]
)
def test_invalid_or_oversized_base64_is_rejected_without_echoing_data(value: object) -> None:
    """Invalid attachment encoding fails without disclosing its contents."""

    with pytest.raises(ValueError, match="Browser avatar_png") as error:
        decode_avatar_png(value)
    assert "c2VjcmV0" not in str(error.value)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "data",
    [
        _png(0),
        _png(height=0),
        _png(1025),
        _png(height=1025),
        _png(depth=3),
        _png(color=7),
        _png()[:-12],
        _png()[:-1],
        _png() + b"trailing data",
        _png()[:29] + b"\0\0\0\0" + _png()[33:],
        b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", b"invalid") + _chunk(b"IEND", b""),
        _png()[:33] + _chunk(b"IEND", b""),
        _png()[:33] + _png()[8:],
        _png()[:-12] + _chunk(b"IEND", b"not empty"),
        _png() + b"\0" * MAX_AVATAR_BYTES,
    ],
)
def test_invalid_png_is_rejected(data: bytes) -> None:
    """Malformed headers, dimensions, chunks, and endings never reach profile writes."""

    with pytest.raises(ValueError, match="Browser avatar_png"):
        decode_avatar_png(base64.b64encode(data).decode())
