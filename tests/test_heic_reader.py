"""HEIC is read with pi-heif, the read-only build of pillow-heif (no HEVC encoder, so the
exe carries no GPLv2 x265). These tests prove nothing is lost by the switch: the same
pixels, the same metadata, the same results as pillow-heif's decoder. pillow-heif itself
is only a test tool here (it writes the HEIC samples)."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest
from PIL import Image

import make_samples as ms
import shrink
from conftest import ROOT


def heic_samples(folder) -> dict[str, str]:
    os.makedirs(folder, exist_ok=True)
    out = {
        "rgb_gps": ms.heic(os.path.join(folder, "rgb.heic"), 1600, 1200),
        "rotated": ms.save_heic(ms.picture(1200, 800, 2), os.path.join(folder, "rot.heic"), 90,
                                ms.exif_bytes(6, True, w=1200, h=800), ms.srgb_icc()),
    }
    rgba = ms.picture(800, 600, 3).convert("RGBA")
    rgba.putalpha(Image.linear_gradient("L").resize((800, 600)))
    out["alpha"] = ms.save_heic(rgba, os.path.join(folder, "alpha.heic"), 90, ms.exif_bytes(1, False))
    try:  # a 10-bit HEIC, as recent iPhones and Android phones write
        import pillow_heif

        deep = ms.picture(640, 480, 4).convert("RGB")
        data = b"".join(bytes((0, v)) for v in deep.tobytes())  # 8-bit values as the high byte of 16-bit
        heif = pillow_heif.from_bytes(mode="RGB;16", size=deep.size, data=data)
        heif.info["exif"] = ms.exif_bytes(1, True)
        path = os.path.join(folder, "deep.heic")
        heif.save(path, quality=90)
        out["10bit"] = path
    except Exception:
        pass
    return out


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    return heic_samples(str(tmp_path_factory.mktemp("heic")))


def test_the_program_reads_heic_with_pi_heif(samples):
    shrink.register_heif()
    factory = Image.OPEN["HEIF"][0]
    assert factory.__module__.startswith("pi_heif")
    with Image.open(samples["rgb_gps"]) as im:
        assert type(im).__module__.startswith("pi_heif")


def test_pillow_heif_registered_first_does_not_take_over(samples):
    import pillow_heif

    pillow_heif.register_heif_opener()  # as if another library had done it
    assert Image.OPEN["HEIF"][0].__module__.startswith("pillow_heif")
    src = shrink.open_source(samples["rgb_gps"])  # the program re-registers its own reader
    assert Image.OPEN["HEIF"][0].__module__.startswith("pi_heif") and src.pixels == (1600, 1200)


@pytest.mark.parametrize("name", ["rgb_gps", "rotated", "alpha", "10bit"])
def test_same_pixels_and_metadata_as_pillow_heif(samples, name):
    if name not in samples:
        pytest.skip("this pillow-heif cannot write a 10-bit HEIC")
    import pi_heif
    import pillow_heif

    a = pi_heif.open_heif(samples[name], convert_hdr_to_8bit=False)
    b = pillow_heif.open_heif(samples[name], convert_hdr_to_8bit=False)
    assert (a.size, a.mode) == (b.size, b.mode)
    assert bytes(a.data) == bytes(b.data)  # decoded pixels, bit for bit
    assert a.info.get("exif") == b.info.get("exif")
    assert a.info.get("icc_profile") == b.info.get("icc_profile")


@pytest.mark.parametrize("name", ["rgb_gps", "rotated", "alpha", "10bit"])
def test_same_results_as_with_pillow_heif(samples, name, monkeypatch):
    """The whole pipeline (rotation, GPS removal, target search) gives the same bytes."""
    if name not in samples:
        pytest.skip("this pillow-heif cannot write a 10-bit HEIC")
    import pillow_heif

    opts = shrink.Options(target_kb=150)
    with_pi = shrink.shrink(shrink.open_source(samples[name]), "JPEG", opts)
    pi_src = shrink.open_source(samples[name])

    monkeypatch.setattr(shrink, "register_heif", lambda: True)  # keep pillow-heif's reader for this read
    pillow_heif.register_heif_opener()
    try:
        with Image.open(samples[name]) as im:
            assert type(im).__module__.startswith("pillow_heif")
        ph_src = shrink.open_source(samples[name])
        with_ph = shrink.shrink(ph_src, "JPEG", opts)
    finally:
        monkeypatch.undo()
        shrink.register_heif()
    assert (pi_src.pixels, pi_src.had_gps, pi_src.transparent) == (ph_src.pixels, ph_src.had_gps, ph_src.transparent)
    assert pi_src.exif == ph_src.exif and pi_src.icc == ph_src.icc
    assert with_pi.data == with_ph.data and with_pi.fits


def test_the_program_never_loads_pillow_heif(tmp_path):
    """What the exe will contain: run the program's own modules in a clean process."""
    path = ms.heic(str(tmp_path / "a.heic"), 800, 600)
    code = (f"import sys; sys.path.insert(0, {ROOT!r})\n"
            "import main, gui, shrink, prefs, update_check\n"
            f"items, _ = shrink.collect([{str(tmp_path)!r}])\n"
            "(r,) = shrink.run_batch(shrink.plan(items, shrink.Options(target_kb=100)), shrink.Options(target_kb=100))\n"
            "print(r.status, r.gps_removed, 'pillow_heif' in sys.modules, 'pi_heif' in sys.modules)\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                         env=dict(os.environ, PHOTO_RESIZE_SETTINGS=str(tmp_path / "s.json")))
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.split() == ["done", "True", "False", "True"]
    assert os.path.exists(tmp_path / "_small" / "a.jpg")


def test_requirements_name_pi_heif_for_the_program():
    req = open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read().lower()
    assert "pi-heif" in req and "pillow-heif" not in req
    bat = open(os.path.join(ROOT, "build.bat"), encoding="utf-8").read()
    assert "--collect-all pi_heif" in bat and "--exclude-module pillow_heif" in bat


def test_the_lgpl_and_gpl_texts_ship_with_the_program():
    """LGPL-3.0 section 4: the combined work comes with the GPL and LGPL texts."""
    folder = os.path.join(ROOT, "licenses")
    lgpl = open(os.path.join(folder, "LGPL-3.0.txt"), encoding="utf-8").read()
    gpl = open(os.path.join(folder, "GPL-3.0.txt"), encoding="utf-8").read()
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in lgpl and "Version 3, 29 June 2007" in lgpl
    assert "GNU GENERAL PUBLIC LICENSE" in gpl and "Version 3, 29 June 2007" in gpl
    bat = open(os.path.join(ROOT, "build.bat"), encoding="utf-8").read()
    assert '--add-data "licenses;licenses"' in bat
