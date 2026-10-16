"""Colours, fonts and spacing. ttk widgets take their look from sv-ttk (Sun Valley, light);
the plain tk widgets (bands, preview canvases) use the values here."""
from __future__ import annotations

COLORS = {
    "bg": "#FAFAFA", "surface": "#FFFFFF", "border": "#E0E0E0", "text": "#1F2328", "muted": "#6B7280",
    "accent": "#005FB8", "band": "#F3F6FD", "ok": "#16A34A", "warn": "#B45309", "err": "#DC2626",
    "canvas": "#F1F3F6", "stripe": "#F7F8FA", "drop_line": "#A9B4C6", "band_line": "#D6E0F5",
    "chip_line": "#D0D5DD", "chip_hover": "#EEF3FB", "ok_text": "#3F6B4F",
}
STATUS_COLORS = {"done": "#16A34A", "over": "#B45309", "small": "#6B7280", "failed": "#DC2626",
                 "cancelled": "#6B7280", "wait": "#6B7280"}

PAD_OUT = 16  # window edge
PAD = 8  # between elements
ROW_HEIGHT = 28
WINDOW = (1220, 820)
WINDOW_MIN = (1000, 680)
SIDE_WIDTH = 330  # the options / result panel on the right
BODY_PT = 10
TITLE_PT = 16
BIG_PT = 17

# UI font per language (Malgun Gothic has Hangul, kana and hanzi)
# Tk lists Malgun Gothic under its Korean name on a Korean Windows, so both names are tried.
MALGUN = ("\ub9d1\uc740 \uace0\ub515", "Malgun Gothic")
UI_FONTS = {"ko": MALGUN, "en": ("Segoe UI",), "zh-CN": ("Microsoft YaHei UI", "Microsoft YaHei"),
            "ja": ("Yu Gothic UI", "Meiryo UI", "Meiryo")}
FALLBACK_FONTS = ("Segoe UI", *MALGUN)

SCALE = 1.0  # screen pixels per design pixel (1.5 at 150 % Windows scaling); set by the GUI at start


def set_scale(pixels_per_inch: float) -> None:
    global SCALE
    SCALE = max(1.0, pixels_per_inch / 96.0)


def px(n: float) -> int:
    return int(round(n * SCALE))


def pick_font(families: set[str], candidates: tuple[str, ...]) -> str:
    for name in (*candidates, *FALLBACK_FONTS):
        if name in families:
            return name
    return "TkDefaultFont"
