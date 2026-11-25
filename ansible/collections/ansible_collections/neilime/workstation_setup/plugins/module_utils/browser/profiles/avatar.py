"""Validate managed browser avatar attachments without image-library dependencies."""

from __future__ import annotations

import base64
import binascii
import struct
import zlib

AVATAR_FILENAME = "workstation-avatar.png"
MAX_AVATAR_BYTES = 256 * 1024


def _validate_header(header: bytes) -> None:
    """Validate PNG dimensions and encoding parameters from the IHDR payload."""

    width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", header)
    valid_depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
    if not (1 <= width <= 1024 and 1 <= height <= 1024):
        raise ValueError("Browser avatar_png dimensions must be between 1 and 1024 pixels")
    if depth not in valid_depths.get(color, set()) or compression or filtering or interlace not in {0, 1}:
        raise ValueError("Browser avatar_png has an invalid PNG header")


def decode_avatar_png(value: object) -> bytes:
    """Decode a bounded PNG attachment; never include its contents in errors."""

    if not isinstance(value, str) or not value or len(value) > 4 * ((MAX_AVATAR_BYTES + 2) // 3):
        raise ValueError("Browser avatar_png must be base64 PNG data of at most 256 KiB")
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("Browser avatar_png must be valid base64 PNG data") from error
    if len(data) > MAX_AVATAR_BYTES or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Browser avatar_png must be PNG data of at most 256 KiB")
    offset = 8
    image_data = False
    while offset + 12 <= len(data):
        length, kind = struct.unpack_from(">I4s", data, offset)
        end = offset + 12 + length
        if end > len(data) or zlib.crc32(data[offset + 4 : end - 4]) != struct.unpack_from(">I", data, end - 4)[0]:
            raise ValueError("Browser avatar_png contains a malformed PNG chunk")
        if offset == 8:
            if kind != b"IHDR" or length != 13:
                raise ValueError("Browser avatar_png must begin with a valid PNG IHDR")
            _validate_header(data[offset + 8 : end - 4])
        elif kind == b"IHDR":
            raise ValueError("Browser avatar_png contains a duplicate PNG header")
        if kind == b"IDAT" and length:
            image_data = True
        if kind == b"IEND":
            if length or end != len(data) or not image_data:
                raise ValueError("Browser avatar_png has an invalid PNG ending")
            return data
        offset = end
    raise ValueError("Browser avatar_png is missing a complete PNG ending")
