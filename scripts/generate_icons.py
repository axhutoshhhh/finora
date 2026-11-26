"""Generate macOS iconset PNGs and compile Finora.icns via iconutil."""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
BRANDING_DIR = ROOT / "assets" / "branding"
ICONSET_DIR = BRANDING_DIR / "Finora.iconset"
ICNS_PATH = BRANDING_DIR / "Finora.icns"

ICON_SPECS: tuple[tuple[str, int], ...] = (
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
)


def _squircle_polygon(
    cx: float, cy: float, half: float, power: float = 4.6, steps: int = 240
) -> list[tuple[float, float]]:
    """Sample a continuous superellipse mimicking macOS app icon geometry."""
    pts: list[tuple[float, float]] = []
    for i in range(steps):
        theta = (2.0 * math.pi * i) / steps
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        x = cx + half * math.copysign(abs(cos_t) ** (2.0 / power), cos_t)
        y = cy + half * math.copysign(abs(sin_t) ** (2.0 / power), sin_t)
        pts.append((x, y))
    return pts


def render_master_icon(size: int = 1024) -> Image.Image:
    """Render the Finora macOS app icon with 4x supersampling for clean anti-aliasing."""
    scale = 4
    canvas_size = size * scale
    img = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    center = canvas_size / 2.0
    outer_half = 412.0 * scale  # 824x824 macOS icon body inside 1024x1024 canvas

    # Subtle outer drop shadow band for Finder/Dock contrast on light backgrounds
    shadow_poly = _squircle_polygon(center, center + 6 * scale, outer_half + 1 * scale)
    draw.polygon(shadow_poly, fill=(14, 24, 19, 42))

    # Primary matte deep forest-slate icon plate (clean single edge, no halo artifact)
    body_poly = _squircle_polygon(center, center, outer_half)
    draw.polygon(body_poly, fill=(30, 72, 55, 255))

    # Geometric Finora ledger-fold mark mapped from 32x32 design coordinates
    # Optically centered horizontally for asymmetric miter silhouette
    mark_box = 528.0 * scale
    unit = mark_box / 32.0
    offset_x = center - (mark_box / 2.0) + 0.35 * unit
    offset_y = center - (mark_box / 2.0)

    def pt(x: float, y: float) -> tuple[float, float]:
        return (offset_x + x * unit, offset_y + y * unit)

    # Top mitered ledger spine + upper bar
    draw.polygon(
        [
            pt(6.5, 5.0),
            pt(25.5, 5.0),
            pt(22.0, 10.5),
            pt(12.5, 10.5),
            pt(12.5, 27.0),
            pt(6.5, 27.0),
        ],
        fill=(244, 245, 240, 255),
    )
    # Middle stepped bar
    draw.polygon(
        [pt(14.8, 14.5), pt(23.8, 14.5), pt(20.7, 19.5), pt(14.8, 19.5)],
        fill=(153, 203, 174, 255),
    )
    # Bottom datum block
    draw.polygon(
        [pt(14.8, 23.4), pt(19.3, 23.4), pt(19.3, 27.0), pt(14.8, 27.0)],
        fill=(153, 203, 174, 190),
    )

    return img.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    if ICONSET_DIR.exists():
        shutil.rmtree(ICONSET_DIR)
    ICONSET_DIR.mkdir(parents=True, exist_ok=True)

    master = render_master_icon(1024)
    for filename, px in ICON_SPECS:
        resized = master if px == 1024 else master.resize((px, px), Image.Resampling.LANCZOS)
        resized.save(ICONSET_DIR / filename, format="PNG")

    subprocess.run(
        ["/usr/bin/iconutil", "-c", "icns", str(ICONSET_DIR), "-o", str(ICNS_PATH)],
        check=True,
    )
    print(f"Generated {ICNS_PATH} ({ICNS_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
