from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from mss import mss
from PIL import Image, ImageGrab


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
    return find_first_target_color_match(area, target_colors, tolerance) is not None


def find_first_target_color_match(
    area: tuple[int, int, int, int],
    target_colors: list[tuple[int, int, int]],
    tolerance: int,
) -> tuple[tuple[int, int, int], tuple[int, int]] | None:
    if not target_colors:
        return None

    x1, y1, x2, y2 = area
    width = max(1, x2 - x1)
    height = max(1, y2 - y1)

    capture_errors: list[str] = []

    # Fast path: direct region capture via MSS.
    try:
        with mss() as screen:
            shot = screen.grab({"left": x1, "top": y1, "width": width, "height": height})
        match = _find_match_in_bgra(shot.bgra, width, target_colors, tolerance)
        if match is not None:
            color, (local_x, local_y) = match
            return color, (x1 + local_x, y1 + local_y)
    except Exception as exc:
        capture_errors.append(f"mss-region={exc}")

    # Wayland/HiDPI fallback path: capture full screen and test scaled area candidates.
    full_image = _capture_full_screen_image(capture_errors)
    if full_image is None:
        raise RuntimeError("Screen capture failed: " + "; ".join(capture_errors))

    rgb_image = full_image.convert("RGB")
    for candidate in _scaled_area_candidates((x1, y1, x2, y2), rgb_image.size):
        cropped = rgb_image.crop(candidate)
        match = _find_match_in_rgb_image(cropped, target_colors, tolerance)
        if match is not None:
            color, (local_x, local_y) = match
            return color, (candidate[0] + local_x, candidate[1] + local_y)

    return None


def _capture_full_screen_image(capture_errors: list[str]) -> Image.Image | None:
    try:
        return ImageGrab.grab(all_screens=True, xdisplay=None)
    except Exception as exc:
        capture_errors.append(f"imagegrab={exc}")

    # GNOME Wayland fallback when ImageGrab cannot access screen content.
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        gnome = _capture_full_screen_gnome_screenshot(capture_errors)
        if gnome is not None:
            return gnome

    return None


def _capture_full_screen_gnome_screenshot(capture_errors: list[str]) -> Image.Image | None:
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        command = ["gnome-screenshot", "-f", str(tmp_path)]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            capture_errors.append(f"gnome-screenshot={result.stderr.strip() or result.stdout.strip()}")
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            return None

        image = Image.open(tmp_path).convert("RGB")
        tmp_path.unlink(missing_ok=True)
        return image
    except Exception as exc:
        capture_errors.append(f"gnome-screenshot-exception={exc}")
        return None


def _scaled_area_candidates(area: tuple[int, int, int, int], image_size: tuple[int, int]) -> list[tuple[int, int, int, int]]:
    x1, y1, x2, y2 = area
    width, height = image_size
    scales = [1.0, 1.25, 1.5, 1.75, 2.0]
    candidates: list[tuple[int, int, int, int]] = []

    for scale in scales:
        sx1 = int(min(x1, x2) * scale)
        sy1 = int(min(y1, y2) * scale)
        sx2 = int(max(x1, x2) * scale)
        sy2 = int(max(y1, y2) * scale)

        sx1 = max(0, min(sx1, width - 1))
        sy1 = max(0, min(sy1, height - 1))
        sx2 = max(sx1 + 1, min(sx2, width))
        sy2 = max(sy1 + 1, min(sy2, height))

        candidate = (sx1, sy1, sx2, sy2)
        if candidate not in candidates:
            candidates.append(candidate)

    return candidates


def _matches_bgra_pixels(pixels: bytes, target_colors: list[tuple[int, int, int]], tolerance: int) -> bool:
    return _find_match_in_bgra(pixels, None, target_colors, tolerance) is not None


def _matches_rgb_image(image: Image.Image, target_colors: list[tuple[int, int, int]], tolerance: int) -> bool:
    return _find_match_in_rgb_image(image, target_colors, tolerance) is not None


def _find_match_in_bgra(
    pixels: bytes,
    width: int | None,
    target_colors: list[tuple[int, int, int]],
    tolerance: int,
) -> tuple[tuple[int, int, int], tuple[int, int]] | None:
    for idx in range(0, len(pixels), 4):
        b = pixels[idx]
        g = pixels[idx + 1]
        r = pixels[idx + 2]
        for tr, tg, tb in target_colors:
            if abs(r - tr) <= tolerance and abs(g - tg) <= tolerance and abs(b - tb) <= tolerance:
                if width is None or width <= 0:
                    return (r, g, b), (0, 0)
                pixel_index = idx // 4
                return (r, g, b), (pixel_index % width, pixel_index // width)
    return None


def _find_match_in_rgb_image(
    image: Image.Image,
    target_colors: list[tuple[int, int, int]],
    tolerance: int,
) -> tuple[tuple[int, int, int], tuple[int, int]] | None:
    width, _ = image.size
    for index, (r, g, b) in enumerate(image.getdata()):
        for tr, tg, tb in target_colors:
            if abs(r - tr) <= tolerance and abs(g - tg) <= tolerance and abs(b - tb) <= tolerance:
                return (r, g, b), (index % width, index // width)
    return None
