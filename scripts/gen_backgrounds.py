#!/usr/bin/env python3
"""
Generate ambient destination backgrounds for Travel Scout.

Visual: layered abstract landscape composition (not a photo):
  - multi-stop vertical sky gradient
  - visible radial sun/moon glow
  - rolling mountain silhouettes (foreground + midground + far)
  - horizon haze band
  - optional atmospheric grain

Themes define palette. Each theme has 3 variants (a/b/c) for subtle
fingerprint differences when the same region gets chosen often.

Run: python3 scripts/gen_backgrounds.py
"""
from PIL import Image, ImageDraw, ImageFilter
from pathlib import Path
import random
import math

OUT_DIR = Path(__file__).resolve().parent.parent / "frontend" / "public" / "backgrounds"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# --- themes ---
THEMES = {
    "mediterranean": {   # warm coastal midday
        "sky_top":   (255, 222, 178),
        "sky_mid":   (246, 200, 162),
        "horizon":   (228, 168, 130),
        "sea":       (96, 162, 188),
        "sea_deep":  (44, 96, 124),
        "near_mtn":  (96, 76, 64),
        "far_mtn":   (180, 156, 132),
        "accent":    (252, 184, 100),
    },
    "tropical": {        # lush island
        "sky_top":   (170, 224, 218),
        "sky_mid":   (120, 196, 184),
        "horizon":   (88, 168, 144),
        "sea":       (52, 138, 124),
        "sea_deep":  (24, 88, 84),
        "near_mtn":  (44, 96, 64),
        "far_mtn":   (108, 152, 120),
        "accent":    (220, 240, 168),
    },
    "desert": {          # terracotta
        "sky_top":   (244, 200, 156),
        "sky_mid":   (236, 168, 116),
        "horizon":   (220, 128, 84),
        "sea":       (192, 88, 56),   # here, sand sea
        "sea_deep":  (132, 56, 36),
        "near_mtn":  (88, 36, 24),
        "far_mtn":   (156, 84, 52),
        "accent":    (252, 196, 96),
    },
    "northern": {        # cool Scandinavian dusk
        "sky_top":   (180, 196, 220),
        "sky_mid":   (124, 148, 184),
        "horizon":   (84, 110, 148),
        "sea":       (40, 64, 102),
        "sea_deep":  (20, 36, 64),
        "near_mtn":  (16, 24, 48),
        "far_mtn":   (60, 80, 116),
        "accent":    (220, 196, 240),
    },
    "mountain": {        # alpine dawn
        "sky_top":   (220, 224, 232),
        "sky_mid":   (188, 200, 220),
        "horizon":   (160, 176, 200),
        "sea":       (108, 124, 152),
        "sea_deep":  (60, 80, 104),
        "near_mtn":  (36, 44, 64),
        "far_mtn":   (124, 140, 168),
        "accent":    (232, 220, 200),
    },
    "asian_metro": {     # electric Asia-Pacific
        "sky_top":   (236, 184, 200),
        "sky_mid":   (180, 120, 168),
        "horizon":   (124, 80, 148),
        "sea":       (56, 36, 100),
        "sea_deep":  (28, 16, 56),
        "near_mtn":  (12, 8, 28),
        "far_mtn":   (88, 56, 124),
        "accent":    (252, 196, 88),
    },
    "old_world": {       # Western Europe muted
        "sky_top":   (220, 212, 200),
        "sky_mid":   (188, 174, 156),
        "horizon":   (152, 132, 116),
        "sea":       (88, 76, 72),
        "sea_deep":  (44, 36, 40),
        "near_mtn":  (32, 24, 28),
        "far_mtn":   (124, 108, 96),
        "accent":    (200, 168, 132),
    },
    "safari": {          # warm golden
        "sky_top":   (252, 220, 168),
        "sky_mid":   (240, 188, 124),
        "horizon":   (220, 152, 84),
        "sea":       (180, 144, 80),
        "sea_deep":  (96, 64, 36),
        "near_mtn":  (44, 32, 20),
        "far_mtn":   (136, 96, 48),
        "accent":    (96, 144, 88),  # acacia green
    },
    "polar": {           # minimalist icefield
        "sky_top":   (228, 236, 244),
        "sky_mid":   (208, 220, 232),
        "horizon":   (180, 200, 220),
        "sea":       (124, 156, 180),
        "sea_deep":  (60, 96, 128),
        "near_mtn":  (44, 64, 92),
        "far_mtn":   (156, 184, 208),
        "accent":    (240, 244, 250),
    },
    "vineyard": {        # wine country golden hour
        "sky_top":   (228, 196, 168),
        "sky_mid":   (200, 156, 132),
        "horizon":   (164, 116, 108),
        "sea":       (96, 60, 72),
        "sea_deep":  (44, 24, 36),
        "near_mtn":  (24, 12, 20),
        "far_mtn":   (124, 84, 88),
        "accent":    (212, 144, 96),
    },
    "urban_night": {     # neon dusk
        "sky_top":   (44, 36, 80),
        "sky_mid":   (60, 48, 96),
        "horizon":   (88, 60, 124),
        "sea":       (28, 16, 44),
        "sea_deep":  (8, 4, 20),
        "near_mtn":  (0, 0, 8),
        "far_mtn":   (36, 24, 60),
        "accent":    (252, 156, 96),  # neon
    },
    "coastal_misty": {   # Pacific NW gray
        "sky_top":   (216, 222, 228),
        "sky_mid":   (180, 192, 200),
        "horizon":   (148, 164, 176),
        "sea":       (84, 100, 120),
        "sea_deep":  (40, 56, 76),
        "near_mtn":  (24, 36, 56),
        "far_mtn":   (108, 124, 144),
        "accent":    (200, 216, 224),
    },
}

VARIANTS = ["a", "b", "c"]
W, H = 1920, 1080


def multi_stop_gradient(stops, n=H):
    """stops: list of (y_ratio, color). e.g. [(0, sky_top), (.5, sky_mid), (1, sea)]"""
    img = Image.new("RGB", (W, H))
    px = img.load()
    stops = sorted(stops, key=lambda x: x[0])
    for y in range(H):
        t = y / (n - 1)
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t0 <= t <= t1:
                lt = (t - t0) / (t1 - t0) if t1 != t0 else 0
                px_x = lerp(c0, c1, lt)
                for x in range(W):
                    px[x, y] = px_x
                break
    return img


def radial_glow(img, color, cx, cy, rad, alpha=100):
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for r in range(rad, rad // 4, -10):
        a = int(alpha * (r / rad) ** 2.0)
        if a < 1:
            continue
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*color, a))
    overlay = overlay.filter(ImageFilter.GaussianBlur(20))
    img.paste(overlay, (0, 0), overlay)
    return img


def rolling_silhouette(img, color, base_y, max_h, count, jitter_seed, alpha=255):
    """Mountain silhouette: a polyline through n control points, varying heights."""
    rng = random.Random(jitter_seed)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    # Build a smoother ridge with peaks at random x positions
    peaks = sorted([rng.randint(0, W) for _ in range(count)])
    heights = [rng.randint(int(max_h * 0.6), max_h) for _ in range(count)]
    # Build the top edge
    points = [(0, base_y)] + [(peaks[i], base_y - heights[i]) for i in range(count)] + [(W, base_y)]
    # Add intermediate points between peaks for smoothness
    smooth = [points[0]]
    for i in range(1, len(points)):
        x0, y0 = points[i - 1]
        x1, y1 = points[i]
        steps = max(8, (x1 - x0) // 16)
        for s in range(1, steps + 1):
            t = s / steps
            # smoothstep
            t = t * t * (3 - 2 * t)
            nx = int(x0 + (x1 - x0) * t)
            ny = int(y0 + (y1 - y0) * t)
            smooth.append((nx, ny))
    smooth.append((W, H))
    d.polygon(smooth, fill=(*color, alpha))
    overlay = overlay.filter(ImageFilter.GaussianBlur(2))
    img.paste(overlay, (0, 0), overlay)
    return img


def horizon_haze(img, color, band_y0, band_y1, alpha=28):
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rectangle([0, band_y0, W, band_y1], fill=(*color, alpha))
    overlay = overlay.filter(ImageFilter.GaussianBlur(14))
    img.paste(overlay, (0, 0), overlay)
    return img


def grain(img, amount=8):
    rng = random.Random(int(amount * 17))
    px = img.load()
    for _ in range(W * H // 60):
        x = rng.randint(0, W - 1)
        y = rng.randint(0, H - 1)
        c = px[x, y]
        delta = rng.randint(-amount, amount)
        px[x, y] = tuple(max(0, min(255, ch + delta)) for ch in c)
    return img


def lerp(a, b, t):
    return tuple(int(max(0, min(255, a[i] + (b[i] - a[i]) * t))) for i in range(3))


def gen_one(theme_name, palette, variant):
    # Generate per-theme jitter so different variants look distinct
    seed = hash((theme_name, variant)) & 0xFFFFFFFF
    rng = random.Random(seed)

    stops = [
        (0.00, palette["sky_top"]),
        (0.45, palette["sky_mid"]),
        (0.62, palette["horizon"]),
        (0.72, palette["sea"]),
        (1.00, palette["sea_deep"]),
    ]
    img = multi_stop_gradient(stops)

    # Sun / moon radial: position varies by variant
    if theme_name != "urban_night":
        cx = int(W * rng.uniform(0.30, 0.70))
        cy = int(H * rng.uniform(0.20, 0.35))
        rad = rng.randint(300, 480)
        alpha = rng.randint(70, 130)
        img = radial_glow(img, palette["accent"], cx, cy, rad, alpha)

    # Distant mountains (low, soft, blended)
    far_mtn_base = int(H * 0.55)
    far_mtn_h = rng.randint(80, 140)
    img = rolling_silhouette(img, palette["far_mtn"], far_mtn_base, far_mtn_h,
                             count=rng.randint(5, 8), jitter_seed=seed + 11, alpha=160)

    # Mid mountains (slightly darker)
    mid_mtn_base = int(H * 0.66)
    mid_mtn_h = rng.randint(140, 220)
    mid_color = lerp(palette["far_mtn"], palette["near_mtn"], 0.5)
    img = rolling_silhouette(img, mid_color, mid_mtn_base, mid_mtn_h,
                             count=rng.randint(4, 7), jitter_seed=seed + 23, alpha=200)

    # Horizon haze between mountains and sea
    img = horizon_haze(img, palette["horizon"], int(H * 0.62), int(H * 0.70), alpha=36)

    # Foreground mountains (only some themes, to keep visual hierarchy)
    if theme_name in ("mountain", "northern", "polar", "coastal_misty", "vineyard", "desert"):
        near_mtn_base = int(H * 0.78)
        near_mtn_h = rng.randint(180, 280)
        img = rolling_silhouette(img, palette["near_mtn"], near_mtn_base, near_mtn_h,
                                 count=rng.randint(3, 5), jitter_seed=seed + 47, alpha=230)
    elif theme_name == "urban_night":
        # City skyline: cluster of building rectangles + lit windows
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        rng2 = random.Random(seed + 99)
        x = 0
        while x < W:
            bw = rng2.randint(40, 110)
            bh = rng2.randint(120, 280)
            by = H - bh - 80
            d.rectangle([x, by, x + bw, by + bh], fill=(*palette["near_mtn"], 245))
            # Windows
            for wx in range(x + 6, x + bw - 6, 8):
                for wy in range(by + 12, by + bh - 8, 14):
                    if rng2.random() < 0.35:
                        win_color = rng2.choice([palette["accent"], (252, 220, 132), (236, 168, 196)])
                        d.rectangle([wx, wy, wx + 4, wy + 6], fill=(*win_color, 220))
            x += bw + rng2.randint(0, 8)
        overlay = overlay.filter(ImageFilter.GaussianBlur(0.6))
        img.paste(overlay, (0, 0), overlay)

    # Subtle grain for variants b/c
    if variant in ("b", "c"):
        img = grain(img, amount=6)

    # Top haze for hero readability (darken the very top so titles pop)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for y in range(0, int(H * 0.30), 4):
        al = int(28 * (1 - y / (H * 0.30)))
        if al > 0:
            d.rectangle([0, y, W, y + 4], fill=(0, 0, 0, al))
    overlay = overlay.filter(ImageFilter.GaussianBlur(6))
    img.paste(overlay, (0, 0), overlay)

    out = OUT_DIR / f"{theme_name}_{variant}.jpg"
    img.save(out, "JPEG", quality=80, optimize=True)
    print(f"  -> {out.name} ({out.stat().st_size // 1024} KB)")


def main():
    print(f"Generating backgrounds -> {OUT_DIR}")
    for theme_name, palette in THEMES.items():
        for v in VARIANTS:
            gen_one(theme_name, palette, v)
    count = len(list(OUT_DIR.glob("*.jpg")))
    print(f"\nDone. {count} images in {OUT_DIR}")


if __name__ == "__main__":
    main()
