"""More of the window, the command line and settings: drops with odd paths, quick option
changes, broken photos in the preview, zoom and drag, runs that fail, a third language
added as a file, settings that cannot be saved, a frozen exe given files, a big list."""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import types

import pytest

import gui
import i18n
import main
import make_samples as ms
import prefs as prefs_mod
import shrink
import update_check
from conftest import ROOT, files_under
from test_gui import folder, make_app, pump, root, wait_estimate, wait_run  # noqa: F401  (fixtures)


# ------------------------------------------------------------------ adding photos
def test_drop_with_spaces_braces_and_korean(root, make_app, tmp_path):
    a = ms.jpeg(str(tmp_path / "새 폴더 (2)" / "여행 사진 1.jpg"), 600, 400, seed=1)
    b = ms.jpeg(str(tmp_path / "plain" / "b.jpg"), 600, 400, seed=2)
    app = make_app()
    data = root.tk.call("list", a.replace("\\", "/"), os.path.dirname(b).replace("\\", "/"))
    app._on_drop(types.SimpleNamespace(data=data))
    assert sorted(os.path.basename(i.src) for i in app.items) == ["b.jpg", "여행 사진 1.jpg"]


def test_adding_the_same_folder_twice_adds_nothing(root, make_app, folder):
    app = make_app([str(folder)])
    assert app.add_paths([str(folder)]) == 0 and len(app.items) == 7
    assert app.status[0] == "msg_no_photos"


def test_a_missing_path_is_reported(root, make_app, tmp_path):
    app = make_app()
    app.add_paths([str(tmp_path / "gone.jpg")])
    assert app.status[0] == "err_missing" and not app.items


def test_delete_key_removes_the_selected_rows(root, make_app, folder):
    app = make_app([str(folder)])
    app.tree.selection_set(("0", "1"))
    app.remove_selected()
    assert len(app.items) == 5 and len(app.tree.get_children()) == 5


def test_clear_while_estimating(root, make_app, folder):
    app = make_app([str(folder)])
    app.clear()
    pump(root, timeout=2)
    assert not app.items and not app.measured and app.info_text().endswith(i18n.t("info_empty"))


def test_closing_while_estimating_waits_for_it(root, make_app, tmp_path):
    for i in range(4):
        ms.jpeg(str(tmp_path / f"p{i}.jpg"), 3000, 2000, seed=i)
    app = make_app([str(tmp_path)])
    assert pump(root, lambda: any(th.name == "estimate" and th.is_alive() for th in app.threads), timeout=5)
    app.on_close()
    assert pump(root, lambda: app.closed, timeout=60)
    assert not any(th.is_alive() for th in app.threads)
    assert not (tmp_path / "_small").exists()


# ------------------------------------------------------------------ options
def test_quick_option_changes_end_with_the_last_estimate(root, make_app, folder):
    app = make_app([str(folder)])
    for mode in (shrink.SIZE, shrink.QUALITY, shrink.TARGET, shrink.SIZE):
        app.mode_chips.pick(mode)
        pump(root, timeout=0.05)
    app.option_chips.pick("800")
    wait_estimate(root, app)
    pump(root, timeout=1)
    first = next(iter(app.measured.values()))
    assert app.prefs.mode == shrink.SIZE and app.prefs.long_edge == 800
    assert max(first.out_pixels) <= 800  # measured with the last options, not an older request


def test_the_estimate_ends_exact(root, make_app, folder):
    app = make_app([str(folder)])
    assert pump(root, lambda: len(app.measured) == len(app.items), timeout=90)
    pump(root, timeout=0.2)
    assert app.lbl_detail.cget("text") == i18n.t("info_estimate_exact")
    assert "about" not in app.lbl_big.cget("text") and not app.guessed
    assert all(app.tree.set(str(i), "status") for i in range(len(app.items)))


def test_a_custom_target_is_restored(root, make_app):
    app = make_app(prefs=prefs_mod.Prefs(target_kb=333))
    assert app.v_target.get() == gui.CUSTOM and app.custom_row.winfo_manager() == "pack"
    assert app.v_custom.get() == "333"


def test_run_twice_numbers_the_second_results(root, make_app, folder):
    app = make_app([str(folder)])
    app.run()
    wait_run(root, app)
    app.run()
    wait_run(root, app)
    made = files_under(folder / "_small")
    assert "IMG_0001.jpg" in made and "IMG_0001 (2).jpg" in made


def test_a_run_where_everything_fails(root, make_app, tmp_path):
    (tmp_path / "x.jpg").write_bytes(b"not a photo")
    (tmp_path / "y.png").write_bytes(b"")
    app = make_app([str(tmp_path)])
    app.run()
    wait_run(root, app)
    s = app.summary
    assert (s.count, s.failed, s.percent) == (0, 2, 0)
    assert "failed 2" in app.info_text() and str(app.btn_open.cget("state")) == "disabled"
    assert all(app.tree.set(i, "status").startswith(gui.CROSS) for i in ("0", "1"))


def test_open_results_selects_the_first_result(root, make_app, folder, monkeypatch):
    opened = []
    monkeypatch.setattr(gui, "open_path", lambda p, select=False: opened.append((p, select)))
    app = make_app([str(folder)])
    app.run()
    wait_run(root, app)
    app.open_results()
    assert opened and opened[0][1] is True and os.path.exists(opened[0][0])


def test_controls_are_locked_while_running(root, make_app, tmp_path):
    for i in range(8):
        ms.jpeg(str(tmp_path / f"p{i}.jpg"), 2000, 1500, seed=i)
    app = make_app([str(tmp_path)])
    app.run()
    assert str(app.btn_run.cget("state")) == "disabled" and str(app.cb_lang.cget("state")) == "disabled"
    assert not app.mode_chips.enabled and not app.option_chips.enabled
    app.mode_chips.pick(shrink.SIZE)  # a click on a locked chip does nothing
    assert app.prefs.mode == shrink.TARGET
    assert app.add_paths([str(tmp_path)]) == 0
    wait_run(root, app)
    assert app.mode_chips.enabled and str(app.btn_run.cget("state")) == "normal"


# ------------------------------------------------------------------ preview
def test_preview_of_a_broken_photo_says_so(root, make_app, tmp_path):
    (tmp_path / "bad.jpg").write_bytes(b"nope")
    app = make_app([str(tmp_path)])
    app.tree.selection_set("0")
    app._on_select()
    assert pump(root, lambda: isinstance(app.preview, str), timeout=20)
    pump(root, timeout=0.3)
    texts = [app.cv_res.itemcget(i, "text") for i in app.cv_res.find_all() if app.cv_res.type(i) == "text"]
    assert texts and texts[0].startswith(i18n.t("st_failed", error="")[:6])


def test_zoom_and_drag_stay_inside_the_picture(root, make_app, folder):
    app = make_app([str(folder)])
    app.tree.selection_set("0")
    app._on_select()
    assert pump(root, lambda: isinstance(app.preview, tuple), timeout=30)
    app.zoom_chips.pick("4.0")
    ev = types.SimpleNamespace
    app._drag_start(ev(x=100, y=100))
    app._drag_move(ev(x=-5000, y=-5000))  # far past the edge
    assert 0.0 <= app.center[0] <= 1.0 and 0.0 <= app.center[1] <= 1.0
    assert app.center[0] > 0.5  # moved right
    a, b = app._photos
    assert (a.width(), a.height()) == (b.width(), b.height())
    app._on_wheel(ev(delta=-120))
    assert app.zoom == 2.0 and app.v_zoom.get() == "2.0"


def test_preview_of_an_already_small_photo(root, make_app, tmp_path):
    ms.small_jpeg(str(tmp_path / "tiny.jpg"))
    app = make_app([str(tmp_path)], prefs=prefs_mod.Prefs(mode=shrink.SIZE))
    app.tree.selection_set("0")
    app._on_select()
    assert pump(root, lambda: isinstance(app.preview, tuple), timeout=20)
    assert app.preview[2]["small"] and "not smaller" in app.lbl_res.cget("text")


# ------------------------------------------------------------------ languages
def test_a_third_language_is_just_a_file(root, make_app, tmp_path, monkeypatch):
    res = tmp_path / "res"
    shutil.copytree(os.path.join(ROOT, "lang"), res / "lang")
    shutil.copytree(os.path.join(ROOT, "assets"), res / "assets")
    ja = json.load(open(res / "lang" / "en.json", encoding="utf-8"))
    ja["app_title"] = "写真の容量を減らす"
    json.dump(ja, open(res / "lang" / "ja.json", "w", encoding="utf-8"), ensure_ascii=False)
    monkeypatch.setattr(i18n, "resource_dir", lambda: str(res))
    monkeypatch.setattr(i18n, "LANGS", i18n.available_langs())
    assert i18n.LANGS == ("ko", "en", "ja")
    app = make_app()
    assert i18n.LANG_NAMES["ja"] in app.cb_lang.cget("values")
    app.v_lang.set(i18n.LANG_NAMES["ja"])
    app._on_lang()
    assert app.root.title().startswith("写真の容量を減らす")


def test_the_notice_survives_a_language_switch(root, make_app):
    app = make_app()
    app._on_update_result(update_check.UpdateInfo("0.2.0", "0.1.0", update_check.SITE + "tools/photoresize"), True)
    app.v_lang.set(i18n.LANG_NAMES["ko"])
    app._on_lang()
    labels = [w for w in app.update_area.winfo_children()[0].winfo_children() if w.winfo_class() == "Label"]
    assert labels and "0.2.0" in labels[0].cget("text") and labels[0].cget("text") != \
        i18n._inst._fallback["update_available"].format(latest="0.2.0", current="0.1.0")


# ------------------------------------------------------------------ settings
def test_settings_that_cannot_be_saved_do_not_stop_the_app(root, make_app, folder, tmp_path, monkeypatch):
    blocked = tmp_path / "a_folder_not_a_file"
    blocked.mkdir()
    monkeypatch.setattr(i18n, "_settings_path", str(blocked))
    app = make_app([str(folder)])
    app.mode_chips.pick(shrink.SIZE)  # saves: fails quietly
    app.run()
    wait_run(root, app)
    assert app.summary.count >= 6


def test_settings_go_to_appdata_when_the_exe_folder_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr(i18n, "app_dir", lambda: str(tmp_path / "Program Files" / "photo-resize"))
    monkeypatch.setattr(i18n, "_writable", lambda folder: False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    assert i18n.settings_dir() == str(tmp_path / "AppData" / "photo-resize")


def test_settings_stay_next_to_the_exe_when_it_already_has_one(tmp_path, monkeypatch):
    here = tmp_path / "portable"
    here.mkdir()
    (here / "settings.json").write_text("{}")
    monkeypatch.setattr(i18n, "app_dir", lambda: str(here))
    monkeypatch.setattr(i18n, "_writable", lambda folder: False)
    assert i18n.settings_dir() == str(here)


# ------------------------------------------------------------------ command line and the exe
def test_frozen_exe_given_files_opens_the_window_with_them(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(gui, "launch", lambda paths=None: seen.append(paths))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "stdout", None)
    assert main.main([str(tmp_path / "a.jpg"), str(tmp_path)]) == 0
    assert seen == [[str(tmp_path / "a.jpg"), str(tmp_path)]]


def test_no_arguments_opens_the_window(monkeypatch):
    seen = []
    monkeypatch.setattr(gui, "launch", lambda paths=None: seen.append(paths))
    assert main.main([]) == 0 and seen == [None]


@pytest.mark.parametrize("args,code", [(["--quality", "100"], 0), (["--size", "10", "--mode", "size"], 0),
                                       (["--target", "999999MB"], 0), (["--target", "0"], 2),
                                       (["--quality", "best"], 2)])
def test_cli_values_are_clamped_or_refused(tmp_path, capsys, args, code):
    src = ms.jpeg(str(tmp_path / "a.jpg"), 900, 600, seed=1)
    if code == 0:
        assert main.main([src, "--lang", "en", *args]) in (0,)
    else:
        with pytest.raises(SystemExit) as e:
            main.main([src, "--lang", "en", *args])
        assert e.value.code == code


def test_cli_with_nothing_to_shrink(tmp_path, capsys):
    (tmp_path / "notes.txt").write_text("x")
    os.makedirs(tmp_path / "_small")
    ms.jpeg(str(tmp_path / "_small" / "old.jpg"), 300, 200, seed=1)
    assert main.main([str(tmp_path), "--lang", "en"]) == 2
    assert "no photos" in capsys.readouterr().err


# ------------------------------------------------------------------ a big list
def test_a_list_of_1500_photos_stays_quick(root, make_app, tmp_path):
    img = ms.picture(48, 32, 1)
    for i in range(1500):
        img.save(_p(tmp_path, i), "JPEG", quality=95)
    app = make_app()
    t = time.time()
    assert app.add_paths([str(tmp_path)]) == 1500
    added = time.time() - t
    assert added < 5, added
    wait_estimate(root, app)
    t = time.time()
    app.mode_chips.pick(shrink.SIZE)
    assert time.time() - t < 3
    assert "1500" in app.info_text()


def _p(base, i):
    folder = base / f"d{i // 300}"
    folder.mkdir(exist_ok=True)
    return folder / f"IMG_{i:05d}.jpg"
