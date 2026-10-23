"""Generates the PWA icons (pure stdlib, no Pillow). Run once: python scripts/make_icons.py"""
import struct
import zlib
from pathlib import Path

ICON_DIR = Path(__file__).resolve().parent.parent / "static" / "icons"
BACKGROUND = (79, 70, 229)
BULB = (254, 240, 138)
BASE = (226, 232, 240)


def _pixel(x: float, y: float) -> tuple[int, int, int]:
    """x, y in 0..1. A light bulb: circle on top, small base below."""
    in_bulb = (x - 0.5) ** 2 + (y - 0.42) ** 2 <= 0.2**2
    in_base = 0.42 <= x <= 0.58 and 0.64 <= y <= 0.76
    if in_bulb:
        return BULB
    return BASE if in_base else BACKGROUND


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def render_png(size: int) -> bytes:
    rows = bytearray()
    for row in range(size):
        rows.append(0)
        for col in range(size):
            rows.extend(_pixel((col + 0.5) / size, (row + 0.5) / size))
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header) + _png_chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + _png_chunk(b"IEND", b"")


def main() -> None:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        (ICON_DIR / f"icon-{size}.png").write_bytes(render_png(size))


if __name__ == "__main__":
    main()
