"""The window, driven from Python (callbacks called directly, never fake mouse messages).
One Tk for the module; each test gets its own Toplevel with an App on it."""
from __future__ import annotations

import gc
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import weakref

import pytest

import gui
import i18n
import make_samples as ms
import prefs as prefs_mod
import shrink
import theme
import update_check
from conftest import ROOT, files_under, snapshot


@pytest.fixture(scope="module")
def root():
    gui._enable_dpi_awareness()
    r = gui.TkinterDnD.Tk() if gui._HAS_DND else tk.Tk()
    theme.set_scale(r.winfo_fpixels("1i"))
    r.withdraw()
    yield r
    r.destroy()


def pump(root, until=None, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        root.update()
        if until is not None and until():
            return True
        time.sleep(0.01)
    return until is None


@pytest.fixture
def make_app(root):
    apps = []

    def make(paths=None, prefs=None, size=theme.WINDOW):
        top = tk.Toplevel(root)
        top.geometry(f"{gui.px(size[0])}x{gui.px(size[1])}+20+20")
        app = gui.App(top, paths, prefs=prefs or prefs_mod.Prefs())
        apps.append(app)
        pump(root, timeout=0.3)
        return app

    yield make
    for app in apps:
        if not app.closed:
            app.on_close()
            pump(root, lambda: app.closed, timeout=30)
    i18n.set_lang("en", persist=False)


@pytest.fixture
def folder(tmp_path):
    ms.make_all(str(tmp_path / "photos"))
    return tmp_path / "photos"


def wait_estimate(root, app):
    assert pump(root, lambda: bool(app.measured), timeout=60)


def wait_run(root, app):
    assert pump(root, lambda: not app.running, timeout=120)


# ------------------------------------------------------------------ the flow
def test_add_estimate_run_summary(root, make_app, folder):
    before = snapshot(folder)
    app = make_app([str(folder)])
    assert len(app.items) == 7 and len(app.tree.get_children()) == 7
    wait_estimate(root, app)
    assert "→ about" in app.lbl_big.cget("text") and "%" in app.lbl_pct.cget("text")
    assert snapshot(folder) == before  # nothing written before [Shrink]
    app.run()
    assert app.running and str(app.btn_cancel.cget("state")) == "normal"
    wait_run(root, app)
    made = [f for f in files_under(folder) if f.startswith("_small/")]
    assert len(made) == sum(1 for r in app.results.values() if r.dst) >= 6
    text = app.info_text()
    assert "location removed from" in text and str(app.summary.gps) in text
    assert app.summary.gps >= 5
    assert str(app.btn_open.cget("state")) == "normal"
    assert all(app.tree.set(str(i), "status") for i in range(7))


def test_nothing_is_written_to_the_real_settings(root, make_app, folder, isolated_settings):
    app = make_app([str(folder)])
    app.mode_chips.pick(shrink.SIZE)
    assert os.path.exists(isolated_settings)
    assert not os.path.exists(os.path.join(ROOT, "settings.json"))
    appdata = os.path.join(os.environ.get("APPDATA", ""), "photo-resize")
    assert not os.path.exists(appdata)
    assert i18n.settings_path() == isolated_settings


def test_mode_chips_switch_the_options(root, make_app, folder):
    app = make_app([str(folder)])
    app.mode_chips.pick(shrink.SIZE)
    assert app.prefs.mode == shrink.SIZE and set(app.option_chips.chips) == {str(s) for s in shrink.SIZES}
    app.option_chips.pick("1280")
    assert app.prefs.long_edge == 1280
    app.mode_chips.pick(shrink.QUALITY)
    app.option_chips.pick("low")
    assert app.prefs.quality_level == "low" and app.prefs.options().quality == 60
    app.mode_chips.pick(shrink.TARGET)
    app.option_chips.pick("1000")
    assert app.prefs.target_kb == 1000
    chip = app.option_chips.chips["1000"]
    assert chip.cget("bg").lower() == theme.COLORS["accent"].lower()  # the chosen chip is marked


def test_custom_target(root, make_app):
    app = make_app()
    app.option_chips.pick(gui.CUSTOM)
    assert app.custom_row.winfo_manager() == "pack"
    app.v_custom.set("300")
    app._on_custom()
    assert app.prefs.target_kb == 300 and app.lbl_custom_err.cget("text") == ""
    app.v_custom.set("abc")
    app._on_custom()
    assert app.lbl_custom_err.cget("text") and app.prefs.target_kb == 300
    app.option_chips.pick("500")
    assert app.custom_row.winfo_manager() == "" and app.prefs.target_kb == 500


def test_changing_options_drops_old_results(root, make_app, folder):
    app = make_app([str(folder)])
    app.run()
    wait_run(root, app)
    assert app.summary is not None
    app.mode_chips.pick(shrink.SIZE)
    assert app.summary is None and not app.results


def test_preview_shows_both_at_the_same_scale(root, make_app, folder):
    app = make_app([str(folder)])
    app.tree.selection_set("0")
    app._on_select()
    assert pump(root, lambda: isinstance(app.preview, tuple), timeout=60)
    pump(root, timeout=0.3)
    assert "Original" in app.lbl_orig.cget("text") and "Result" in app.lbl_res.cget("text")
    assert len(app._photos) == 2
    a, b = app._photos
    assert (a.width(), a.height()) == (b.width(), b.height())
    app.zoom_chips.pick("2.0")
    assert app.zoom == 2.0 and len(app._photos) == 2
    a, b = app._photos
    assert (a.width(), a.height()) == (b.width(), b.height())


def test_cancel_stops_without_half_files(root, make_app, tmp_path):
    for i in range(10):
        ms.jpeg(str(tmp_path / "many" / f"p{i}.jpg"), 2000, 1500, seed=i)
    app = make_app([str(tmp_path / "many")])
    app.run()
    app.cancel()
    wait_run(root, app)
    assert app.status[0] == "status_cancelled"
    made = files_under(tmp_path / "many")
    assert not any(f.endswith(".part") for f in made)


def test_closing_during_a_run_waits_for_it(root, make_app, tmp_path):
    for i in range(6):
        ms.jpeg(str(tmp_path / "c" / f"p{i}.jpg"), 2000, 1500, seed=i)
    app = make_app([str(tmp_path / "c")])
    app.run()
    pump(root, timeout=0.2)
    app.on_close()
    assert pump(root, lambda: app.closed, timeout=60)
    assert not any(th.is_alive() for th in app.threads)
    assert not any(f.endswith(".part") for f in files_under(tmp_path / "c"))


def test_language_switch_keeps_everything(root, make_app, folder):
    app = make_app([str(folder)])
    app.mode_chips.pick(shrink.SIZE)
    app.v_lang.set(i18n.LANG_NAMES["ko"])
    app._on_lang()
    assert i18n.current_lang() == "ko"
    assert app.root.title().startswith(i18n.t("app_title"))
    assert len(app.tree.get_children()) == 7 and app.prefs.mode == shrink.SIZE
    assert app.mode_chips.var.get() == shrink.SIZE


@pytest.mark.parametrize("lang", list(i18n.LANGS))
def test_no_text_is_cut_off_at_the_smallest_window(root, make_app, folder, lang):
    i18n.set_lang(lang, persist=False)
    app = make_app([str(folder)], size=theme.WINDOW_MIN)
    app._on_update_result(update_check.UpdateInfo("9.9.9", "0.1.0", update_check.SITE + "tools/photoresize"), True)
    pump(root, timeout=0.5)
    widgets = [app.btn_run, app.btn_cancel, app.btn_open, app.btn_files, app.btn_folder, app.btn_clear,
               app.chk_png, app.chk_update, app.chk_recursive]
    for group in app.chip_groups + [app.zoom_chips]:
        widgets += list(group.chips.values())
    cut = [w.cget("text") for w in widgets if w.winfo_width() < w.winfo_reqwidth()]
    assert not cut, cut
    assert app.chk_png.winfo_ismapped() and app.btn_run.winfo_ismapped()  # the side panel fits


# ------------------------------------------------------------------ new version notice
INFO = update_check.UpdateInfo("0.2.0", "0.1.0", "https://chaekgalpi.co.kr/tools/photoresize")


def test_notice_is_one_line_and_keeps_the_side_panel(root, make_app, folder):
    app = make_app([str(folder)])
    pump(root, timeout=0.3)
    side_before = (app.btn_run.winfo_rooty(), app.chk_png.winfo_rooty())
    app._on_update_result(INFO, True)
    pump(root, timeout=0.3)
    assert app.update_area.winfo_children() and app.prefs.update_check_last == update_check.today()
    assert (app.btn_run.winfo_rooty(), app.chk_png.winfo_rooty()) == side_before
    assert app.tree.winfo_height() > 50 and app.cv_orig.winfo_height() > 30
    app._update_later()
    assert app.prefs.update_check_skipped == "0.2.0" and not app.update_area.winfo_children()


def test_update_opens_the_tools_page_only(root, make_app, monkeypatch):
    opened = []
    monkeypatch.setattr(gui.webbrowser, "open", lambda url: opened.append(url))
    app = make_app()
    app._on_update_result(INFO, True)
    app._update_open()
    assert opened == [INFO.url] and not app.update_area.winfo_children()


def test_no_notice_when_switched_off(root, make_app):
    app = make_app(prefs=prefs_mod.Prefs(update_check=False))
    app._on_update_result(INFO, True)
    assert not app.update_area.winfo_children()


def test_unanswered_check_does_not_use_up_the_day(root, make_app):
    app = make_app()
    app._on_update_result(None, False)
    assert app.prefs.update_check_last == ""


def test_window_closed_while_the_request_is_out_frees_the_app(root, monkeypatch):
    """The decisive check (scan-pdf-split / TrimPDF): close the window while the request is
    out, collect on the main thread, and the App must be gone - the worker thread holds
    nothing of it."""
    release = threading.Event()
    started = threading.Event()

    def slow_fetch(slug, version):
        started.set()
        release.wait(10)
        return None

    monkeypatch.setitem(update_check.check_async.__kwdefaults__, "fetcher", slow_fetch)
    top = tk.Toplevel(root)
    app = gui.App(top, prefs=prefs_mod.Prefs())
    ref = weakref.ref(app)
    assert pump(root, started.is_set, timeout=5)
    app.on_close()
    assert pump(root, lambda: app.closed, timeout=10)
    del app
    pump(root, timeout=0.3)
    gc.collect()
    assert ref() is None
    release.set()


CHILD = r'''
import sys, time, threading, tkinter as tk
sys.path.insert(0, ROOT)
import urllib.request
def blocked(*a, **k): raise OSError("blocked")
urllib.request.urlopen = blocked
import update_check
update_check.fetch.__kwdefaults__["opener"] = blocked
def slow(slug, version):
    time.sleep(1.0)
    return None
update_check.check_async.__kwdefaults__["fetcher"] = slow
import i18n, prefs, gui
prefs.save = lambda *a, **k: None
i18n.set_lang("en", persist=False)
root = tk.Tk()
app = gui.App(root, prefs=prefs.Prefs())
root.after(1700, app.on_close)   # the request is out (1.5 s delay + 1 s answer)
root.mainloop()
time.sleep(1.5)                  # the thread finishes after the window is gone
print("alive")
'''


CHILD_RUN = r'''
import sys, time, tkinter as tk
sys.path.insert(0, ROOT)
import urllib.request
def blocked(*a, **k): raise OSError("blocked")
urllib.request.urlopen = blocked
import update_check
update_check.fetch.__kwdefaults__["opener"] = blocked
update_check.check_async.__kwdefaults__["fetcher"] = lambda s, v: None
import i18n, prefs, gui
prefs.save = lambda *a, **k: None
i18n.set_lang("en", persist=False)
root = tk.Tk()
app = gui.App(root, [FOLDER], prefs=prefs.Prefs())
def step():
    if app.measured and not app.running and not app.results:
        app.tree.selection_set("0"); app._on_select(); app.run()
    if app.summary is not None:
        app.on_close()
        return
    root.after(100, step)
root.after(100, step)
while not app.closed:            # pump like a test harness or an embedding program would
    root.update()
    time.sleep(0.01)
try:
    root.update()                # anything still queued in Tk wakes up now
except tk.TclError:
    pass
print("closed", app.summary.count)
'''


def test_a_real_run_then_close_leaves_no_tcl_errors(tmp_path):
    ms.make_all(str(tmp_path / "p"))
    script = tmp_path / "child_run.py"
    folder = str(tmp_path / "p")
    script.write_text(f"ROOT = {ROOT!r}\nFOLDER = {folder!r}\n" + CHILD_RUN, encoding="utf-8")
    env = dict(os.environ, PHOTO_RESIZE_SETTINGS=str(tmp_path / "settings.json"))
    out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=120, env=env)
    assert out.returncode == 0 and "closed 7" in out.stdout, out.stderr[-2000:]
    assert out.stderr.strip() == "", out.stderr[-2000:]


def test_closing_mid_request_does_not_crash_the_process(tmp_path):
    script = tmp_path / "child.py"
    script.write_text(f"ROOT = {ROOT!r}\n" + CHILD, encoding="utf-8")
    env = dict(os.environ, PHOTO_RESIZE_SETTINGS=str(tmp_path / "settings.json"))
    for _ in range(3):
        out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=60, env=env)
        assert out.returncode == 0 and "alive" in out.stdout, out.stderr[-2000:]
        assert "invalid command name" not in out.stderr and "Traceback" not in out.stderr, out.stderr[-2000:]
