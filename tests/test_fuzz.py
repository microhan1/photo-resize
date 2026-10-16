"""Random photos x random options, checked against the promises that hold for every input.

    PHOTO_RESIZE_FUZZ_SEEDS=300 python -m pytest tests/test_fuzz.py -q     # more cases
    python -m pytest tests/test_fuzz.py -q -k seed17                         # replay one

Each seed builds a small folder of generated pictures (size, aspect, pixel mode, file
format, EXIF orientation, location, transparency all drawn from the seed) and runs one
batch with options drawn from the same seed.
"""
from __future__ import annotations

import os
import random

import piexif
import pytest
from PIL import Image

import make_samples as ms
import shrink
from conftest import files_under, snapshot

SEEDS = int(os.environ.get("PHOTO_RESIZE_FUZZ_SEEDS", "40"))
FORMATS = [("JPEG", ".jpg"), ("PNG", ".png"), ("WEBP", ".webp"), ("TIFF", ".tif"), ("BMP", ".bmp"),
           ("HEIF", ".heic")]
MODES_PIX = ["RGB", "RGB", "RGB", "L", "RGBA", "P", "CMYK", "LA"]


def make_picture(rnd: random.Random, folder, n: int):
    fmt, ext = rnd.choice(FORMATS)
    mode = rnd.choice(MODES_PIX)
    if fmt == "JPEG" and mode not in ("RGB", "L", "CMYK"):
        mode = "RGB"
    if fmt in ("BMP",) and mode in ("RGBA", "LA", "CMYK"):
        mode = "RGB"
    if fmt in ("WEBP", "HEIF") and mode in ("CMYK", "LA", "P"):
        mode = "RGB"
    if fmt == "PNG" and mode == "CMYK":
        mode = "RGB"
    if fmt == "HEIF" and mode == "L":
        mode = "RGB"
    long_edge = rnd.choice([8, 33, 160, 500, 900, 1600, 2400])
    aspect = rnd.choice([1.0, 1.333, 1.5, 0.75, 0.5625, 3.0, 0.2, 12.0])
    w = max(1, int(long_edge if aspect >= 1 else long_edge * aspect))
    h = max(1, int(long_edge / aspect if aspect >= 1 else long_edge))
    img = ms.picture(w, h, rnd.randrange(10_000), rnd.choice([0.05, 0.3, 0.6]))
    if mode in ("RGBA", "LA"):
        alpha = Image.new("L", (w, h), rnd.choice([0, 128, 255]))
        img = img.convert(mode[:-1] if mode == "LA" else "RGB").convert(mode)
        img.putalpha(alpha)
    elif mode == "P":
        img = img.convert("P", palette=Image.Palette.ADAPTIVE)
    elif mode != "RGB":
        img = img.convert(mode)
    orientation = rnd.choice([1, 1, 3, 6, 8, 2, 5, 7, 4])
    gps = rnd.random() < 0.7
    kwargs = {}
    if fmt in ("JPEG", "PNG", "WEBP", "TIFF", "HEIF"):
        kwargs["exif"] = ms.exif_bytes(orientation, gps, w=w, h=h)
    if fmt == "JPEG":
        kwargs["quality"] = rnd.choice([40, 75, 92, 100])
    if fmt == "HEIF":
        import pillow_heif

        pillow_heif.register_heif_opener()
        kwargs["quality"] = 90
    sub = folder / rnd.choice(["", "a", "a/b"])
    os.makedirs(sub, exist_ok=True)
    name = rnd.choice(["IMG_{n}", "사진 {n}", "photo {n} #&%", "IMG_{n}_small_not"]).format(n=n)
    path = sub / (name + (ext.upper() if rnd.random() < 0.2 else ext))
    img.save(path, fmt, **kwargs)
    return path, (gps and fmt != "BMP"), (w, h), fmt


def random_options(rnd: random.Random) -> shrink.Options:
    return shrink.Options(mode=rnd.choice(shrink.MODES),
                          target_kb=rnd.choice([10, 30, 100, 200, 500, 1000, 2000, rnd.randrange(10, 3000)]),
                          long_edge=rnd.choice(list(shrink.SIZES) + [64, 333]),
                          quality=rnd.choice(list(shrink.QUALITY_LEVELS.values()) + [61, 94]),
                          output=rnd.choice(shrink.OUTPUTS), keep_png=rnd.random() < 0.4).validated()


@pytest.mark.parametrize("seed", range(SEEDS), ids=lambda s: f"seed{s}")
def test_promises_hold_for_random_photos(tmp_path, seed):
    rnd = random.Random(seed)
    folder = tmp_path / "in"
    made = {}
    for n in range(rnd.randint(1, 5)):
        path, gps, size, fmt = make_picture(rnd, folder, n)
        made[os.path.normcase(str(path))] = (gps, size, fmt)
    opts = random_options(rnd)
    before = snapshot(folder)

    items, missing = shrink.collect([str(folder)])
    assert not missing and len(items) == len(made)
    jobs = shrink.plan(items, opts)
    results = shrink.run_batch(jobs, opts)

    # 1. originals untouched (bytes and modified time), nothing outside the results added
    after = snapshot(folder)
    assert {k: v for k, v in after.items() if k in before} == before
    new = set(after) - set(before)
    assert not any(k.endswith(".part") for k in new)
    written = [r for r in results if r.dst]
    assert len(new) == len(written) == len({os.path.normcase(r.dst) for r in written})

    for r in results:
        gps, size, fmt = made[os.path.normcase(r.src)]
        assert r.status in (shrink.DONE, shrink.OVER, shrink.SMALL), (r.src, r.error)
        if not r.dst:
            assert r.status in (shrink.SMALL, shrink.OVER)
            continue
        # 2. the result is a whole, readable picture, smaller than the original
        out_size = os.path.getsize(r.dst)
        assert out_size == r.out_size < r.in_size
        with Image.open(r.dst) as im:
            im.load()
            assert im.size == tuple(r.out_pixels)
            assert im.format == ("PNG" if r.dst.lower().endswith(".png") else "JPEG")
            raw = im.info.get("exif")
            assert "xmp" not in im.info
        # 3. no location, upright
        if raw:
            ex = piexif.load(raw)
            assert ex["GPS"] == {} and piexif.ImageIFD.GPSTag not in ex["0th"]
            assert ex["0th"].get(piexif.ImageIFD.Orientation, 1) == 1
        assert r.gps_removed == r.had_gps
        # 4. the original's modified time
        assert os.stat(r.dst).st_mtime_ns == os.stat(r.src).st_mtime_ns
        # 5. the mode's own promise
        upright = tuple(r.in_pixels)
        if opts.mode == shrink.TARGET and r.status == shrink.DONE:
            assert out_size <= opts.target_bytes
        if opts.mode == shrink.SIZE:
            assert max(r.out_pixels) <= max(opts.long_edge, max(upright))
            assert max(r.out_pixels) <= max(upright)  # never enlarged
            if max(upright) > 2:
                ratio_in = upright[0] / upright[1]
                ratio_out = r.out_pixels[0] / r.out_pixels[1]
                assert abs(ratio_in - ratio_out) / ratio_in < 0.5 or min(r.out_pixels) == 1
        if opts.mode == shrink.QUALITY:
            assert tuple(r.out_pixels) == upright
        # 6. where it went
        if opts.output == shrink.SUFFIX:
            assert os.path.dirname(r.dst) == os.path.dirname(r.src)
            assert os.path.splitext(os.path.basename(r.dst))[0].split(" (")[0].endswith("_small")
        else:
            assert f"{os.sep}_small" in r.dst

    # 7. a second run reads the same photos only, and still changes no original
    items2, _ = shrink.collect([str(folder)])
    assert sorted(i.src for i in items2) == sorted(i.src for i in items)
