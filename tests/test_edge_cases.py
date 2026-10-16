"""Edge cases found by probing the engine (2026-10-16): every EXIF orientation, location
hidden in TIFF tags / PNG / WebP / XMP / IPTC, oversized EXIF, huge photos, odd files and
frames, the file system (a file called _small, stale .part files, a name taken mid-run,
write failures, long paths, junctions), and the optimality of the target search."""
from __future__ import annotations

import builtins
import os
import shutil
import subprocess
import sys
import threading
import unicodedata

import piexif
import pytest
from PIL import Image, ImageDraw

import make_samples as ms
import shrink
from conftest import files_under, sha1, snapshot


def run(paths, **kw):
    opts = shrink.Options(**kw)
    items, _ = shrink.collect([str(p) for p in paths])
    return shrink.run_batch(shrink.plan(items, opts), opts)


def exif_of(path) -> dict:
    with Image.open(path) as im:
        raw = im.info.get("exif")
    return piexif.load(raw) if raw else {}


def quadrants(w=600, h=400) -> Image.Image:
    """Upright reference picture: red top-left, green top-right, blue bottom-left, white bottom-right."""
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w // 2, h // 2), fill=(255, 0, 0))
    d.rectangle((w // 2, 0, w, h // 2), fill=(0, 255, 0))
    d.rectangle((0, h // 2, w // 2, h), fill=(0, 0, 255))
    d.rectangle((w // 2, h // 2, w, h), fill=(255, 255, 255))
    return img


# How to store an upright picture so that a viewer applying Orientation n shows it upright
# (the inverse of what ImageOps.exif_transpose does).
STORE = {1: [], 2: [Image.Transpose.FLIP_LEFT_RIGHT], 3: [Image.Transpose.ROTATE_180],
         4: [Image.Transpose.FLIP_TOP_BOTTOM], 5: [Image.Transpose.TRANSPOSE], 6: [Image.Transpose.ROTATE_90],
         7: [Image.Transpose.TRANSVERSE], 8: [Image.Transpose.ROTATE_270]}


def colour_at(im, fx, fy):
    return im.convert("RGB").getpixel((int(im.width * fx), int(im.height * fy)))


def close(c, want, tol=60):
    return all(abs(a - b) <= tol for a, b in zip(c, want))


# ------------------------------------------------------------------ orientation
@pytest.mark.parametrize("orientation", range(1, 9))
def test_every_orientation_comes_out_upright(tmp_path, orientation):
    upright = quadrants()
    stored = upright
    for op in STORE[orientation]:
        stored = stored.transpose(op)
    path = str(tmp_path / f"o{orientation}.jpg")
    stored.save(path, "JPEG", quality=95, exif=ms.exif_bytes(orientation, True))
    (r,) = run([path], target_kb=100)
    with Image.open(r.dst) as im:
        assert im.size == upright.size
        assert close(colour_at(im, 0.25, 0.25), (255, 0, 0))
        assert close(colour_at(im, 0.75, 0.25), (0, 255, 0))
        assert close(colour_at(im, 0.25, 0.75), (0, 0, 255))
        assert close(colour_at(im, 0.75, 0.75), (255, 255, 255))
    assert exif_of(r.dst)["0th"][piexif.ImageIFD.Orientation] == 1


def test_heic_with_orientation_comes_out_upright(tmp_path):
    upright = quadrants(900, 600)
    stored = upright.transpose(Image.Transpose.ROTATE_90)  # shown upright with Orientation 6
    path = ms.save_heic(stored, str(tmp_path / "rot.heic"), 95, ms.exif_bytes(6, True))
    (r,) = run([path], target_kb=200)
    with Image.open(r.dst) as im:
        assert abs(im.width / im.height - 1.5) < 0.01  # landscape again (the target may make it smaller)
        assert close(colour_at(im, 0.25, 0.25), (255, 0, 0)) and close(colour_at(im, 0.75, 0.75), (255, 255, 255))


# ------------------------------------------------------------------ location in other places
@pytest.mark.parametrize("fmt,ext", [("TIFF", ".tif"), ("PNG", ".png"), ("WEBP", ".webp")])
def test_location_in_tiff_png_and_webp(tmp_path, fmt, ext):
    path = str(tmp_path / f"g{ext}")
    kwargs = {"exif": ms.exif_bytes(1, True, w=800, h=600)}
    if fmt == "WEBP":
        kwargs["xmp"] = ms.XMP_WITH_GPS
    ms.picture(800, 600, 1).save(path, fmt, **kwargs)
    (r,) = run([path], target_kb=100)
    ex = exif_of(r.dst)
    assert r.status == shrink.DONE and r.had_gps and r.gps_removed
    assert ex["GPS"] == {} and piexif.ImageIFD.GPSTag not in ex["0th"]
    assert ex["Exif"][piexif.ExifIFD.DateTimeOriginal] == ms.DATE  # the date survives, TIFF included
    data = open(r.dst, "rb").read()
    assert b"GPSLatitude" not in data


def test_tiff_layout_tags_are_not_copied(tmp_path):
    path = str(tmp_path / "t.tif")
    ms.picture(800, 600, 1).save(path, "TIFF", exif=ms.exif_bytes(1, False))
    (r,) = run([path], target_kb=100)
    zeroth = exif_of(r.dst)["0th"]
    assert not ({273, 279, 259, 262, 278} & set(zeroth))  # strips, compression, colour layout
    assert zeroth[piexif.ImageIFD.Make] == b"SampleCam"


def test_xmp_and_iptc_inside_the_exif_block_are_dropped(tmp_path):
    ex = Image.Exif()
    ex.load(ms.exif_bytes(1, True))
    ex[700] = ms.XMP_WITH_GPS  # XMP packet as a TIFF tag
    ex[33723] = b"\x1c\x02\x5a\x00\x05Seoul"  # IPTC city
    path = str(tmp_path / "x.jpg")
    ms.picture(800, 600, 2).save(path, "JPEG", quality=95, exif=ex.tobytes())
    with Image.open(path) as im:
        assert 700 in im.getexif() and 33723 in im.getexif()  # the sample really carries them
    (r,) = run([path], target_kb=100)
    zeroth = exif_of(r.dst)["0th"]
    assert 700 not in zeroth and 33723 not in zeroth
    raw = open(r.dst, "rb").read()
    assert b"GPSLatitude" not in raw and b"Seoul" not in raw


def test_jpeg_comment_is_not_carried(tmp_path):
    path = str(tmp_path / "c.jpg")
    ms.picture(800, 600, 2).save(path, "JPEG", quality=95, comment=b"home 37.5665,126.9780")
    (r,) = run([path], target_kb=100)
    assert b"126.9780" not in open(r.dst, "rb").read()


def test_pillow_fallback_also_drops_location():
    raw = ms.exif_bytes(6, True)[6:]
    out, had = shrink._clean_exif_pillow(raw)
    ex = Image.Exif()
    ex.load(out)
    assert had and shrink.GPS_IFD not in ex and ex[shrink.ORIENTATION] == 1


def test_unreadable_exif_means_no_exif_at_all():
    out, had = shrink.clean_exif(b"\x00\x01garbage with GPS inside", 10, 10)
    assert out == b"" and had  # nothing to carry a location, and it is counted as removed


def test_exif_too_big_for_a_jpeg_segment(tmp_path):
    data = piexif.load(ms.exif_bytes(1, True))
    data["Exif"][piexif.ExifIFD.MakerNote] = b"M" * 70_000
    path = str(tmp_path / "big.png")
    ms.picture(800, 600, 2).save(path, "PNG", exif=piexif.dump(data))
    (r,) = run([path], target_kb=100)
    assert r.status == shrink.DONE
    ex = exif_of(r.dst)
    assert ex["Exif"][piexif.ExifIFD.DateTimeOriginal] == ms.DATE and ex["GPS"] == {}
    assert piexif.ExifIFD.MakerNote not in ex["Exif"]


# ------------------------------------------------------------------ the search itself
@pytest.mark.parametrize("seed,size,kb", [(1, (3000, 2000), 500), (3, (2000, 2000), 200), (4, (6000, 1000), 300)])
def test_size_is_kept_as_large_as_quality_60_allows(tmp_path, seed, size, kb):
    """PRD: quality first, the size only as far as needed. The long edge found is within
    1% of the largest one that fits at quality 60 (found here by a separate bisection)."""
    path = ms.jpeg(str(tmp_path / "p.jpg"), *size, seed=seed, detail=0.4)
    src = shrink.open_source(path)
    out = shrink.shrink(src, "JPEG", shrink.Options(target_kb=kb))
    target = kb * 1000
    assert out.fits and len(out.data) <= target
    lo, hi = 16, max(src.image.size)
    while hi - lo > 2:
        mid = (lo + hi) // 2
        if len(shrink.encode(shrink._resized(src.image, mid), "JPEG", 60, src.exif, src.icc)) <= target:
            lo = mid
        else:
            hi = mid
    assert max(out.pixels) >= lo * 0.99


def test_quality_is_the_best_by_brute_force(tmp_path):
    for seed, kb in ((5, 900), (6, 1500), (7, 700)):
        path = ms.jpeg(str(tmp_path / f"b{seed}.jpg"), 2400, 1600, seed=seed, detail=0.35)
        src = shrink.open_source(path)
        out = shrink.shrink(src, "JPEG", shrink.Options(target_kb=kb))
        im = shrink._resized(src.image, max(out.pixels))
        fitting = [q for q in range(60, 96) if len(shrink.encode(im, "JPEG", q, src.exif, src.icc)) <= kb * 1000]
        assert out.quality == max(fitting)


def test_smallest_custom_target_ends(tmp_path):
    path = ms.jpeg(str(tmp_path / "p.jpg"), 4000, 3000, seed=8, detail=0.5)
    (r,) = run([path], target_kb=shrink.TARGET_MIN_KB)
    assert r.status in (shrink.DONE, shrink.OVER) and r.seconds < shrink.TIME_LIMIT
    if r.status == shrink.DONE:
        assert r.out_size <= 10_000
    else:
        assert max(r.out_pixels) == shrink.MIN_EDGE


def test_keep_png_with_a_tiny_target_ends(tmp_path):
    path = ms.png_transparent(str(tmp_path / "t.png"), 1600, 1200)
    (r,) = run([path], target_kb=10, keep_png=True)
    assert r.status in (shrink.DONE, shrink.OVER)
    with Image.open(r.dst) as im:
        assert im.format == "PNG" and im.mode == "RGBA"


def test_same_photo_gives_the_same_bytes(tmp_path):
    path = ms.jpeg(str(tmp_path / "p.jpg"), 2000, 1500, seed=9)
    a = shrink.shrink(shrink.open_source(path), "JPEG", shrink.Options(target_kb=300)).data
    b = shrink.shrink(shrink.open_source(path), "JPEG", shrink.Options(target_kb=300)).data
    assert a == b


# ------------------------------------------------------------------ huge photos
def test_a_200_megapixel_photo_opens(tmp_path):
    """Samsung 200 MP photos are over Pillow's own 179 MP stop."""
    path = str(tmp_path / "huge.png")
    Image.new("L", (16384, 12288), 90).save(path, "PNG")  # 201 MP, tiny file
    (r,) = run([path], mode=shrink.SIZE, long_edge=1920)
    assert r.status == shrink.DONE, r.error
    assert r.in_pixels == (16384, 12288) and r.out_pixels == (1920, 1440)


def test_big_photos_are_shrunk_one_at_a_time(tmp_path, monkeypatch):
    monkeypatch.setattr(shrink, "BIG_PIXELS", 100_000)
    for i in range(6):
        ms.jpeg(str(tmp_path / f"p{i}.jpg"), 900, 600, seed=i)
    inside, most = [0], [0]
    lock = threading.Lock()
    real = shrink.open_source

    def counting(src):
        with lock:
            inside[0] += 1
            most[0] = max(most[0], inside[0])
        try:
            import time

            time.sleep(0.05)
            return real(src)
        finally:
            with lock:
                inside[0] -= 1

    monkeypatch.setattr(shrink, "open_source", counting)
    results = run([tmp_path], target_kb=100)
    assert all(r.status == shrink.DONE for r in results) and most[0] == 1


def test_small_photos_run_side_by_side(tmp_path, monkeypatch):
    for i in range(6):
        ms.jpeg(str(tmp_path / f"p{i}.jpg"), 600, 400, seed=i)
    inside, most = [0], [0]
    lock = threading.Lock()
    real = shrink.open_source

    def counting(src):
        with lock:
            inside[0] += 1
            most[0] = max(most[0], inside[0])
        try:
            import time

            time.sleep(0.2)
            return real(src)
        finally:
            with lock:
                inside[0] -= 1

    monkeypatch.setattr(shrink, "open_source", counting)
    monkeypatch.setattr(shrink, "WORKERS", 4)
    items, _ = shrink.collect([str(tmp_path)])
    shrink.run_batch(shrink.plan(items, shrink.Options()), shrink.Options(), workers=4)
    assert most[0] > 1


# ------------------------------------------------------------------ odd files
def test_truncated_jpeg_fails_alone(tmp_path):
    good = ms.jpeg(str(tmp_path / "good.jpg"), 900, 600, seed=1)
    data = open(good, "rb").read()
    (tmp_path / "cut.jpg").write_bytes(data[: len(data) // 2])
    results = {os.path.basename(r.src): r for r in run([tmp_path], target_kb=100)}
    assert results["cut.jpg"].status == shrink.FAILED and results["good.jpg"].status == shrink.DONE
    assert files_under(tmp_path / "_small") == ["good.jpg"]


def test_png_named_jpg_is_read_by_content(tmp_path):
    ms.picture(800, 600, 1).save(tmp_path / "really_png.jpg", "PNG")
    (r,) = run([tmp_path / "really_png.jpg"], target_kb=100)
    assert r.status == shrink.DONE


@pytest.mark.parametrize("kind", ["apng", "webp_anim", "tiff_pages"])
def test_animations_and_pages_use_the_first_frame(tmp_path, kind):
    frames = [Image.new("RGB", (400, 300), c) for c in ((250, 10, 10), (10, 250, 10), (10, 10, 250))]
    frames = [Image.blend(f, ms.picture(400, 300, 1), 0.1) for f in frames]
    ext = {"apng": ".png", "webp_anim": ".webp", "tiff_pages": ".tif"}[kind]
    path = str(tmp_path / f"a{ext}")
    fmt = {"apng": "PNG", "webp_anim": "WEBP", "tiff_pages": "TIFF"}[kind]
    frames[0].save(path, fmt, save_all=True, append_images=frames[1:], duration=100)
    (r,) = run([path], target_kb=50)
    assert r.status == shrink.DONE
    with Image.open(r.dst) as im:
        c = colour_at(im, 0.5, 0.5)
        assert c[0] > 150 and c[1] < 100 and c[2] < 100  # the red first frame


@pytest.mark.parametrize("kind", ["float01", "float255", "int32"])
def test_float_and_32_bit_tiff(tmp_path, kind):
    grey = ms.picture(600, 400, 1).convert("L")
    if kind == "float01":
        img = grey.convert("F").point(lambda v: v / 255.0)
    elif kind == "float255":
        img = grey.convert("F")
    else:
        img = grey.convert("I").point(lambda v: v * 1000)  # values up to 255000
    path = str(tmp_path / "f.tif")
    img.save(path, "TIFF")
    (r,) = run([path], target_kb=50)
    assert r.status in (shrink.DONE, shrink.SMALL), r.error
    src = shrink.open_source(path)
    lo, hi = src.image.getextrema()
    assert src.image.mode == "L" and lo < 120 and hi > 150  # not all black, not clipped to white


def test_tiny_pictures(tmp_path):
    Image.new("RGB", (1, 1), (9, 9, 9)).save(tmp_path / "one.png")
    ms.picture(5000, 3, 1).save(tmp_path / "line.png")
    for mode in shrink.MODES:
        results = run([tmp_path], mode=mode, target_kb=10)
        assert all(r.status in (shrink.DONE, shrink.SMALL) for r in results), [r.error for r in results]


# ------------------------------------------------------------------ the file system
def test_a_file_called_small_gets_a_numbered_folder(tmp_path):
    ms.jpeg(str(tmp_path / "a.jpg"), 900, 600, seed=1)
    (tmp_path / "_small").write_text("i am a file")
    (r,) = run([tmp_path], target_kb=100)
    assert r.status == shrink.DONE and r.dst == str(tmp_path / "_small (2)" / "a.jpg")
    assert (tmp_path / "_small").read_text() == "i am a file"
    items, _ = shrink.collect([str(tmp_path)])  # the numbered folder is not read back as input
    assert [os.path.basename(i.src) for i in items] == ["a.jpg"]


def test_a_stale_part_file_is_left_alone(tmp_path):
    ms.jpeg(str(tmp_path / "a.jpg"), 900, 600, seed=1)
    os.makedirs(tmp_path / "_small")
    (tmp_path / "_small" / "a.jpg.part").write_bytes(b"from a crash")
    (r,) = run([tmp_path], target_kb=100)
    assert r.status == shrink.DONE and r.dst.endswith("a.jpg")
    assert (tmp_path / "_small" / "a.jpg.part").read_bytes() == b"from a crash"
    assert sorted(files_under(tmp_path / "_small")) == ["a.jpg", "a.jpg.part"]


def test_a_name_taken_after_planning_gets_the_next_number(tmp_path):
    ms.jpeg(str(tmp_path / "a.jpg"), 900, 600, seed=1)
    opts = shrink.Options(target_kb=100)
    items, _ = shrink.collect([str(tmp_path)])
    jobs = shrink.plan(items, opts)
    os.makedirs(os.path.dirname(jobs[0].dst))
    with open(jobs[0].dst, "wb") as f:
        f.write(b"someone else")
    (r,) = shrink.run_batch(jobs, opts)
    assert r.status == shrink.DONE and r.dst == str(tmp_path / "_small" / "a (2).jpg")
    assert open(jobs[0].dst, "rb").read() == b"someone else"


def test_a_failed_write_leaves_nothing(tmp_path, monkeypatch):
    ms.jpeg(str(tmp_path / "a.jpg"), 900, 600, seed=1)
    real_open = builtins.open

    class Broken:
        def __init__(self, f):
            self.f = f

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.f.close()
            return False

        def write(self, data):
            self.f.write(data[:100])
            raise OSError(28, "No space left on device")

    def fake_open(path, mode="r", *a, **k):
        f = real_open(path, mode, *a, **k)
        return Broken(f) if str(path).endswith(".part") else f

    monkeypatch.setattr(builtins, "open", fake_open)
    (r,) = run([tmp_path], target_kb=100)
    monkeypatch.undo()
    assert r.status == shrink.FAILED and "No space" in r.error and r.dst == ""
    assert files_under(tmp_path / "_small") == []


def test_a_failed_rename_leaves_nothing(tmp_path, monkeypatch):
    ms.jpeg(str(tmp_path / "a.jpg"), 900, 600, seed=1)
    monkeypatch.setattr(shrink.os, "rename", lambda a, b: (_ for _ in ()).throw(PermissionError("locked")))
    (r,) = run([tmp_path], target_kb=100)
    monkeypatch.undo()
    assert r.status == shrink.FAILED and files_under(tmp_path / "_small") == []


def test_paths_longer_than_260_characters(tmp_path):
    deep = tmp_path
    while len(str(deep)) < 280:
        deep = deep / ("long_folder_name_" + "x" * 20)
    src = ms.jpeg(shrink.fs(str(deep / "photo.jpg")), 900, 600, seed=1)
    src = str(deep / "photo.jpg")
    items, missing = shrink.collect([str(tmp_path)])
    assert [i.src for i in items] == [src] and not missing
    (r,) = shrink.run_batch(shrink.plan(items, shrink.Options(target_kb=100)), shrink.Options(target_kb=100))
    assert r.status == shrink.DONE, r.error
    assert len(r.dst) > 260 and os.path.exists(shrink.fs(r.dst))


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows thing")
def test_junctions_are_not_followed(tmp_path):
    outside = tmp_path / "outside"
    ms.jpeg(str(outside / "elsewhere.jpg"), 300, 200, seed=1)
    root = tmp_path / "root"
    ms.jpeg(str(root / "here.jpg"), 300, 200, seed=2)
    subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "link"), str(outside)], check=True, capture_output=True)
    items, _ = shrink.collect([str(root)])
    assert [os.path.basename(i.src) for i in items] == ["here.jpg"]


def test_unicode_names(tmp_path):
    nfd = unicodedata.normalize("NFD", "한글 사진")
    names = [f"{nfd}.jpg", "emoji 📷 photo.jpg", "日本語の写真.jpg"]
    for i, n in enumerate(names):
        ms.jpeg(str(tmp_path / n), 600, 400, seed=i)
    results = run([tmp_path], target_kb=100)
    assert all(r.status == shrink.DONE for r in results)
    assert sorted(os.path.basename(r.dst) for r in results) == sorted(names)


def test_the_same_photo_given_twice_is_shrunk_once(tmp_path):
    p = ms.jpeg(str(tmp_path / "Photo.JPG"), 600, 400, seed=1)
    items, _ = shrink.collect([p, p.lower(), p.upper(), str(tmp_path)])
    assert len(items) == 1


def test_nested_results_folders_are_never_input(tmp_path):
    ms.jpeg(str(tmp_path / "sub" / "a.jpg"), 600, 400, seed=1)
    run([tmp_path / "sub"], target_kb=100)  # sub/_small/a.jpg
    run([tmp_path], target_kb=100)  # _small/sub/a.jpg, and sub/_small is skipped
    made = files_under(tmp_path)
    assert made == ["_small/sub/a.jpg", "sub/_small/a.jpg", "sub/a.jpg"]


def test_suffix_names_in_two_folders_do_not_clash(tmp_path):
    ms.jpeg(str(tmp_path / "x" / "a.jpg"), 600, 400, seed=1)
    ms.jpeg(str(tmp_path / "y" / "a.jpg"), 600, 400, seed=2)
    results = run([tmp_path], target_kb=100, output=shrink.SUFFIX)
    assert sorted(files_under(tmp_path)) == ["x/a.jpg", "x/a_small.jpg", "y/a.jpg", "y/a_small.jpg"]
    assert all(r.status == shrink.DONE for r in results)


def test_a_big_batch(tmp_path):
    for i in range(60):
        ms.jpeg(str(tmp_path / f"d{i % 3}" / f"IMG_{i:04d}.jpg"), 400, 300, seed=i, quality=97)
    before = snapshot(tmp_path)
    results = run([tmp_path], target_kb=30)
    assert len(results) == 60 and all(r.status == shrink.DONE for r in results)
    assert len({r.dst for r in results}) == 60
    after = snapshot(tmp_path)
    assert {k: v for k, v in after.items() if k in before} == before


# ------------------------------------------------------------------ "keep PNG" decides from the pixels
def test_an_opaque_rgba_screenshot_becomes_jpg_even_with_keep_png(tmp_path):
    """Windows screenshots are RGBA PNGs with every pixel opaque (found on real pictures)."""
    shot = ms.picture(1600, 900, 3, 0.2).convert("RGBA")  # alpha 255 everywhere
    shot.save(tmp_path / "Screenshot 2026-10-16.png")
    (r,) = run([tmp_path], target_kb=300, keep_png=True)
    assert r.status == shrink.DONE and r.dst.endswith("Screenshot 2026-10-16.jpg")
    with Image.open(r.dst) as im:
        assert im.format == "JPEG"


def test_a_partly_transparent_png_stays_png(tmp_path):
    img = ms.picture(800, 600, 3, 0.2).convert("RGBA")
    ImageDraw.Draw(img).rectangle((0, 0, 99, 99), fill=(0, 0, 0, 0))  # a transparent corner
    img.save(tmp_path / "logo.png")
    (r,) = run([tmp_path], target_kb=2000, keep_png=True)
    assert r.dst.endswith("logo.png")
    with Image.open(r.dst) as im:
        assert im.format == "PNG" and im.getpixel((3, 3))[3] == 0


def test_keep_png_reserves_both_names(tmp_path):
    ms.png_transparent(str(tmp_path / "a.png"), 400, 300)
    ms.jpeg(str(tmp_path / "a.jpg"), 400, 300, seed=1)
    results = run([tmp_path], target_kb=500, keep_png=True)
    by_src = {os.path.basename(r.src): os.path.basename(r.dst) for r in results}
    # a.jpg comes first and takes a.jpg; a.png keeps a (2).jpg in reserve and, being transparent, uses a.png
    assert by_src == {"a.jpg": "a.jpg", "a.png": "a.png"}
    jobs = shrink.plan(shrink.collect([str(tmp_path)])[0], shrink.Options(keep_png=True))
    names = [os.path.basename(n) for j in jobs for n in (j.dst, j.dst_png) if n]
    assert len(names) == len(set(names)) == 3  # second run: a (2).jpg; a (3).jpg and a (2).png kept for a.png


def test_png_result_is_under_the_target_after_the_final_squeeze(tmp_path):
    path = ms.png_transparent(str(tmp_path / "t.png"), 2400, 1800)
    for kb in (300, 800, 1500):
        src = shrink.open_source(path)
        out = shrink.shrink(src, "PNG", shrink.Options(target_kb=kb))
        assert out.fits and len(out.data) <= kb * 1000
