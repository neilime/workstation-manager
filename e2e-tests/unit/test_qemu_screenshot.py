"""Unit tests for the host-side QEMU screenshot helper."""

from __future__ import annotations

import importlib.util
import pathlib
import types
import unittest

SCREENSHOT_MODULE_PATH = pathlib.Path(__file__).parents[1] / "qemu_screenshot.py"


def load_screenshot_module() -> types.ModuleType:
    """Load the host-side helper without making e2e-tests a Python package."""
    spec = importlib.util.spec_from_file_location("qemu_screenshot", SCREENSHOT_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {SCREENSHOT_MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


qemu_screenshot = load_screenshot_module()


def ppm(width: int, height: int, pixels: bytes) -> bytes:
    """Build a binary RGB PPM fixture."""
    return f"P6\n{width} {height}\n255\n".encode() + pixels


class PpmToPngTests(unittest.TestCase):
    """Exercise framebuffer validation and conversion."""

    def test_rejects_qemu_inactive_display_placeholder(self) -> None:
        """QEMU's black and gray inactive-display surface is not a screenshot."""
        inactive_pixels = (b"\x00\x00\x00" * 7) + b"\xaa\xaa\xaa"

        with self.assertRaisesRegex(RuntimeError, "QEMU display output is not active"):
            qemu_screenshot.ppm_to_png(ppm(4, 2, inactive_pixels))

    def test_rejects_all_black_framebuffer(self) -> None:
        """An inactive framebuffer without placeholder text is also rejected."""
        with self.assertRaisesRegex(RuntimeError, "QEMU display output is not active"):
            qemu_screenshot.ppm_to_png(ppm(2, 2, b"\x00\x00\x00" * 4))

    def test_converts_active_framebuffer(self) -> None:
        """A framebuffer with actual display content is converted to PNG."""
        active_pixels = b"\x00\x00\x00\xff\x00\x00"

        png_data = qemu_screenshot.ppm_to_png(ppm(2, 1, active_pixels))

        self.assertTrue(png_data.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
