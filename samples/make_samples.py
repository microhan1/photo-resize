"""Generated sample photos for the tests and the screenshots - never real photos.

    python samples/make_samples.py <folder>

Pictures are gradients with seeded noise and soft shapes, so JPEG sizes behave roughly
like camera photos (a 4000x3000 sample is a few MB at quality 92). Metadata is written
with piexif: capture date, camera, orientation and a GPS position (Seoul City Hall).
"""
from __future__ import annotations

import io
import os
import random
import sys

from PIL import Image, ImageCms, ImageDraw, ImageFilter

DATE = b"2024:03:15 12:34:56"
GPS_LAT = ((37, 1), (33, 1), (5100, 100))
GPS_LON = ((126, 1), (58, 1), (4200, 100))


def srgb_icc() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def picture(w: int, h: int, seed: int = 0, detail: float = 0.35, mode: str = "RGB") -> Image.Image:
    """A photo-like picture: colour gradient, shapes, fine noise (more detail = bigger files)."""
    rnd = random.Random(seed)
    grad = Image.linear_gradient("L").resize((w, h))
    r = grad
    g = grad.rotate(90, expand=False).resize((w, h))
    b = Image.radial_gradient("L").resize((w, h))
    img = Image.merge("RGB", (r, g, b))
    draw = ImageDraw.Draw(img)
    for _ in range(12):
        x0, y0 = rnd.randrange(w), rnd.randrange(h)
        rad = rnd.randrange(max(2, min(w, h) // 12), max(3, min(w, h) // 3))
        color = tuple(rnd.randrange(256) for _ in range(3))
        draw.ellipse((x0 - rad, y0 - rad, x0 + rad, y0 + rad), fill=color)
    img = img.filter(ImageFilter.GaussianBlur(max(1, min(w, h) // 200)))
    noise = Image.frombytes("RGB", (w, h), rnd.randbytes(w * h * 3)).filter(ImageFilter.GaussianBlur(0.6))
    img = Image.blend(img, noise, detail)
    return img.convert(mode) if mode != "RGB" else img


def exif_bytes(orientation: int = 1, gps: bool = True, date: bytes = DATE, w: int = 0, h: int = 0) -> bytes:
    import piexif

    zeroth = {piexif.ImageIFD.Make: b"SampleCam", piexif.ImageIFD.Model: b"S1",
              piexif.ImageIFD.Orientation: orientation, piexif.ImageIFD.DateTime: date}
    exif = {piexif.ExifIFD.DateTimeOriginal: date, piexif.ExifIFD.DateTimeDigitized: date}
    if w and h:
        exif[piexif.ExifIFD.PixelXDimension] = w
        exif[piexif.ExifIFD.PixelYDimension] = h
    data = {"0th": zeroth, "Exif": exif, "GPS": {}, "1st": {}, "thumbnail": None}
    if gps:
        data["GPS"] = {piexif.GPSIFD.GPSLatitudeRef: b"N", piexif.GPSIFD.GPSLatitude: GPS_LAT,
                       piexif.GPSIFD.GPSLongitudeRef: b"E", piexif.GPSIFD.GPSLongitude: GPS_LON}
    return piexif.dump(data)


XMP_WITH_GPS = (b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
                b'<rdf:Description xmlns:exif="http://ns.adobe.com/exif/1.0/" exif:GPSLatitude="37,33.85N" '
                b'exif:GPSLongitude="126,58.70E"/></rdf:RDF></x:xmpmeta>')


def jpeg(path: str, w: int = 4000, h: int = 3000, seed: int = 0, quality: int = 92, orientation: int = 1,
         gps: bool = True, icc: bool = True, xmp: bool = False, detail: float = 0.35) -> str:
    img = picture(w, h, seed, detail)
    kwargs = {"quality": quality, "exif": exif_bytes(orientation, gps, w=w, h=h)}
    if icc:
        kwargs["icc_profile"] = srgb_icc()
    if xmp:
        kwargs["xmp"] = XMP_WITH_GPS
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    img.save(path, "JPEG", **kwargs)
    return path


def rotated_jpeg(path: str, w: int = 1200, h: int = 800) -> str:
    """Stored landscape with Orientation 6 (turn 90° clockwise to view): upright it is portrait.
    The top-left of the stored pixels is red; upright, red is in the top-right corner."""
    img = Image.new("RGB", (w, h), (40, 120, 200))
    ImageDraw.Draw(img).rectangle((0, 0, w // 4, h // 4), fill=(255, 0, 0))
    img = Image.blend(img, picture(w, h, 7, 1.0), 0.15)
    img.save(path, "JPEG", quality=95, exif=exif_bytes(6, True, w=w, h=h))
    return path


def png_transparent(path: str, w: int = 1600, h: int = 1200) -> str:
    img = picture(w, h, 3, 0.2).convert("RGBA")
    alpha = Image.new("L", (w, h), 0)
    ImageDraw.Draw(alpha).ellipse((w // 8, h // 8, w * 7 // 8, h * 7 // 8), fill=255)
    img.putalpha(alpha)
    img.save(path, "PNG")
    return path


def png_opaque(path: str, w: int = 1600, h: int = 1200) -> str:
    picture(w, h, 4, 0.25).save(path, "PNG")
    return path


def save_heic(img: Image.Image, path: str, quality: int = 90, exif: bytes = b"", icc: bytes = b"") -> str:
    """Write a HEIC with pillow-heif's encoder (the program itself only reads, with pi-heif).
    pillow-heif is NOT registered as a Pillow plugin, so the program under test still opens
    every HEIC with pi-heif."""
    import pillow_heif

    heif = pillow_heif.from_pillow(img)
    if exif:
        heif.info["exif"] = exif
    if icc:
        heif.info["icc_profile"] = icc
    heif.save(path, quality=quality)
    return path


def heic(path: str, w: int = 2000, h: int = 1500, gps: bool = True) -> str:
    img = picture(w, h, 5, 0.3)
    return save_heic(img, path, 90, exif_bytes(1, gps, w=w, h=h), srgb_icc())


def small_jpeg(path: str, w: int = 320, h: int = 240) -> str:
    """Already small and saved at a low quality: re-encoding cannot beat it."""
    picture(w, h, 9, 0.3).save(path, "JPEG", quality=40, exif=exif_bytes(1, True, w=w, h=h))
    return path


def make_all(folder: str) -> list[str]:
    """A small mixed folder (with a subfolder) for GUI tests and screenshots."""
    os.makedirs(os.path.join(folder, "trip"), exist_ok=True)
    out = [
        jpeg(os.path.join(folder, "IMG_0001.jpg"), 3000, 2000, seed=1),
        jpeg(os.path.join(folder, "IMG_0002.jpg"), 2400, 1800, seed=2),
        rotated_jpeg(os.path.join(folder, "IMG_0003.jpg")),
        png_transparent(os.path.join(folder, "logo.png"), 800, 600),
        heic(os.path.join(folder, "trip", "IMG_1001.heic"), 1600, 1200),
        jpeg(os.path.join(folder, "trip", "IMG_1002.jpg"), 2000, 1500, seed=3),
        small_jpeg(os.path.join(folder, "thumb.jpg")),
    ]
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "out")
    for p in make_all(target):
        print(p, os.path.getsize(p))
