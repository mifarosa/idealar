"""Draws the Idealar logo (a thick ring, dot and stems that read as "ai" and as a light bulb, on an orange rounded square) as PNG icons, pure stdlib.

Run after changing the design:  python scripts/make_icons.py
Keep static/img/logo.svg in sync with the shapes below.
"""
import struct
import zlib
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"
ORANGE = (233, 106, 38)
WHITE = (255, 255, 255)
SAMPLES = 4  # per axis, for smooth edges

CORNER_RADIUS = 14 / 64

# Shapes in a 0..1 square (same proportions as the 64x64 SVG). The glyph reads as "ai" and as a light bulb:
# a thick ring is the round bowl of an "a" (its stem on the right) and the glass of the bulb, the dot inside is the
# dot of the "i", and the "i" stem below is the base of the bulb. It is centred on the icon.
RING_CENTER, RING_OUTER, RING_INNER = (32 / 64, 24 / 64), 16 / 64, 8 / 64
DOT_RADIUS = 4.8 / 64
A_STEM = (40 / 64, 8 / 64, 8 / 64, 32 / 64, 4 / 64)  # left, top, width, height, corner radius
I_STEM = (28 / 64, 45 / 64, 8 / 64, 11 / 64, 4 / 64)


def _in_rounded_rect(x: float, y: float, left: float, top: float, width: float, height: float, radius: float) -> bool:
    cx = min(max(x, left + radius), left + width - radius)
    cy = min(max(y, top + radius), top + height - radius)
    return left <= x <= left + width and top <= y <= top + height and (x - cx) ** 2 + (y - cy) ** 2 <= radius**2


def _distance(x: float, y: float, center: tuple[float, float]) -> float:
    return ((x - center[0]) ** 2 + (y - center[1]) ** 2) ** 0.5


def _sample(x: float, y: float, rounded: bool) -> tuple[tuple[int, int, int], bool]:
    """Colour and whether the point is painted at all."""
    distance = _distance(x, y, RING_CENTER)
    white = (
        RING_INNER <= distance <= RING_OUTER
        or distance <= DOT_RADIUS
        or _in_rounded_rect(x, y, *A_STEM)
        or _in_rounded_rect(x, y, *I_STEM)
    )
    if white:
        return WHITE, True
    if not rounded or _in_rounded_rect(x, y, 0, 0, 1, 1, CORNER_RADIUS):
        return ORANGE, True
    return ORANGE, False


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def render_png(size: int, rounded: bool = True) -> bytes:
    rows = bytearray()
    for row in range(size):
        rows.append(0)
        for col in range(size):
            red = green = blue = covered = 0
            for sy in range(SAMPLES):
                for sx in range(SAMPLES):
                    colour, painted = _sample((col + (sx + 0.5) / SAMPLES) / size, (row + (sy + 0.5) / SAMPLES) / size, rounded)
                    if painted:
                        red, green, blue, covered = red + colour[0], green + colour[1], blue + colour[2], covered + 1
            total = SAMPLES * SAMPLES
            if covered:
                rows.extend((red // covered, green // covered, blue // covered, 255 * covered // total))
            else:
                rows.extend((0, 0, 0, 0))
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header) + _png_chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + _png_chunk(b"IEND", b"")


def main() -> None:
    icons = STATIC / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        (icons / f"icon-{size}.png").write_bytes(render_png(size))
    # Full-bleed variants: Android masks "maskable" icons itself and iOS fills transparent corners with black.
    (icons / "icon-512-maskable.png").write_bytes(render_png(512, rounded=False))
    (icons / "apple-touch-icon.png").write_bytes(render_png(180, rounded=False))


if __name__ == "__main__":
    main()
