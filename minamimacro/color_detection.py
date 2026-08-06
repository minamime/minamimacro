from __future__ import annotations

from pathlib import Path

from mss import mss
from PIL import Image


def extract_palette_from_image(image_path: str | Path, max_colors: int = 12) -> list[tuple[int, int, int]]:
    image = Image.open(image_path).convert("RGB")
    reduced = image.resize((min(image.width, 256), min(image.height, 256)))

    quantized = reduced.quantize(colors=max_colors, method=Image.MEDIANCUT)
    palette = quantized.getpalette() or []
    color_counts = quantized.getcolors() or []

    colors: list[tuple[int, int, int]] = []
    for _, color_index in sorted(color_counts, reverse=True):
        base = color_index * 3
        if base + 2 >= len(palette):
            continue
        r, g, b = palette[base], palette[base + 1], palette[base + 2]
        colors.append((int(r), int(g), int(b)))

    return colors[:max_colors]


def area_contains_any_target_color(
    area: tuple[int, int, int, int],
    target_colors: list[tuple[int, int, int]],
    tolerance: int,
) -> bool:
    if not target_colors:
        return False

    x1, y1, x2, y2 = area
    width = max(1, x2 - x1)
    height = max(1, y2 - y1)

    with mss() as screen:
        shot = screen.grab({"left": x1, "top": y1, "width": width, "height": height})

    pixels = shot.bgra
    step = 4

    for idx in range(0, len(pixels), step):
        b = pixels[idx]
        g = pixels[idx + 1]
        r = pixels[idx + 2]
        for tr, tg, tb in target_colors:
            if abs(r - tr) <= tolerance and abs(g - tg) <= tolerance and abs(b - tb) <= tolerance:
                return True

    return False
