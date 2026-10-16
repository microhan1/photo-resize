"""Draw the program icon (assets/icon.png and assets/icon.ico).

    python assets/make_icon.py

A photo card (sky and hills) with a downward arrow badge: "the same photo, smaller".
Drawn at 4x and reduced, so the edges stay smooth at 16 px too.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
S = 1024  # drawing size; reduced to 256


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # photo card
    card = (96, 150, 820, 760)
    d.rounded_rectangle(card, radius=90, fill=(255, 255, 255, 255), outline=(208, 213, 221, 255), width=18)
    inner = (150, 204, 766, 706)
    sky = Image.new("RGBA", (inner[2] - inner[0], inner[3] - inner[1]), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sky)
    for y in range(sky.height):  # sky gradient
        t = y / sky.height
        sd.line([(0, y), (sky.width, y)], fill=(int(96 + 80 * t), int(165 + 50 * t), 250, 255))
    w, h = sky.size
    sd.ellipse((w * 0.62, h * 0.12, w * 0.86, h * 0.36), fill=(255, 214, 92, 255))  # sun
    sd.polygon([(0, h), (0, h * 0.62), (w * 0.28, h * 0.36), (w * 0.55, h * 0.70), (w * 0.55, h)],
               fill=(46, 160, 104, 255))
    sd.polygon([(w * 0.35, h), (w * 0.72, h * 0.48), (w, h * 0.78), (w, h)], fill=(30, 128, 84, 255))
    mask = Image.new("L", sky.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=48, fill=255)
    img.paste(sky, inner[:2], mask)
    # arrow badge
    cx, cy, r = 742, 742, 210
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(0, 95, 184, 255), outline=(255, 255, 255, 255), width=28)
    d.rectangle((cx - 42, cy - 112, cx + 42, cy + 20), fill=(255, 255, 255, 255))
    d.polygon([(cx - 112, cy + 2), (cx + 112, cy + 2), (cx, cy + 122)], fill=(255, 255, 255, 255))
    return img


def main() -> None:
    big = draw()
    icon = big.resize((256, 256), Image.Resampling.LANCZOS)
    icon.save(os.path.join(HERE, "icon.png"))
    icon.save(os.path.join(HERE, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128),
                                                     (256, 256)])


if __name__ == "__main__":
    main()
