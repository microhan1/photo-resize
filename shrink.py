"""Make photos smaller: under a target file size, to a long edge, or at a JPEG quality.

Everything the GUI and the CLI share lives here: collecting files, naming the results,
reading and writing photos and their EXIF, the target-size search and the batch runner.

Rules that never change (PRD v0.1):
- The original is never written to. Results go to a new name; an existing name gets
  " (2)", " (3)"... and a result is created with an exclusive open, so nothing is replaced.
- A result that would not be smaller than its original is not written ("already small").
- Location (GPS) is always removed: the EXIF GPS block, and XMP (which may carry it too).
  Orientation is applied to the pixels (tag set to 1), the capture date and the colour
  profile are kept, and the result's modified time is the original's.
"""
from __future__ import annotations

import concurrent.futures
import contextlib
import dataclasses
import io
import math
import os
import re
import sys
import threading
import time
import uuid
import warnings
from typing import Callable, Iterable

# ---------------------------------------------------------------- constants
EXTS = (".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".heic", ".heif", ".webp", ".bmp", ".tif", ".tiff")
OUT_DIR = "_small"  # results folder inside the source folder (folder output)
OUT_SUFFIX = "_small"  # added to the file name (suffix output)

TARGET, SIZE, QUALITY = "target", "size", "quality"
MODES = (TARGET, SIZE, QUALITY)
FOLDER, SUFFIX = "folder", "suffix"
OUTPUTS = (FOLDER, SUFFIX)

KB = 1000  # targets count 1 KB as 1000 bytes, so "500KB" fits whichever way a site counts
TARGET_PRESETS_KB = (200, 500, 1000, 2000)
TARGET_MIN_KB, TARGET_MAX_KB = 10, 100_000
DEFAULT_TARGET_KB = 500

SIZES = (3840, 2560, 1920, 1280, 800)  # long edge presets (px)
SIZE_MIN, SIZE_MAX = 64, 20_000
DEFAULT_SIZE = 1920
SIZE_QUALITY = 85  # JPEG quality of the size mode

QUALITY_LEVELS = {"high": 85, "medium": 75, "low": 60}
DEFAULT_QUALITY_LEVEL = "medium"

MIN_QUALITY, MAX_QUALITY = 60, 95  # the target search never goes below 60 nor above 95
SCALE_STEP = 0.85  # when quality 60 is still too big: long edge x 0.85 (or less when far off)
MIN_EDGE = 160  # the search gives up below this long edge ("over target")
TIME_LIMIT = 60.0  # seconds per photo for the target search (a 108 MP photo takes about 10 s)
WORKERS = max(1, min(4, os.cpu_count() or 1))
MAX_PIXELS = 300_000_000  # a 200-megapixel phone photo must open (Pillow stops at 179 MP by default)
BIG_PIXELS = 40_000_000  # photos above this are shrunk one at a time (memory)
EXIF_LIMIT = 65_000  # a JPEG APP1 segment holds at most 65533 bytes

# statuses
DONE, OVER, SMALL, FAILED, CANCELLED = "done", "over", "small", "failed", "cancelled"

ORIENTATION = 0x0112
GPS_IFD = 0x8825
WHITE = (255, 255, 255)

_heif_lock = threading.Lock()
_heif_ready = False
_big_lock = threading.Lock()


def _pillow_limits() -> None:
    from PIL import Image

    if Image.MAX_IMAGE_PIXELS is not None and Image.MAX_IMAGE_PIXELS < MAX_PIXELS:
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    warnings.filterwarnings("ignore", category=Image.DecompressionBombWarning)


class Cancelled(Exception):
    pass


def register_heif() -> bool:
    """pillow-heif as a Pillow plugin (HEIC/HEIF). False when it cannot be loaded."""
    global _heif_ready
    with _heif_lock:
        if not _heif_ready:
            try:
                import pillow_heif

                pillow_heif.register_heif_opener()
                _heif_ready = True
            except Exception:
                return False
    return True


def fs(path: str) -> str:
    """Long paths (over MAX_PATH) work with the \\\\?\\ prefix on Windows."""
    if sys.platform != "win32" or len(path) < 240 or path.startswith("\\\\?\\"):
        return path
    path = os.path.abspath(path)
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


# ---------------------------------------------------------------- options
@dataclasses.dataclass
class Options:
    mode: str = TARGET
    target_kb: int = DEFAULT_TARGET_KB
    long_edge: int = DEFAULT_SIZE
    quality: int = QUALITY_LEVELS[DEFAULT_QUALITY_LEVEL]
    output: str = FOLDER
    keep_png: bool = False  # transparent PNGs stay PNG (transparency kept, smaller gain)

    def validated(self) -> "Options":
        o = dataclasses.replace(self)
        if o.mode not in MODES:
            o.mode = TARGET
        if o.output not in OUTPUTS:
            o.output = FOLDER
        o.target_kb = _clamp_int(o.target_kb, TARGET_MIN_KB, TARGET_MAX_KB, DEFAULT_TARGET_KB)
        o.long_edge = _clamp_int(o.long_edge, SIZE_MIN, SIZE_MAX, DEFAULT_SIZE)
        o.quality = _clamp_int(o.quality, MIN_QUALITY, MAX_QUALITY, QUALITY_LEVELS[DEFAULT_QUALITY_LEVEL])
        o.keep_png = bool(o.keep_png)
        return o

    @property
    def target_bytes(self) -> int:
        return self.target_kb * KB


def _clamp_int(value, lo: int, hi: int, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def parse_size(text: str) -> int | None:
    """'500KB', '1MB', '1.5 mb', '300' (KB) -> KB, or None."""
    m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*(kb|k|mb|m)?\s*", str(text), re.IGNORECASE)
    if not m:
        return None
    n = float(m.group(1).replace(",", "."))
    unit = (m.group(2) or "kb").lower()
    kb = n * 1000 if unit in ("mb", "m") else n
    return int(round(kb)) if kb > 0 else None


def format_target(kb: int) -> str:
    """500 -> '500KB', 1000 -> '1MB', 1500 -> '1.5MB'."""
    if kb >= 1000 and kb % 100 == 0:
        mb = kb / 1000
        return f"{mb:g}MB"
    return f"{kb}KB"


def format_bytes(n: int) -> str:
    """Like Windows Explorer (1 KB = 1024 bytes)."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 / 1024:.1f} MB"
    return f"{n / 1024 ** 3:.2f} GB"


# ---------------------------------------------------------------- collecting
@dataclasses.dataclass
class Item:
    src: str  # the photo
    base: str  # folder whose structure the results keep (the dropped folder, or the photo's folder)
    size: int = 0


def is_photo(name: str) -> bool:
    return name.lower().endswith(EXTS) and not name.startswith("._")


_RESULT_NAME = re.compile(re.escape(OUT_SUFFIX) + r"(?: \(\d+\))?$", re.IGNORECASE)
_RESULT_DIR = re.compile(re.escape(OUT_DIR) + r"(?: \(\d+\))?$", re.IGNORECASE)


def is_result_dir(name: str) -> bool:
    """_small, or _small (2) when a file was already called _small."""
    return bool(_RESULT_DIR.fullmatch(name))


def looks_like_result(name: str) -> bool:
    """photo_small.jpg / photo_small (2).jpg: a result of the suffix output."""
    return bool(_RESULT_NAME.search(os.path.splitext(name)[0]))


def _walk(folder: str, recursive: bool) -> Iterable[str]:
    """Photos under folder, sorted by path; never enters a results folder, a symlink or a junction."""
    try:
        entries = sorted(os.scandir(fs(folder)), key=lambda e: e.name.lower())
    except OSError:
        return
    dirs = []
    for e in entries:
        try:
            if e.is_symlink() or (hasattr(e, "is_junction") and e.is_junction()):
                continue
            if e.is_dir():
                if not is_result_dir(e.name):
                    dirs.append(e.name)
            elif e.is_file() and is_photo(e.name) and not looks_like_result(e.name):
                yield os.path.join(folder, e.name)
        except OSError:
            continue
    if recursive:
        for d in dirs:
            yield from _walk(os.path.join(folder, d), recursive)


def collect(paths: Iterable[str], recursive: bool = True, known: set[str] | None = None) -> tuple[list[Item], list[str]]:
    """Files and folders -> photos (no duplicates). Returns (items, paths that do not exist)."""
    seen = set() if known is None else known
    items, missing = [], []
    for p in paths:
        p = os.path.abspath(str(p))
        if os.path.isdir(fs(p)):
            pairs = [(f, p) for f in _walk(p, recursive)]
        elif os.path.isfile(fs(p)):
            pairs = [(p, os.path.dirname(p))] if is_photo(os.path.basename(p)) else []
        else:
            missing.append(p)
            continue
        for f, base in pairs:
            key = os.path.normcase(f)
            if key in seen:
                continue
            seen.add(key)
            try:
                size = os.path.getsize(fs(f))
            except OSError:
                size = 0
            items.append(Item(f, base, size))
    return items, missing


# ---------------------------------------------------------------- naming
@dataclasses.dataclass
class Job:
    item: Item
    dst: str  # final path of the result (JPEG)
    fmt: str  # "PNG" when it may stay PNG (keep PNG, and the header has an alpha channel), else "JPEG"
    dst_png: str = ""  # its path if it does stay PNG (decided once the pixels are read)


def output_format(src: str, keep_png: bool) -> str:
    """"PNG" when the photo may stay PNG ("keep PNG" is on and the PNG has an alpha channel),
    else "JPEG". Reads the header only; final_format() decides from the pixels, because a
    Windows screenshot is an RGBA PNG without one transparent pixel."""
    if not keep_png or not src.lower().endswith(".png"):
        return "JPEG"
    from PIL import Image

    try:
        with Image.open(fs(src)) as im:
            if im.mode in ("RGBA", "LA", "PA", "RGBa", "La") or "transparency" in im.info:
                return "PNG"
    except Exception:
        pass
    return "JPEG"


def _free_name(path: str, taken: set[str]) -> str:
    stem, ext = os.path.splitext(path)
    n = 1
    cand = path
    while os.path.normcase(cand) in taken or os.path.lexists(fs(cand)):
        n += 1
        cand = f"{stem} ({n}){ext}"
    return cand


def out_dir_name(base: str) -> str:
    """_small, unless something that is not a folder holds that name: then _small (2)..."""
    name, n = OUT_DIR, 1
    while os.path.lexists(fs(os.path.join(base, name))) and not os.path.isdir(fs(os.path.join(base, name))):
        n += 1
        name = f"{OUT_DIR} ({n})"
    return name


def result_path(item: Item, output: str, fmt: str, out_dir: str = OUT_DIR) -> str:
    folder, name = os.path.split(item.src)
    stem = os.path.splitext(name)[0]
    ext = ".png" if fmt == "PNG" else ".jpg"
    if output == SUFFIX:
        return os.path.join(folder, stem + OUT_SUFFIX + ext)
    rel = os.path.relpath(folder, item.base)
    parts = [item.base, out_dir] + ([] if rel == "." else [rel])
    return os.path.join(*parts, stem + ext)


def plan(items: list[Item], opts: Options) -> list[Job]:
    """Result names for a batch, decided up front and in order, so two photos never get one
    name (a.png and a.jpg -> a.jpg and a (2).jpg) and the original is never a target."""
    opts = opts.validated()
    taken = {os.path.normcase(i.src) for i in items}
    out_dirs: dict[str, str] = {}
    jobs = []
    for item in items:
        fmt = output_format(item.src, opts.keep_png)
        key = os.path.normcase(item.base)
        if key not in out_dirs:
            out_dirs[key] = out_dir_name(item.base)
        dst = _free_name(result_path(item, opts.output, "JPEG", out_dirs[key]), taken)
        taken.add(os.path.normcase(dst))
        dst_png = ""
        if fmt == "PNG":  # both names are kept: which one is used depends on the pixels
            dst_png = _free_name(result_path(item, opts.output, "PNG", out_dirs[key]), taken)
            taken.add(os.path.normcase(dst_png))
        jobs.append(Job(item, dst, fmt, dst_png))
    return jobs


def final_format(fmt: str, src: "Source") -> str:
    """PNG only when it may stay PNG and some pixel really is transparent."""
    return "PNG" if fmt == "PNG" and src.transparent else "JPEG"


# ---------------------------------------------------------------- reading
@dataclasses.dataclass
class Source:
    image: object  # PIL image, upright, mode RGB/L/RGBA/LA
    exif: bytes  # cleaned EXIF for the result (no GPS, Orientation 1)
    icc: bytes
    had_gps: bool
    size: int  # bytes of the original
    pixels: tuple[int, int]  # upright size of the original
    transparent: bool = False  # some pixel is not fully opaque


def _to_8bit(im):
    """16-bit, 32-bit and float greyscale (PNG/TIFF) to 8-bit L, scaled by the range the
    values really use (convert() alone would clip everything over 255 to white)."""
    if im.mode.startswith("I;16"):
        im = im.convert("I")
    if im.mode not in ("I", "F"):
        return im
    lo, hi = im.getextrema()
    if im.mode == "F" and hi <= 1.0:
        scale = 255.0  # 0..1 floats
    elif hi <= 255:
        scale = 1.0
    elif hi <= 65535:
        scale = 1 / 257  # 16-bit
    else:
        scale = 255.0 / hi
    return im.point(lambda v: v * scale).convert("L")


def _has_alpha(im) -> bool:
    if im.mode in ("RGBA", "LA", "PA", "RGBa", "La"):
        return True
    return im.mode == "P" and "transparency" in im.info


def _normalize(im, icc: bytes):
    """Pixels the encoders take: RGB, L, RGBA or LA. CMYK goes to RGB (through its profile)."""
    im = _to_8bit(im)
    if im.mode == "1":
        im = im.convert("L")
    if im.mode == "P":
        im = im.convert("RGBA" if "transparency" in im.info else "RGB")
    if im.mode in ("PA", "RGBa", "La"):
        im = im.convert("RGBA")
    if im.mode == "CMYK":
        converted = None
        if icc:
            try:
                from PIL import ImageCms

                src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
                converted = ImageCms.profileToProfile(im, src, ImageCms.createProfile("sRGB"), outputMode="RGB")
            except Exception:
                converted = None
        im = converted if converted is not None else im.convert("RGB")
        icc = b""  # the CMYK profile does not describe RGB pixels
    if im.mode not in ("RGB", "L", "RGBA", "LA"):
        im = im.convert("RGB")
    return im, icc


def _raw_exif(im) -> bytes:
    data = im.info.get("exif") or b""
    if isinstance(data, str):
        data = data.encode("latin-1", "ignore")
    if data.startswith(b"Exif\x00\x00"):
        data = data[6:]
    return bytes(data)


# Tags of the first IFD that do not belong in the result: the picture layout of a TIFF
# (strips, tiles, compression...), and blocks that can carry a location of their own (XMP,
# IPTC, Photoshop resources), besides the GPS pointer itself. The ICC profile is written
# separately.
DROP_0TH = {256, 257, 258, 259, 262, 273, 277, 278, 279, 284, 317, 322, 323, 324, 325, 338, 339, 513, 514, 530,
            531, 532, 700, 33723, 34377, 34675, GPS_IFD}
MAKER_NOTE, USER_COMMENT = 37500, 37510


def clean_exif(raw: bytes, width: int, height: int) -> tuple[bytes, bool]:
    """EXIF for the result: no GPS block (nor XMP/IPTC hidden in the first IFD), Orientation
    1, the new pixel size, no thumbnail. Dates, camera and the rest stay. Returns (exif
    bytes, the original had GPS)."""
    if not raw:
        return b"", False
    import piexif

    try:
        data = piexif.load(b"Exif\x00\x00" + raw)
    except Exception:
        return _clean_exif_pillow(raw)
    had_gps = bool(data.get("GPS")) or piexif.ImageIFD.GPSTag in data.get("0th", {})
    data["GPS"] = {}
    for tag in DROP_0TH & set(data.get("0th", {})):
        del data["0th"][tag]
    data["0th"][piexif.ImageIFD.Orientation] = 1
    data.setdefault("Exif", {})
    data["Exif"][piexif.ExifIFD.PixelXDimension] = width
    data["Exif"][piexif.ExifIFD.PixelYDimension] = height
    data["thumbnail"] = None
    data["1st"] = {}
    try:
        return _fit_exif(piexif.dump(data), data), had_gps
    except Exception:
        pass
    for ifd in ("0th", "Exif", "Interop"):  # drop the tags piexif refuses to write, one by one
        for tag in list(data.get(ifd, {})):
            probe = {"0th": {}, "Exif": {}, "GPS": {}, "Interop": {}, "1st": {}, "thumbnail": None}
            probe[ifd] = {tag: data[ifd][tag]}
            try:
                piexif.dump(probe)
            except Exception:
                del data[ifd][tag]
    try:
        return _fit_exif(piexif.dump(data), data), had_gps
    except Exception:
        return _clean_exif_pillow(raw)


def _fit_exif(dumped: bytes, data: dict) -> bytes:
    """EXIF that fits one JPEG segment: without the maker note and comments when too big,
    then only the dates, camera and orientation."""
    import piexif

    if len(dumped) <= EXIF_LIMIT:
        return dumped
    data["Exif"].pop(MAKER_NOTE, None)
    data["Exif"].pop(USER_COMMENT, None)
    data["Interop"] = {}
    dumped = piexif.dump(data)
    if len(dumped) <= EXIF_LIMIT:
        return dumped
    keep0 = {k: v for k, v in data["0th"].items() if k in (271, 272, 274, 306, 305)}
    keep_e = {k: v for k, v in data["Exif"].items() if k in (36867, 36868, 40962, 40963)}
    dumped = piexif.dump({"0th": keep0, "Exif": keep_e, "GPS": {}, "Interop": {}, "1st": {}, "thumbnail": None})
    return dumped if len(dumped) <= EXIF_LIMIT else b""


def _clean_exif_pillow(raw: bytes) -> tuple[bytes, bool]:
    """Pillow's reader for EXIF piexif cannot parse; if that fails too, no EXIF at all
    (which also means no location)."""
    from PIL import Image

    try:
        ex = Image.Exif()
        ex.load(b"Exif\x00\x00" + raw)
        had_gps = GPS_IFD in ex
        for tag in DROP_0TH & set(ex):
            del ex[tag]
        ex[ORIENTATION] = 1
        out = ex.tobytes()
        return (out if len(out) <= EXIF_LIMIT else b""), had_gps
    except Exception:
        return b"", b"GPS" in raw


def open_source(src: str) -> Source:
    """Read a photo upright with its cleaned metadata. Raises on unreadable files."""
    from PIL import Image, ImageOps

    if src.lower().endswith((".heic", ".heif")):
        register_heif()
    _pillow_limits()
    size = os.path.getsize(fs(src))
    with Image.open(fs(src)) as im:
        raw = _raw_exif(im)
        if not raw:  # TIFF keeps its EXIF as tags of the image itself, not as an "exif" block
            try:
                ex = im.getexif()
                if len(ex):
                    raw = ex.tobytes()
                    raw = raw[6:] if raw.startswith(b"Exif\x00\x00") else raw
            except Exception:
                raw = b""
        icc = im.info.get("icc_profile") or b""
        if getattr(im, "n_frames", 1) > 1:
            im.seek(0)  # bursts and animations: the first image
        pic = ImageOps.exif_transpose(im)  # turns the pixels; HEIC comes upright already
        pic.load()
    pic, icc = _normalize(pic, icc)
    pic.info = {}  # nothing (XMP, comments, text chunks) rides along into the result
    exif, had_gps = clean_exif(raw, pic.width, pic.height)
    transparent = pic.mode in ("RGBA", "LA") and pic.getchannel("A").getextrema()[0] < 255
    return Source(pic, exif, icc, had_gps, size, pic.size, transparent)


# ---------------------------------------------------------------- encoding
def _flatten(im):
    """Transparent pixels over white for JPEG."""
    if im.mode in ("RGB", "L"):
        return im
    from PIL import Image

    rgba = im.convert("RGBA")
    bg = Image.new("RGB", im.size, WHITE)
    bg.paste(rgba, mask=rgba.getchannel("A"))
    return bg.convert("L") if im.mode == "LA" else bg


PNG_SEARCH_LEVEL = 6  # zlib level while searching: 10x faster than 9, about 9% bigger
PNG_FINAL_LEVEL = 9


def encode(im, fmt: str, quality: int, exif: bytes, icc: bytes, level: int = PNG_FINAL_LEVEL) -> bytes:
    buf = io.BytesIO()
    kwargs = {}
    if exif:
        kwargs["exif"] = exif
    if icc:
        kwargs["icc_profile"] = icc
    if fmt == "PNG":
        im.save(buf, "PNG", compress_level=level, **kwargs)
    else:
        _flatten(im).save(buf, "JPEG", quality=int(quality), optimize=True, **kwargs)
    return buf.getvalue()


def _resized(im, long_edge: int):
    from PIL import Image

    w, h = im.size
    if max(w, h) <= long_edge:
        return im
    s = long_edge / max(w, h)
    size = (max(1, round(w * s)), max(1, round(h * s)))
    return im.resize(size, Image.Resampling.LANCZOS, reducing_gap=3.0)


@dataclasses.dataclass
class Encoded:
    data: bytes
    pixels: tuple[int, int]
    quality: int  # 0 for PNG
    fits: bool  # under the target (always True outside the target mode)
    tries: int = 0


def _search_target(src: Source, fmt: str, target: int, cancel: threading.Event | None, deadline: float) -> Encoded:
    """Best picture under `target` bytes: at the full size, the highest JPEG quality in
    [60, 95] that fits (binary search); if even 60 is too big, a smaller long edge and
    search again. When nothing fits (time limit, MIN_EDGE), the smallest one made."""
    pic = src.image
    long0 = max(pic.size)
    edge = long0
    smallest: Encoded | None = None
    tries = 0

    def enc(im, q, level=PNG_SEARCH_LEVEL):
        nonlocal tries
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        tries += 1
        return encode(im, fmt, q, src.exif, src.icc, level)

    floor = 0 if fmt == "PNG" else MIN_QUALITY
    too_big: int | None = None  # the last long edge that did not fit at the floor quality
    while True:
        im = _resized(pic, edge)
        data, q = enc(im, floor), floor
        if len(data) <= target:
            if too_big is not None:
                # The jump down may have overshot: keep as many pixels as fit at the floor
                # quality (PRD: quality goes down first, the size only as far as needed).
                lo, hi = edge, too_big
                while hi - lo > max(8, long0 // 200) and time.monotonic() <= deadline:
                    mid = (lo + hi) // 2
                    im2 = _resized(pic, mid)
                    d2 = enc(im2, floor)
                    if len(d2) <= target:
                        lo, im, data = mid, im2, d2
                    else:
                        hi = mid
            if fmt == "PNG":
                final = enc(im, 0, PNG_FINAL_LEVEL)  # once, at the strongest level; never bigger
                return Encoded(final if len(final) < len(data) else data, im.size, 0, True, tries)
            best, lo, hi = data, MIN_QUALITY, MAX_QUALITY + 1
            top = enc(im, MAX_QUALITY)
            if len(top) <= target:
                return Encoded(top, im.size, MAX_QUALITY, True, tries)
            hi = MAX_QUALITY  # lo fits, hi does not
            while hi - lo > 1:
                mid = (lo + hi) // 2
                d = enc(im, mid)
                if len(d) <= target:
                    lo, best = mid, d
                else:
                    hi = mid
            return Encoded(best, im.size, lo, True, tries)
        if smallest is None or len(data) < len(smallest.data):
            smallest = Encoded(data, im.size, q, False, tries)
        if edge <= MIN_EDGE or time.monotonic() > deadline:
            smallest.tries = tries
            return smallest
        too_big = edge
        # bytes grow about with the pixel count: aim near the target, but step at least 0.85
        step = min(SCALE_STEP, max(0.5, math.sqrt(target / len(data)) * 0.97))
        edge = max(MIN_EDGE, int(edge * step))


def shrink(src: Source, fmt: str, opts: Options, cancel: threading.Event | None = None) -> Encoded:
    """The result's bytes for one photo (nothing is written)."""
    opts = opts.validated()
    if opts.mode == TARGET:
        # A photo already under the target still gets a result (without its location) when
        # one can be made smaller than it; never one that is bigger.
        target = min(opts.target_bytes, max(1, src.size - 1))
        out = _search_target(src, fmt, target, cancel, time.monotonic() + TIME_LIMIT)
        out.fits = len(out.data) <= opts.target_bytes
        return out
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    if opts.mode == SIZE:
        im, q = _resized(src.image, opts.long_edge), SIZE_QUALITY
    else:
        im, q = src.image, opts.quality
    data = encode(im, fmt, q, src.exif, src.icc)
    return Encoded(data, im.size, 0 if fmt == "PNG" else q, True, 1)


# ---------------------------------------------------------------- one photo, a batch
@dataclasses.dataclass
class Result:
    src: str
    dst: str = ""  # "" when nothing was written
    status: str = FAILED
    in_size: int = 0
    out_size: int = 0
    in_pixels: tuple[int, int] = (0, 0)
    out_pixels: tuple[int, int] = (0, 0)
    quality: int = 0
    gps_removed: bool = False  # the result was written without the original's location
    had_gps: bool = False
    error: str = ""
    seconds: float = 0.0


def _write_new(path: str, data: bytes, cancel: threading.Event | None) -> str:
    """Create `path` with `data` and return the name used; never replaces anything. The
    bytes go to a temporary "<name>.<random>.part" first and are renamed (rename refuses to
    replace), so a half-written file never sits under the final name and nothing is left
    behind on failure. A name taken since the plan was made gets the next number."""
    os.makedirs(fs(os.path.dirname(path)), exist_ok=True)
    part = f"{path}.{uuid.uuid4().hex[:8]}.part"
    try:
        with open(fs(part), "xb") as f:
            f.write(data)
        for _ in range(1000):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            try:
                os.rename(fs(part), fs(path))
                return path
            except FileExistsError:
                path = _free_name(path, set())
        raise FileExistsError(path)
    except BaseException:
        try:
            os.remove(fs(part))
        except OSError:
            pass
        raise


def _pixel_count(src: str) -> int:
    from PIL import Image

    try:
        if src.lower().endswith((".heic", ".heif")):
            register_heif()
        _pillow_limits()
        with Image.open(fs(src)) as im:
            return im.width * im.height
    except Exception:
        return 0


def process(job: Job, opts: Options, cancel: threading.Event | None = None, write: bool = True) -> Result:
    """Shrink one photo and (when write) save the result. Never raises."""
    t0 = time.monotonic()
    res = Result(job.item.src, in_size=job.item.size)
    try:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        big = _pixel_count(job.item.src) > BIG_PIXELS
        with _big_lock if big else contextlib.nullcontext():  # one huge photo in memory at a time
            src = open_source(job.item.src)
            res.in_size, res.in_pixels, res.had_gps = src.size, src.pixels, src.had_gps
            fmt = final_format(job.fmt, src)
            out = shrink(src, fmt, opts, cancel)
            del src
        res.out_size, res.out_pixels, res.quality = len(out.data), out.pixels, out.quality
        smaller = len(out.data) < res.in_size
        if not out.fits:
            res.status = OVER  # the smallest one made is kept, if it is smaller than the original
        elif not smaller:
            res.status = SMALL  # not smaller than the original: no result
        else:
            res.status = DONE
        if smaller:
            if write:
                dst = _write_new(job.dst_png if fmt == "PNG" and job.dst_png else job.dst, out.data, cancel)
                st = os.stat(fs(job.item.src))
                os.utime(fs(dst), ns=(st.st_atime_ns, st.st_mtime_ns))
                res.dst = dst
                res.gps_removed = res.had_gps
    except Cancelled:
        res.status = CANCELLED
    except Exception as exc:  # damaged file, unknown format, out of memory...
        res.status = FAILED
        res.error = f"{exc.__class__.__name__}: {exc}"[:300]
    res.seconds = time.monotonic() - t0
    return res


def run_batch(jobs: list[Job], opts: Options, cancel: threading.Event | None = None,
              on_result: Callable[[int, Result], None] | None = None, workers: int = WORKERS) -> list[Result]:
    """Every job, `workers` at a time; on_result(index, result) as each one finishes
    (called on a worker thread). One failing photo never stops the others."""
    opts = opts.validated()
    results: list[Result | None] = [None] * len(jobs)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(process, job, opts, cancel): i for i, job in enumerate(jobs)}
        for fut in concurrent.futures.as_completed(futures):
            i = futures[fut]
            results[i] = fut.result()
            if on_result is not None:
                on_result(i, results[i])
    return [r for r in results if r is not None]


@dataclasses.dataclass
class Summary:
    count: int = 0  # results written
    before: int = 0  # bytes of their originals
    after: int = 0  # bytes of the results
    over: int = 0
    small: int = 0
    failed: int = 0
    cancelled: int = 0
    gps: int = 0  # results written without the original's location

    @property
    def percent(self) -> int:
        return int(round(100 * (1 - self.after / self.before))) if self.before else 0


def summarize(results: Iterable[Result]) -> Summary:
    s = Summary()
    for r in results:
        if r.dst:
            s.count += 1
            s.before += r.in_size
            s.after += r.out_size
            s.gps += 1 if r.gps_removed else 0
        s.over += r.status == OVER
        s.small += r.status == SMALL
        s.failed += r.status == FAILED
        s.cancelled += r.status == CANCELLED
    return s


def expected_size(r: Result) -> int:
    """What the photo will take after the run: its result, or the original when none is made."""
    return r.out_size if r.out_size and r.out_size < r.in_size else r.in_size


def _kind(item: Item) -> str:
    ext = os.path.splitext(item.src)[1].lower()
    return {".jpeg": ".jpg", ".jpe": ".jpg", ".jfif": ".jpg", ".heif": ".heic", ".tiff": ".tif"}.get(ext, ext)


def sample_indices(items: list[Item], sample: int) -> list[int]:
    """Which photos the estimate really shrinks. How much a photo shrinks depends on its
    file type (a PNG screenshot and a camera JPG differ a lot) and on its size, so the
    samples are spread over both: one of each type first (the types holding the most bytes
    first), then more of the big types, each new one at another size step of its type."""
    groups: dict[str, list[int]] = {}
    for i, item in enumerate(items):
        groups.setdefault(_kind(item), []).append(i)
    for k in groups:
        groups[k].sort(key=lambda i: items[i].size)
    order = sorted(groups, key=lambda k: -sum(items[i].size for i in groups[k]))
    share = {k: 0 for k in order}
    total = min(sample, len(items))
    while sum(share.values()) < total:
        for k in order:  # round robin, the heaviest type first
            if share[k] < len(groups[k]) and sum(share.values()) < total:
                share[k] += 1
    picked = []
    for k in order:
        n, members = share[k], groups[k]
        for j in range(n):  # evenly spread over the sizes of this type (median first)
            pos = (len(members) - 1) // 2 if n == 1 else round(j * (len(members) - 1) / (n - 1))
            picked.append(members[pos])
    return sorted(set(picked))


def guess_sizes(items: list[Item], measured: dict[int, Result], opts: Options) -> dict[int, int]:
    """Expected bytes of the photos not measured yet, from the measured ones: per file type
    a straight line in log-log (result bytes against original bytes, slope 0..1), or the
    byte ratio when a type has fewer than two sizes measured. In the target mode never over
    the target. Chosen on real and generated folders (2026-10-16): steadier than a mean or
    the nearest sample, which swing with how text-heavy a screenshot is."""
    opts = opts.validated()
    pts: dict[str, list[tuple[float, float]]] = {}
    tot_in = tot_out = 0
    for i, r in measured.items():
        if r.status in (DONE, OVER, SMALL) and r.in_size:
            pts.setdefault(_kind(items[i]), []).append((math.log(r.in_size), math.log(max(1, expected_size(r)))))
            tot_in += r.in_size
            tot_out += expected_size(r)
    overall = (math.log(tot_out / tot_in), 1.0) if tot_in else (0.0, 1.0)  # log ratio, slope 1
    fits: dict[str, tuple[float, float]] = {}
    for kind, xy in pts.items():
        xs = [x for x, _ in xy]
        if len(set(xs)) >= 2:
            mx, my = sum(xs) / len(xs), sum(y for _, y in xy) / len(xy)
            b = sum((x - mx) * (y - my) for x, y in xy) / sum((x - mx) ** 2 for x in xs)
            b = max(0.0, min(1.0, b))
            fits[kind] = (my - b * mx, b)
        else:
            fits[kind] = (sum(y - x for x, y in xy) / len(xy), 1.0)
    out = {}
    for i, item in enumerate(items):
        if i in measured:
            continue
        a, b = fits.get(_kind(item), overall)
        size = max(1, item.size)
        guess = math.exp(a + b * math.log(size))
        if opts.mode == TARGET:
            guess = min(guess, opts.target_bytes * 0.97)  # results land just under the target
        out[i] = int(min(guess, item.size))
    return out


def _measure(item: Item, opts: Options, cancel) -> Result:
    r = process(Job(item, "", output_format(item.src, opts.keep_png)), opts, cancel, write=False)
    if r.status == CANCELLED:
        raise Cancelled()
    return r


def estimate(items: list[Item], opts: Options, cancel: threading.Event | None = None,
             sample: int = 3) -> tuple[dict[int, Result], dict[int, int]]:
    """Expected result sizes without writing anything: `sample` photos spread over file
    types and sizes are really shrunk in memory (exact); the others are guessed from them.
    Returns (measured results, guessed bytes) by index."""
    opts = opts.validated()
    measured: dict[int, Result] = {}
    for i in sample_indices(items, sample):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        measured[i] = _measure(items[i], opts, cancel)
    return measured, guess_sizes(items, measured, opts)


ESTIMATE_LIMIT = 400  # photos measured at most; past that the guesses are already close


def estimate_iter(items: list[Item], opts: Options, cancel: threading.Event | None = None, first: int = 12,
                  every: float = 1.0, workers: int | None = None, limit: int = ESTIMATE_LIMIT):
    """The estimate, getting better: yields (measured, guessed) after 3 and then `first`
    samples, then about every `every` seconds while more are measured (in a shuffled, so
    unbiased, order), and a last time when every photo - or `limit` of them - is measured.
    Nothing is written. Raises Cancelled when `cancel` is set."""
    import random

    opts = opts.validated()
    measured: dict[int, Result] = {}
    quick = sample_indices(items, min(3, first))  # a number on screen within a second or so
    head = [i for i in sample_indices(items, first) if i not in set(quick)]
    rest = [i for i in range(len(items)) if i not in set(quick) | set(head)]
    random.Random(len(items)).shuffle(rest)
    rest = rest[:max(0, limit - len(quick) - len(head))]
    n_workers = max(1, (workers or WORKERS) - 1)  # leave a core for the window

    def run(indices):
        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
            for i, r in zip(indices, pool.map(lambda i: _measure(items[i], opts, cancel), indices)):
                measured[i] = r

    for part in (quick, head):
        if part:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            run(part)
            yield dict(measured), guess_sizes(items, measured, opts)
    last = time.monotonic()
    chunk = max(4, n_workers * 2)
    for k in range(0, len(rest), chunk):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        run(rest[k:k + chunk])
        done = k + chunk >= len(rest)
        if done or time.monotonic() - last >= every:
            last = time.monotonic()
            yield dict(measured), guess_sizes(items, measured, opts)
