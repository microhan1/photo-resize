"""Draw the start-up picture (assets/splash.png) that build.bat puts on the screen with
--splash while the one-file exe unpacks.

    python assets/make_splash.py

The program icon from make_icon.py and the file name "photo-resize": the program's own name
differs in each language, so the picture carries the one name all four READMEs share.
Drawn at 4x and reduced, then saved as a palette PNG so the picture stays a few KB and does
not slow the start it is meant to cover.
"""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_icon import draw as draw_icon  # noqa: E402

S = 4  # drawing scale
W, H = 300, 104  # the picture's size on screen (the same as the other tools in the series)
ICON, ICON_X = 64, 20
TEXT_X, RIGHT_PAD = 98, 14
INK, RULE = (23, 32, 43), (217, 224, 230)
FONT = r"C:\Windows\Fonts\segoeuib.ttf"
NAME = "photo-resize"
COLORS = 128


def draw() -> Image.Image:
    img = Image.new("RGB", (W * S, H * S), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W * S - 1, H * S - 1), outline=RULE, width=S)
    icon = draw_icon().resize((ICON * S, ICON * S), Image.LANCZOS)
    img.paste(icon, (ICON_X * S, (H - ICON) // 2 * S), icon)
    room = (W - TEXT_X - RIGHT_PAD) * S
    size = 34 * S
    font = ImageFont.truetype(FONT, size)
    while font.getlength(NAME) > room and size > 10 * S:  # shrink the name until it fits
        size -= S
        font = ImageFont.truetype(FONT, size)
    d.text((TEXT_X * S, H * S // 2), NAME, font=font, fill=INK, anchor="lm")
    return img.resize((W, H), Image.LANCZOS)


def main() -> None:
    out = os.path.join(HERE, "splash.png")
    img = draw().quantize(colors=COLORS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    img.save(out, optimize=True)
    print(out, os.path.getsize(out), "bytes")


if __name__ == "__main__":
    main()
