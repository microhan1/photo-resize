"""The engine: target sizes, the quality floor, originals untouched, rotation, location
removed, dates kept, transparent PNG, HEIC, "not bigger than the original", folder
structure and name collisions. Every picture is generated (samples/make_samples.py)."""
from __future__ import annotations

import io
import os
import stat
import threading

import piexif
import pytest
from PIL import Image, ImageCms

import make_samples as ms
import shrink
from conftest import files_under, sha1, snapshot


def run(paths, recursive=True, **kw):
    opts = shrink.Options(**kw)
    items, missing = shrink.collect([str(p) for p in paths], recursive)
    return shrink.run_batch(shrink.plan(items, opts), opts)


def exif_of(path) -> dict:
    with Image.open(path) as im:
        raw = im.info.get("exif")
    return piexif.load(raw) if raw else {}


@pytest.fixture(scope="module")
def big_jpeg(tmp_path_factory):
    """A 12-megapixel camera-like photo, well over 2 MB, with date, GPS and a profile."""
    folder = tmp_path_factory.mktemp("big")
    path = ms.jpeg(str(folder / "big.jpg"), 4000, 3000, seed=11, detail=0.4)
    assert os.path.getsize(path) > 2_500_000
    return path


def copy(src, folder, name="photo.jpg"):
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(str(folder), name)
    with open(src, "rb") as a, open(dst, "wb") as b:
        b.write(a.read())
    st = os.stat(src)
    os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns))
    return dst


# ------------------------------------------------------------------ target size
@pytest.mark.parametrize("kb", [200, 500, 1000, 2000, 300])
def test_result_is_under_the_target(tmp_path, big_jpeg, kb):
    src = copy(big_jpeg, tmp_path)
    (r,) = run([src], target_kb=kb)
    assert r.status == shrink.DONE
    assert os.path.getsize(r.dst) == r.out_size <= kb * 1000  # 1 KB = 1000 bytes: fits either way of counting
    assert shrink.MIN_QUALITY <= r.quality <= shrink.MAX_QUALITY
    with Image.open(r.dst) as im:
        assert im.format == "JPEG" and im.size == r.out_pixels


def test_the_highest_quality_that_fits_is_chosen(tmp_path, big_jpeg):
    """One quality step up at the same size would not fit (unless it is already 95)."""
    src = copy(big_jpeg, tmp_path)
    (r,) = run([src], target_kb=500)
    s = shrink.open_source(src)
    im = shrink._resized(s.image, max(r.out_pixels))
    assert im.size == r.out_pixels
    assert len(shrink.encode(im, "JPEG", r.quality, s.exif, s.icc)) == r.out_size
    if r.quality < shrink.MAX_QUALITY:
        assert len(shrink.encode(im, "JPEG", r.quality + 1, s.exif, s.icc)) > 500_000


def test_quality_goes_down_first_and_size_only_below_60(tmp_path, big_jpeg):
    """Full size is kept while quality 60 fits; the size shrinks only when it does not."""
    src = copy(big_jpeg, tmp_path)
    s = shrink.open_source(src)
    at70 = len(shrink.encode(s.image, "JPEG", 70, s.exif, s.icc))
    (r,) = run([src], target_kb=at70 // 1000 + 1)
    assert r.out_pixels == r.in_pixels and r.quality >= 70
    at60 = len(shrink.encode(s.image, "JPEG", 60, s.exif, s.icc))
    (r2,) = run([src], target_kb=at60 // 1000 - 50)
    assert r2.status == shrink.DONE and max(r2.out_pixels) < max(r2.in_pixels)
    assert r2.quality >= shrink.MIN_QUALITY


def test_unreachable_target_is_over_and_keeps_the_smallest(tmp_path, big_jpeg, monkeypatch):
    monkeypatch.setattr(shrink, "MIN_EDGE", 2000)  # give up early
    src = copy(big_jpeg, tmp_path)
    (r,) = run([src], target_kb=50)
    assert r.status == shrink.OVER
    assert r.dst and os.path.getsize(r.dst) == r.out_size > 50_000
    assert r.out_size < r.in_size and r.quality == shrink.MIN_QUALITY
    assert max(r.out_pixels) == 2000


def test_time_limit_ends_the_search(tmp_path, big_jpeg, monkeypatch):
    monkeypatch.setattr(shrink, "TIME_LIMIT", 0.0)
    src = copy(big_jpeg, tmp_path)
    (r,) = run([src], target_kb=20)
    assert r.status == shrink.OVER and r.out_pixels == r.in_pixels  # stopped after the first try


def test_a_photo_already_under_the_target_still_loses_its_location(tmp_path):
    src = ms.jpeg(str(tmp_path / "a.jpg"), 1200, 900, seed=2, quality=92)
    assert os.path.getsize(src) < 2_000_000
    (r,) = run([src], target_kb=2000)
    assert r.status == shrink.DONE and r.out_size < r.in_size
    assert exif_of(r.dst)["GPS"] == {} and r.gps_removed


# ------------------------------------------------------------------ size and quality modes
def test_size_mode_shrinks_the_long_edge(tmp_path, big_jpeg):
    src = copy(big_jpeg, tmp_path)
    (r,) = run([src], mode=shrink.SIZE, long_edge=1920)
    assert r.out_pixels == (1920, 1440) and r.quality == shrink.SIZE_QUALITY


def test_size_mode_never_enlarges(tmp_path):
    src = ms.jpeg(str(tmp_path / "s.jpg"), 800, 600, seed=3, quality=98)
    (r,) = run([src], mode=shrink.SIZE, long_edge=1920)
    assert r.out_pixels == (800, 600)


@pytest.mark.parametrize("level", ["high", "medium", "low"])
def test_quality_mode_keeps_the_pixels(tmp_path, level):
    src = ms.jpeg(str(tmp_path / "q.jpg"), 1600, 1200, seed=4, quality=97)
    (r,) = run([src], mode=shrink.QUALITY, quality=shrink.QUALITY_LEVELS[level])
    assert r.status == shrink.DONE and r.out_pixels == (1600, 1200)
    assert r.quality == shrink.QUALITY_LEVELS[level]


def test_bigger_than_the_original_is_not_made(tmp_path):
    src = ms.small_jpeg(str(tmp_path / "tiny.jpg"))  # saved at quality 40
    before = snapshot(tmp_path)
    (r,) = run([src], mode=shrink.SIZE)  # quality 85 would be bigger
    assert r.status == shrink.SMALL and r.dst == "" and r.out_size >= r.in_size
    assert snapshot(tmp_path) == before  # not even an empty _small folder


# ------------------------------------------------------------------ originals and names
@pytest.mark.parametrize("mode", shrink.MODES)
def test_originals_are_never_changed(tmp_path, mode):
    folder = tmp_path / "in"
    ms.make_all(str(folder))
    before = snapshot(folder)
    run([folder], mode=mode)
    after = snapshot(folder)
    assert {k: v for k, v in after.items() if k in before} == before
    assert all(k.startswith("_small" + os.sep) for k in set(after) - set(before))


def test_read_only_original_stays_read_only(tmp_path):
    src = ms.jpeg(str(tmp_path / "ro.jpg"), 1200, 900, seed=5)
    os.chmod(src, stat.S_IREAD)
    try:
        digest = sha1(src)
        (r,) = run([src], target_kb=200)
        assert r.status == shrink.DONE
        assert sha1(src) == digest and not os.access(src, os.W_OK)
    finally:
        os.chmod(src, stat.S_IREAD | stat.S_IWRITE)


def test_folder_structure_is_kept(tmp_path):
    folder = tmp_path / "trip"
    ms.jpeg(str(folder / "day1" / "a.jpg"), 900, 600, seed=1)
    ms.jpeg(str(folder / "day1" / "night" / "b.jpg"), 900, 600, seed=2)
    ms.jpeg(str(folder / "c.jpg"), 900, 600, seed=3)
    run([folder], target_kb=200)
    made = [f for f in files_under(folder) if f.startswith("_small/")]
    assert made == ["_small/c.jpg", "_small/day1/a.jpg", "_small/day1/night/b.jpg"]


def test_without_subfolders(tmp_path):
    folder = tmp_path / "f"
    ms.jpeg(str(folder / "top.jpg"), 900, 600, seed=1)
    ms.jpeg(str(folder / "sub" / "deep.jpg"), 900, 600, seed=2)
    items, _ = shrink.collect([str(folder)], recursive=False)
    assert [os.path.basename(i.src) for i in items] == ["top.jpg"]


def test_suffix_output_sits_next_to_the_original(tmp_path):
    src = ms.jpeg(str(tmp_path / "IMG_1.jpg"), 900, 600, seed=1)
    (r,) = run([src], target_kb=200, output=shrink.SUFFIX)
    assert r.dst == str(tmp_path / "IMG_1_small.jpg")


def test_an_existing_name_gets_a_number_and_is_not_touched(tmp_path):
    src = ms.jpeg(str(tmp_path / "a.jpg"), 900, 600, seed=1)
    os.makedirs(tmp_path / "_small")
    (tmp_path / "_small" / "a.jpg").write_bytes(b"keep me")
    os.makedirs(tmp_path / "_small" / "a (2).jpg")  # a folder holding the next name
    (r,) = run([src], target_kb=200)
    assert r.dst == str(tmp_path / "_small" / "a (3).jpg")
    assert (tmp_path / "_small" / "a.jpg").read_bytes() == b"keep me"


def test_two_photos_never_get_one_name(tmp_path):
    ms.jpeg(str(tmp_path / "a.jpg"), 900, 600, seed=1)
    ms.png_opaque(str(tmp_path / "a.png"), 900, 600)
    results = run([tmp_path], target_kb=200)
    names = sorted(os.path.basename(r.dst) for r in results)
    assert names == ["a (2).jpg", "a.jpg"]


def test_running_again_leaves_results_alone(tmp_path):
    folder = tmp_path / "f"
    ms.jpeg(str(folder / "a.jpg"), 900, 600, seed=1)
    run([folder], target_kb=200)
    first = snapshot(folder)
    results = run([folder], target_kb=200)  # _small is not read as input
    assert [os.path.basename(r.src) for r in results] == ["a.jpg"]
    assert results[0].dst.endswith("a (2).jpg")
    after = snapshot(folder)
    assert {k: v for k, v in after.items() if k in first} == first


def test_suffix_results_are_not_shrunk_again(tmp_path):
    ms.jpeg(str(tmp_path / "a.jpg"), 900, 600, seed=1)
    run([tmp_path], target_kb=200, output=shrink.SUFFIX)
    items, _ = shrink.collect([str(tmp_path)])
    assert [os.path.basename(i.src) for i in items] == ["a.jpg"]


def test_names_with_korean_symbols_and_upper_case(tmp_path):
    src = ms.jpeg(str(tmp_path / "여행 사진 #1 & 50%.JPG"), 900, 600, seed=1)
    (r,) = run([src], target_kb=200)
    assert r.status == shrink.DONE and os.path.basename(r.dst) == "여행 사진 #1 & 50%.jpg"


# ------------------------------------------------------------------ metadata
def test_rotation_is_applied_to_the_pixels(tmp_path):
    src = ms.rotated_jpeg(str(tmp_path / "r.jpg"))  # stored 1200x800, Orientation 6
    (r,) = run([src], target_kb=200)
    with Image.open(r.dst) as im:
        assert im.size == (800, 1200)
        red = im.convert("RGB").getpixel((im.width - 10, 10))
        assert red[0] > 180 and red[1] < 90 and red[2] < 90  # the red corner is top-right when upright
    assert exif_of(r.dst)["0th"][piexif.ImageIFD.Orientation] == 1


def test_location_is_removed_from_exif_and_xmp(tmp_path):
    src = ms.jpeg(str(tmp_path / "g.jpg"), 1200, 900, seed=6, xmp=True)
    assert exif_of(src)["GPS"]
    (r,) = run([src], target_kb=200)
    ex = exif_of(r.dst)
    assert ex["GPS"] == {} and piexif.ImageIFD.GPSTag not in ex["0th"]
    with Image.open(r.dst) as im:
        assert 0x8825 not in im.getexif() and "xmp" not in im.info
    data = open(r.dst, "rb").read()
    assert b"GPSLatitude" not in data and b"xmpmeta" not in data
    assert r.gps_removed and shrink.summarize([r]).gps == 1


def test_a_photo_without_location_is_not_counted(tmp_path):
    src = ms.jpeg(str(tmp_path / "n.jpg"), 1200, 900, seed=6, gps=False)
    (r,) = run([src], target_kb=200)
    assert r.status == shrink.DONE and not r.gps_removed and shrink.summarize([r]).gps == 0


def test_date_camera_and_profile_are_kept(tmp_path):
    src = ms.jpeg(str(tmp_path / "d.jpg"), 1200, 900, seed=7)
    (r,) = run([src], target_kb=200)
    ex = exif_of(r.dst)
    assert ex["Exif"][piexif.ExifIFD.DateTimeOriginal] == ms.DATE
    assert ex["0th"][piexif.ImageIFD.Make] == b"SampleCam"
    assert ex["Exif"][piexif.ExifIFD.PixelXDimension] == r.out_pixels[0]
    with Image.open(r.dst) as im:
        icc = im.info.get("icc_profile")
    assert icc and ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc))).strip()


def test_modified_time_is_the_originals(tmp_path):
    src = ms.jpeg(str(tmp_path / "m.jpg"), 900, 600, seed=8)
    os.utime(src, (1_600_000_000, 1_600_000_000))
    (r,) = run([src], target_kb=200)
    assert os.stat(r.dst).st_mtime == os.stat(src).st_mtime == 1_600_000_000


def test_odd_exif_never_stops_a_photo(tmp_path):
    img = ms.picture(900, 600, 1)
    img.save(tmp_path / "x.jpg", "JPEG", quality=95, exif=b"Exif\x00\x00garbage-not-tiff")
    (r,) = run([tmp_path / "x.jpg"], target_kb=100)
    assert r.status == shrink.DONE


# ------------------------------------------------------------------ formats
def test_transparent_png_becomes_jpg_on_white(tmp_path):
    src = ms.png_transparent(str(tmp_path / "logo.png"), 800, 600)
    (r,) = run([src], target_kb=200)
    assert r.dst.endswith("logo.jpg")
    with Image.open(r.dst) as im:
        assert im.format == "JPEG"
        assert all(c > 245 for c in im.convert("RGB").getpixel((3, 3)))  # outside the ellipse: white


def test_keep_png_keeps_transparency(tmp_path):
    src = ms.png_transparent(str(tmp_path / "logo.png"), 1600, 1200)
    (r,) = run([src], target_kb=2000, keep_png=True)
    assert r.dst.endswith("logo.png") and r.status in (shrink.DONE, shrink.OVER)
    with Image.open(r.dst) as im:
        assert im.format == "PNG" and im.mode == "RGBA" and im.getpixel((3, 3))[3] == 0


def test_keep_png_does_not_apply_to_opaque_png(tmp_path):
    src = ms.png_opaque(str(tmp_path / "shot.png"), 900, 600)
    (r,) = run([src], target_kb=200, keep_png=True)
    assert r.dst.endswith("shot.jpg")


def test_heic_is_read(tmp_path):
    src = ms.heic(str(tmp_path / "IMG_1001.heic"), 2000, 1500)
    (r,) = run([src], target_kb=300)
    assert r.status == shrink.DONE and r.dst.endswith("IMG_1001.jpg") and r.out_size <= 300_000
    ex = exif_of(r.dst)
    assert ex["GPS"] == {} and ex["Exif"][piexif.ExifIFD.DateTimeOriginal] == ms.DATE and r.gps_removed


@pytest.mark.parametrize("fmt,ext", [("WEBP", ".webp"), ("BMP", ".bmp"), ("TIFF", ".tif"), ("PNG", ".png")])
def test_other_formats(tmp_path, fmt, ext):
    path = str(tmp_path / f"p{ext}")
    ms.picture(1200, 900, 2).save(path, fmt)
    (r,) = run([path], target_kb=200)
    assert r.status == shrink.DONE and r.dst.endswith(".jpg")


@pytest.mark.parametrize("mode", ["L", "CMYK", "I;16", "P", "LA", "1"])
def test_unusual_pixel_modes(tmp_path, mode):
    base = ms.picture(800, 600, 3)
    if mode == "I;16":
        img = base.convert("L").point(lambda v: v).convert("I").point(lambda v: v * 257).convert("I;16")
        path = str(tmp_path / "deep.png")
    elif mode == "P":
        img = base.convert("P", palette=Image.Palette.ADAPTIVE)
        img.info["transparency"] = 0
        path = str(tmp_path / "pal.png")
    elif mode == "LA":
        img = base.convert("LA")
        path = str(tmp_path / "la.png")
    elif mode == "1":
        img = base.convert("1")
        path = str(tmp_path / "bw.png")
    else:
        img = base.convert(mode)
        path = str(tmp_path / f"{mode}.jpg")
    img.save(path)
    (r,) = run([path], target_kb=100)
    assert r.status in (shrink.DONE, shrink.SMALL), r.error
    if r.dst:
        with Image.open(r.dst) as im:
            assert im.mode in ("RGB", "L")
            if mode == "I;16":
                assert 60 < sum(im.getextrema()) / 2 < 200  # not clipped to white


# ------------------------------------------------------------------ batches
def test_a_broken_file_fails_alone(tmp_path):
    (tmp_path / "broken.jpg").write_bytes(b"this is not a photo")
    (tmp_path / "empty.png").write_bytes(b"")
    ms.jpeg(str(tmp_path / "good.jpg"), 900, 600, seed=1)
    results = {os.path.basename(r.src): r for r in run([tmp_path], target_kb=200)}
    assert results["broken.jpg"].status == shrink.FAILED and results["broken.jpg"].error
    assert results["empty.png"].status == shrink.FAILED
    assert results["good.jpg"].status == shrink.DONE
    assert files_under(tmp_path / "_small") == ["good.jpg"]


def test_cancel_before_start_writes_nothing(tmp_path):
    ms.make_all(str(tmp_path))
    items, _ = shrink.collect([str(tmp_path)])
    cancel = threading.Event()
    cancel.set()
    results = shrink.run_batch(shrink.plan(items, shrink.Options()), shrink.Options(), cancel)
    assert {r.status for r in results} == {shrink.CANCELLED}
    assert not (tmp_path / "_small").exists()


def test_cancel_midway_leaves_only_whole_results(tmp_path):
    for i in range(8):
        ms.jpeg(str(tmp_path / f"p{i}.jpg"), 1600, 1200, seed=i)
    items, _ = shrink.collect([str(tmp_path)])
    cancel = threading.Event()
    results = shrink.run_batch(shrink.plan(items, shrink.Options()), shrink.Options(), cancel,
                               on_result=lambda i, r: cancel.set(), workers=2)
    written = [r for r in results if r.dst]
    assert any(r.status == shrink.CANCELLED for r in results)
    made = files_under(tmp_path / "_small") if (tmp_path / "_small").exists() else []
    assert not any(f.endswith(".part") for f in made)
    assert sorted(made) == sorted(os.path.basename(r.dst) for r in written)
    for r in written:
        with Image.open(r.dst) as im:
            im.load()


def test_collect_reports_missing_and_skips_duplicates(tmp_path):
    a = ms.jpeg(str(tmp_path / "a.jpg"), 300, 200, seed=1)
    (tmp_path / "notes.txt").write_text("x")
    items, missing = shrink.collect([a, str(tmp_path), str(tmp_path / "nope.jpg")])
    assert [i.src for i in items] == [a]
    assert missing == [str(tmp_path / "nope.jpg")]


def test_estimate_writes_nothing(tmp_path):
    ms.make_all(str(tmp_path))
    before = snapshot(tmp_path)
    items, _ = shrink.collect([str(tmp_path)])
    measured, guessed = shrink.estimate(items, shrink.Options(target_kb=500))
    assert sorted(measured) == shrink.sample_indices(items, 3)
    assert sorted(set(measured) | set(guessed)) == list(range(len(items))) and not set(measured) & set(guessed)
    assert all(g <= 500_000 for g in guessed.values())
    assert snapshot(tmp_path) == before


def test_samples_cover_every_file_type_and_spread_over_sizes(tmp_path):
    ms.make_all(str(tmp_path))  # jpg, png and heic
    for i in range(6):
        ms.jpeg(str(tmp_path / "cam" / f"C{i}.jpg"), 300 + 300 * i, 200 + 200 * i, seed=i)
    items, _ = shrink.collect([str(tmp_path)])
    picked = shrink.sample_indices(items, 3)
    assert {shrink._kind(items[i]) for i in picked} == {".jpg", ".png", ".heic"}
    picked6 = shrink.sample_indices(items, 6)
    jpg_sizes = sorted(items[i].size for i in picked6 if shrink._kind(items[i]) == ".jpg")
    all_jpg = sorted(it.size for it in items if shrink._kind(it) == ".jpg")
    assert jpg_sizes[0] == all_jpg[0] and jpg_sizes[-1] == all_jpg[-1]  # the smallest and the biggest
    assert shrink.sample_indices(items, 100) == list(range(len(items)))
    assert shrink.sample_indices([], 3) == []


def test_the_estimate_gets_exact_and_writes_nothing(tmp_path):
    ms.make_all(str(tmp_path))
    for i in range(10):
        ms.jpeg(str(tmp_path / "more" / f"M{i}.jpg"), 1200, 900, seed=40 + i)
    before = snapshot(tmp_path)
    items, _ = shrink.collect([str(tmp_path)])
    opts = shrink.Options(target_kb=200)
    snaps = list(shrink.estimate_iter(items, opts, first=6, every=0.0))
    assert len(snaps[0][0]) <= 3 and len(snaps) >= 3
    last_measured, last_guessed = snaps[-1]
    assert sorted(last_measured) == list(range(len(items))) and last_guessed == {}
    real = shrink.run_batch(shrink.plan(items, opts), opts)  # the exact estimate is what the run makes
    assert sum(shrink.expected_size(r) for r in last_measured.values()) == sum(shrink.expected_size(r) for r in real)
    after = snapshot(tmp_path)
    assert {k: v for k, v in after.items() if k in before} == before


def test_the_estimate_stops_when_cancelled(tmp_path):
    for i in range(20):
        ms.jpeg(str(tmp_path / f"p{i}.jpg"), 900, 600, seed=i)
    items, _ = shrink.collect([str(tmp_path)])
    cancel = threading.Event()
    gen = shrink.estimate_iter(items, shrink.Options(), cancel, first=3)
    first_measured, _ = next(gen)
    cancel.set()
    with pytest.raises(shrink.Cancelled):
        for _ in gen:
            pass
    assert len(first_measured) == 3


def test_the_estimate_measures_at_most_its_limit(tmp_path):
    for i in range(12):
        ms.jpeg(str(tmp_path / f"p{i}.jpg"), 300, 200, seed=i)
    items, _ = shrink.collect([str(tmp_path)])
    *_, (measured, guessed) = shrink.estimate_iter(items, shrink.Options(), first=4, limit=7)
    assert len(measured) == 7 and len(guessed) == 5


def test_summary_counts():
    rs = [shrink.Result("a", "a2", shrink.DONE, 1000, 300, gps_removed=True),
          shrink.Result("b", "b2", shrink.OVER, 1000, 600),
          shrink.Result("c", "", shrink.SMALL, 50, 60),
          shrink.Result("d", "", shrink.FAILED)]
    s = shrink.summarize(rs)
    assert (s.count, s.before, s.after, s.over, s.small, s.failed, s.gps) == (2, 2000, 900, 1, 1, 1, 1)
    assert s.percent == 55


# ------------------------------------------------------------------ small helpers
@pytest.mark.parametrize("text,kb", [("500KB", 500), ("1MB", 1000), ("1.5 mb", 1500), ("300", 300), ("2m", 2000),
                                     ("0", None), ("abc", None), ("", None), ("-5", None)])
def test_parse_size(text, kb):
    assert shrink.parse_size(text) == kb


def test_format_target_and_bytes():
    assert [shrink.format_target(k) for k in shrink.TARGET_PRESETS_KB] == ["200KB", "500KB", "1MB", "2MB"]
    assert shrink.format_target(1500) == "1.5MB" and shrink.format_target(333) == "333KB"
    assert shrink.format_bytes(500) == "500 B" and shrink.format_bytes(2048) == "2 KB"
    assert shrink.format_bytes(3 * 1024 * 1024) == "3.0 MB"


def test_options_are_clamped():
    o = shrink.Options(mode="zip", target_kb=5, long_edge=10**9, quality=10, output="cloud", keep_png=1).validated()
    assert (o.mode, o.target_kb, o.long_edge, o.quality, o.output, o.keep_png) == \
        (shrink.TARGET, shrink.TARGET_MIN_KB, shrink.SIZE_MAX, shrink.MIN_QUALITY, shrink.FOLDER, True)
    assert shrink.Options(target_kb="x").validated().target_kb == shrink.DEFAULT_TARGET_KB
