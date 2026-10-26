"""Japanese and Simplified Chinese screens (v0.1.2): the files themselves, switching while
the window is open, layout at the smallest and default sizes (100 % and 150 %), glyphs in
the chosen fonts, every error and notice in both languages, results that do not depend on
the language, and safe fallbacks for odd settings or a missing file."""
from __future__ import annotations

import builtins
import ctypes
import json
import os
import re
import shutil
import tkinter as tk
import tkinter.font as tkfont

import pytest

import gui
import i18n
import main
import make_samples as ms
import prefs as prefs_mod
import shrink
import theme
import update_check as uc
from conftest import ROOT, files_under, sha1
from test_gui import folder, make_app, pump, root, wait_estimate, wait_run  # noqa: F401  (fixtures)
from version import APP_VERSION

NEW = ("ja", "zh-CN")
ALL = ("ko", "en", "zh-CN", "ja")
HANGUL = re.compile("[\uac00-\ud7a3\u3131-\u318e]")
KANA = re.compile("[\u3040-\u30ff]")
CJK = re.compile("[\u3040-\u30ff\u3400-\u9fff]")
# characters only one of the two scripts uses: a Chinese word in the Japanese file or a
# traditional / Japanese form in the Simplified Chinese file
SIMPLIFIED_ONLY = set("张压图选预览设语处终页开关输仅较铺")
TRADITIONAL_OR_JA_ONLY = set("張壓圖選預覽設語處終頁開關輸僅較結畫質檔")


def load(lang):
    with open(os.path.join(ROOT, "lang", f"{lang}.json"), encoding="utf-8") as f:
        return json.load(f)


def placeholders(text):
    """{name}, %(name)s and bare %s, in order of appearance."""
    return re.findall(r"\{(\w+)\}|%\((\w+)\)|(%s)", text)


# ------------------------------------------------------------------ a. the files
def test_both_new_languages_are_offered_in_series_order():
    assert i18n.LANGS == ALL
    assert {c: i18n.LANG_NAMES[c] for c in NEW} == {"ja": "日本語", "zh-CN": "简体中文"}


@pytest.mark.parametrize("lang", NEW)
def test_same_keys_as_korean_and_nothing_empty(lang):
    ko, other = load("ko"), load(lang)
    assert set(other) == set(ko)
    assert list(other) == list(ko)  # same order: the files diff line by line
    assert [k for k, v in other.items() if not isinstance(v, str) or not v.strip()] == []


@pytest.mark.parametrize("lang", NEW)
def test_same_placeholders_and_line_breaks_as_korean(lang):
    ko, other = load("ko"), load(lang)
    for key in ko:
        assert sorted(placeholders(other[key])) == sorted(placeholders(ko[key])), key
        assert other[key].count("\n") == ko[key].count("\n"), key
        assert other[key].endswith("\n") == ko[key].endswith("\n"), key


@pytest.mark.parametrize("lang", NEW)
def test_every_placeholder_fills(lang):
    """Formatting each string with the names it asks for never falls back to the raw text."""
    i18n.set_lang(lang, persist=False)
    for key, text in load(lang).items():
        names = {a for a, _, _ in placeholders(text) if a}
        if names and "%(" not in text:
            out = i18n.t(key, **{n: "X" for n in names})
            assert "{" not in out and out.count("X") >= len(names), key


@pytest.mark.parametrize("lang", NEW)
def test_really_translated(lang):
    """Where Korean has Hangul, the new file has kana or hanzi; no Hangul is left over, and
    the Japanese and Chinese files are not mixed up."""
    ko, other = load("ko"), load(lang)
    for key, text in other.items():
        assert not HANGUL.search(text), key
        if HANGUL.search(ko[key]):
            assert CJK.search(text), key
    joined = "".join(other.values())
    if lang == "ja":
        assert KANA.search(joined) and not (set(joined) & SIMPLIFIED_ONLY)
    else:
        assert not KANA.search(joined) and not (set(joined) & TRADITIONAL_OR_JA_ONLY)


@pytest.mark.parametrize("lang, label", [("ja", "ご意見を送る"), ("zh-CN", "发送反馈")])
def test_the_feedback_label_is_the_series_wording(lang, label):
    assert load(lang)["btn_feedback"] == label
    assert load(lang)["err_feedback_open"].rstrip().endswith("{url}")


@pytest.mark.parametrize("lang", NEW)
def test_the_files_are_plain_utf8_json(lang):
    raw = open(os.path.join(ROOT, "lang", f"{lang}.json"), "rb").read()
    assert not raw.startswith(b"\xef\xbb\xbf")  # no BOM; line ends follow core.autocrlf like ko.json
    json.loads(raw.decode("utf-8"))


# ------------------------------------------------------------------ b. switching while open
def shown(app):
    """Every text on the screen: widget texts, table headings, canvas texts, the title."""
    out = [app.root.title()]

    def walk(w):
        try:
            text = str(w.cget("text"))
        except tk.TclError:
            text = ""
        if text:
            out.append(text)
        if w.winfo_class() == "Canvas":
            out.extend(w.itemcget(i, "text") for i in w.find_all() if w.type(i) == "text")
        for child in w.winfo_children():
            walk(child)

    walk(app.root)
    out.extend(app.tree.heading(c, "text") for c in app.tree["columns"])
    out.extend(app.tree.set(i, "status") for i in app.tree.get_children())
    return [s for s in out if s]


def foreign_texts(lang):
    """Fixed strings (no placeholders) of the other languages that this one does not use."""
    mine = set(load(lang).values())
    return {v for other in ALL if other != lang for v in load(other).values()
            if v not in mine and "{" not in v and "%" not in v and any(c.isalpha() for c in v)}


def switch(app, lang):
    app.v_lang.set(i18n.LANG_NAMES[lang])
    app._on_lang()
    pump(app.root.master, timeout=0.2)


def test_switching_through_all_four_changes_every_text(root, make_app, folder):
    app = make_app([str(folder)])
    wait_estimate(root, app)
    app.run()
    wait_run(root, app)
    statuses = ("st_done", "st_done_q", "st_over", "st_small", "st_failed")
    for lang in ("ko", "ja", "zh-CN", "en", "ko"):
        switch(app, lang)
        assert i18n.current_lang() == lang
        texts = shown(app)
        joined = "\n".join(texts)
        assert app.root.title() == f"{i18n.t('app_title')} {APP_VERSION}"
        for key in ("app_title", "app_tagline", "btn_add_files", "btn_add_folder", "btn_clear", "opt_recursive",
                    "lbl_how", "mode_target", "mode_size", "mode_quality", "lbl_output", "opt_keep_png",
                    "btn_run", "btn_cancel", "btn_open_results", "btn_feedback", "opt_update_check",
                    "lbl_preview", "zoom_fit", "status_done"):
            assert i18n.t(key) in texts, (lang, key)
        assert [app.tree.heading(c, "text") for c in app.tree["columns"]] == \
            [i18n.t(f"col_{c}") for c in app.tree["columns"]]
        assert app.lbl_status.cget("text") == i18n.t("status_done")
        assert i18n.t("summary_gps", count=app.summary.gps) in app.info_text()
        for iid in app.tree.get_children():
            cell = app.tree.set(iid, "status")
            assert any(i18n.t(k, q=0, error="").split("0")[0].strip() in cell for k in statuses), (lang, cell)
        leftovers = [t for t in texts if t in foreign_texts(lang)]
        assert leftovers == [], (lang, leftovers)
        if lang != "ko":
            assert not HANGUL.search(joined), lang
        assert len(app.tree.get_children()) == 7  # nothing lost on the way


@pytest.mark.parametrize("lang", NEW)
def test_the_choice_is_saved_and_comes_back_at_the_next_start(root, make_app, isolated_settings, lang):
    app = make_app()
    switch(app, lang)
    with open(isolated_settings, encoding="utf-8") as f:
        assert json.load(f)["lang"] == lang
    app.on_close()
    pump(root, lambda: app.closed, timeout=30)
    i18n.set_lang("en", persist=False)  # a fresh process starts in no language at all
    assert i18n.init() == lang and i18n.current_lang() == lang
    again = make_app()
    assert again.v_lang.get() == i18n.LANG_NAMES[lang]
    assert again.root.title().startswith(load(lang)["app_title"])


@pytest.mark.parametrize("lang", NEW)
def test_the_choice_does_not_touch_the_other_settings(root, make_app, isolated_settings, lang):
    app = make_app(prefs=prefs_mod.Prefs(mode=shrink.QUALITY, quality_level="high", keep_png=True))
    app._save()
    switch(app, lang)
    p = prefs_mod.load()
    assert (p.mode, p.quality_level, p.keep_png) == (shrink.QUALITY, "high", True)


# ------------------------------------------------------------------ c. layout
def cut_off(app):
    widgets = [app.btn_run, app.btn_cancel, app.btn_open, app.btn_files, app.btn_folder, app.btn_clear,
               app.chk_png, app.chk_update, app.chk_recursive, app.lnk_feedback]
    for group in app.chip_groups + [app.zoom_chips]:
        widgets += list(group.chips.values())
    return [w.cget("text") for w in widgets if w.winfo_width() < w.winfo_reqwidth()]


def header_problems(app):
    """The title, the tagline and the right-hand group (link, check box, language) sit in one
    row without overlapping, and the tagline is not squeezed."""
    head = app.lnk_feedback.master.master
    right = app.lnk_feedback.master
    left_labels = [w for w in head.winfo_children() if w is not right]
    problems = []
    edges = sorted((w.winfo_rootx(), w.winfo_rootx() + w.winfo_width(), str(w.cget("text"))) for w in left_labels)
    for (a0, a1, an), (b0, b1, bn) in zip(edges, edges[1:]):
        if a1 > b0:
            problems.append(("overlap", an, bn))
    if edges and edges[-1][1] > right.winfo_rootx():
        problems.append(("into the right group", edges[-1][2]))
    for w in left_labels:
        if w.winfo_width() < w.winfo_reqwidth():
            problems.append(("squeezed", str(w.cget("text"))))
    kids = sorted((w.winfo_rootx(), w.winfo_rootx() + w.winfo_width()) for w in right.winfo_children())
    problems += [("right group overlap", a, b) for a, b in zip(kids, kids[1:]) if a[1] > b[0]]
    if right.winfo_rootx() + right.winfo_width() > head.winfo_rootx() + head.winfo_width():
        problems.append(("off the edge", "right group"))
    return problems


def heading_problems(app):
    font = tkfont.Font(root=app.root, font=app.f_bold)
    return [(c, app.tree.heading(c, "text")) for c in app.tree["columns"]
            if font.measure(app.tree.heading(c, "text")) + gui.px(8) > app.tree.column(c, "width")]


@pytest.mark.parametrize("size", [theme.WINDOW_MIN, theme.WINDOW], ids=["min", "default"])
@pytest.mark.parametrize("lang", ALL)
def test_nothing_is_cut_or_overlapping(root, make_app, folder, lang, size):
    i18n.set_lang(lang, persist=False)
    app = make_app([str(folder)], size=size)
    app._on_update_result(uc.UpdateInfo("9.9.9", "0.1.0", uc.SITE + "tools/photoresize"), True)
    pump(root, timeout=0.5)
    assert cut_off(app) == []
    assert header_problems(app) == []
    assert heading_problems(app) == []
    assert app.chk_png.winfo_ismapped() and app.btn_run.winfo_ismapped()
    notice = app.update_area.winfo_children()[0]
    assert all(w.winfo_width() >= w.winfo_reqwidth() for w in notice.winfo_children()
               if w.winfo_class() in ("TButton", "Button"))


@pytest.mark.xfail(strict=True, reason="v0.1.1 layout, every language: the columns add up to 726 design px but "
                   "the list is about 620 wide at the smallest window, so the status column is off the right edge "
                   "(no horizontal scroll). Left as it is in this language-only change; see the hub report.")
@pytest.mark.parametrize("lang", ALL)
def test_the_status_column_shows_at_the_smallest_window(root, make_app, folder, lang):
    i18n.set_lang(lang, persist=False)
    app = make_app([str(folder)], size=theme.WINDOW_MIN)
    pump(root, timeout=0.5)
    widths = sum(int(app.tree.column(c, "width")) for c in app.tree["columns"])
    assert widths <= app.tree.winfo_width()


@pytest.fixture
def scale_100(root):
    """The window as a 100 % (96 dpi) screen draws it, on whatever screen runs the tests."""
    before_tk, before_scale = root.tk.call("tk", "scaling"), theme.SCALE
    root.tk.call("tk", "scaling", 96 / 72)
    theme.SCALE = 1.0
    yield
    root.tk.call("tk", "scaling", before_tk)
    theme.SCALE = before_scale


@pytest.mark.parametrize("lang", ALL)
def test_smallest_window_at_100_percent(root, make_app, folder, scale_100, lang):
    i18n.set_lang(lang, persist=False)
    app = make_app([str(folder)], size=theme.WINDOW_MIN)
    pump(root, timeout=0.5)
    assert cut_off(app) == [] and header_problems(app) == [] and heading_problems(app) == []
    assert app.btn_run.winfo_ismapped()


@pytest.fixture
def scale_150(root):
    before_tk, before_scale = root.tk.call("tk", "scaling"), theme.SCALE
    root.tk.call("tk", "scaling", 144 / 72)
    theme.SCALE = 1.5
    yield
    root.tk.call("tk", "scaling", before_tk)
    theme.SCALE = before_scale


@pytest.mark.parametrize("lang", ALL)
def test_smallest_window_at_150_percent(root, make_app, folder, scale_150, lang):
    i18n.set_lang(lang, persist=False)
    app = make_app([str(folder)], size=theme.WINDOW_MIN)
    pump(root, timeout=0.5)
    assert cut_off(app) == [] and header_problems(app) == [] and heading_problems(app) == []
    assert app.btn_run.winfo_ismapped()


# ------------------------------------------------------------------ d. fonts and glyphs
FONT_FILES = {"Yu Gothic UI": ("YuGothR.ttc", "YuGothM.ttc"), "Meiryo UI": ("meiryo.ttc",),
              "Microsoft YaHei UI": ("msyh.ttc",), "Microsoft YaHei": ("msyh.ttc",)}


@pytest.mark.parametrize("lang, wanted", [("ja", "Yu Gothic UI"), ("zh-CN", "Microsoft YaHei UI")])
def test_the_window_uses_the_languages_own_font(root, make_app, lang, wanted):
    if wanted not in set(tkfont.families(root)):
        pytest.skip(f"{wanted} is not installed here")
    i18n.set_lang(lang, persist=False)
    app = make_app()
    assert app.f_body[0] == wanted
    assert tkfont.Font(root=root, font=app.f_body).actual("family") == wanted


def _faces(path):
    from PIL import ImageFont

    for index in range(8):
        try:
            yield ImageFont.truetype(path, 20, index=index)
        except OSError:
            return


@pytest.mark.parametrize("lang, family", [("ja", "Yu Gothic UI"), ("zh-CN", "Microsoft YaHei UI")])
def test_every_character_has_a_glyph_in_that_font(lang, family):
    """No character of the language file would draw as an empty box (the .notdef glyph)."""
    windir = os.environ.get("WINDIR", r"C:\Windows")
    paths = [os.path.join(windir, "Fonts", n) for n in FONT_FILES[family]]
    paths = [p for p in paths if os.path.exists(p)]
    if not paths:
        pytest.skip(f"no font file for {family}")
    faces = list(_faces(paths[0]))
    face = next((f for f in faces if f.getname()[0] == family), faces[0])
    from PIL import Image, ImageDraw

    def drawn(ch):
        img = Image.new("L", (32, 32))
        ImageDraw.Draw(img).text((2, 2), ch, font=face, fill=255)
        return img.tobytes()

    notdef = drawn("\U0010fffd")  # a private-use character no font has
    chars = sorted({c for v in load(lang).values() for c in v if ord(c) > 0x7F and not c.isspace()})
    missing = [c for c in chars if drawn(c) == notdef]
    assert chars and missing == []


# ------------------------------------------------------------------ e. errors and notices
def run_cli(capsys, lang, *args):
    code = main.main([*map(str, args), "--lang", lang])
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.mark.parametrize("lang", NEW)
def test_unreadable_files_and_a_broken_heic(capsys, tmp_path, lang):
    (tmp_path / "x.jpg").write_bytes(b"not a photo")
    (tmp_path / "y.png").write_bytes(b"")
    (tmp_path / "z.heic").write_bytes(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 40)
    code, out, err = run_cli(capsys, lang, tmp_path)
    i18n.set_lang(lang, persist=False)
    failed = i18n.t("st_failed", error="")
    assert code == 1 and out.count(failed) == 3
    assert i18n.t("summary_failed", count=3) in out and i18n.t("cli_start", count=3, how="")[:4] in out
    assert not HANGUL.search(out + err)


@pytest.mark.parametrize("lang", NEW)
def test_a_good_heic_is_done(capsys, tmp_path, lang):
    ms.heic(str(tmp_path / "a.heic"), 1600, 1200)
    code, out, err = run_cli(capsys, lang, tmp_path, "--target", "100KB")
    i18n.set_lang(lang, persist=False)
    assert code == 0 and i18n.t("st_done") in out and i18n.t("summary_gps", count=1) in out


@pytest.mark.parametrize("lang", NEW)
def test_a_failed_write(capsys, tmp_path, monkeypatch, lang):
    ms.jpeg(str(tmp_path / "a.jpg"), 900, 600, seed=1)
    real_open = builtins.open

    def fake_open(path, mode="r", *a, **k):
        if str(path).endswith(".part"):
            raise OSError(28, "No space left on device")
        return real_open(path, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", fake_open)
    code, out, err = run_cli(capsys, lang, tmp_path, "--target", "100KB")
    monkeypatch.undo()
    i18n.set_lang(lang, persist=False)
    assert code == 1 and i18n.t("st_failed", error="") in out and "No space" in out
    assert files_under(tmp_path / "_small") == []


@pytest.mark.parametrize("lang", NEW)
def test_already_small_and_over_target(capsys, tmp_path, monkeypatch, lang):
    ms.small_jpeg(str(tmp_path / "tiny.jpg"))
    code, out, err = run_cli(capsys, lang, tmp_path, "--mode", "size")
    i18n.set_lang(lang, persist=False)
    assert code == 0 and i18n.t("st_small") in out and i18n.t("summary_small", count=1) in out
    big = tmp_path / "big"
    big.mkdir()
    ms.jpeg(str(big / "b.jpg"), 3000, 2000, seed=5)
    monkeypatch.setattr(shrink, "MIN_EDGE", 2000)
    code, out, err = run_cli(capsys, lang, big, "--target", "20KB")
    i18n.set_lang(lang, persist=False)
    assert code == 0 and i18n.t("st_over") in out and i18n.t("summary_over", count=1) in out


@pytest.mark.parametrize("lang", NEW)
def test_command_line_mistakes(capsys, tmp_path, lang):
    load_ = load(lang)
    assert run_cli(capsys, lang, tmp_path / "missing.jpg")[2].startswith(
        load_["err_open_failed"].split("{")[0])
    assert load_["cli_no_input"] in run_cli(capsys, lang, tmp_path)[2]
    for args, key in ((["x.jpg", "--target", "big"], "cli_bad_target"),
                      (["x.jpg", "--quality", "best"], "cli_bad_quality"),
                      (["x.jpg", "--mode", "zip"], "cli_invalid_choice")):
        with pytest.raises(SystemExit):
            main.main([*args, "--lang", lang])
        err = capsys.readouterr().err
        assert load_[key].split("%")[0].split("{")[0][:3] in err, (key, err)
        assert load_["cli_error"].split(": ")[1] in err  # the word for "error"
    with pytest.raises(SystemExit):
        main.main(["--lang", lang, "--help"])
    help_text = capsys.readouterr().out
    assert load_["cli_usage"].strip() in help_text and load_["cli_desc"][:10] in help_text


@pytest.mark.parametrize("lang", NEW)
def test_window_errors_and_notices(root, make_app, tmp_path, monkeypatch, lang):
    i18n.set_lang(lang, persist=False)
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "x.jpg").write_bytes(b"nope")
    app = make_app([str(bad)])
    app.add_paths([str(tmp_path / "missing.jpg")])
    assert app.lbl_status.cget("text") == i18n.t("err_missing", name=str(tmp_path / "missing.jpg"), count=1) or \
        app.lbl_status.cget("text").startswith(i18n.t("err_missing", name="", count=1).split(":")[0])
    empty = tmp_path / "empty"
    empty.mkdir()
    app.add_paths([str(empty)])
    assert app.lbl_status.cget("text") == i18n.t("msg_no_photos")
    app.tree.selection_set("0")
    app._on_select()
    assert pump(root, lambda: isinstance(app.preview, str), timeout=20)
    pump(root, timeout=0.3)
    texts = [app.cv_res.itemcget(i, "text") for i in app.cv_res.find_all() if app.cv_res.type(i) == "text"]
    assert texts and texts[0].startswith(i18n.t("st_failed", error=""))
    app.run()
    wait_run(root, app)
    assert i18n.t("summary_failed", count=1) in app.info_text()
    assert app.tree.set("0", "status").startswith(gui.CROSS) and i18n.t("st_failed", error="") in \
        app.tree.set("0", "status")


@pytest.mark.parametrize("lang", NEW)
def test_already_small_preview_and_custom_target_error(root, make_app, tmp_path, lang):
    i18n.set_lang(lang, persist=False)
    ms.small_jpeg(str(tmp_path / "tiny.jpg"))
    app = make_app([str(tmp_path)], prefs=prefs_mod.Prefs(mode=shrink.SIZE))
    app.tree.selection_set("0")
    app._on_select()
    assert pump(root, lambda: isinstance(app.preview, tuple), timeout=20)
    assert app.lbl_res.cget("text").endswith(i18n.t("lbl_result_small", size="X").split("X")[1])
    app.mode_chips.pick(shrink.TARGET)
    app.option_chips.pick(gui.CUSTOM)
    pump(root, timeout=0.2)
    app.v_custom.set("1")
    app._on_custom()
    assert app.lbl_custom_err.cget("text") == i18n.t("err_custom_target", lo=shrink.TARGET_MIN_KB,
                                                     hi=shrink.TARGET_MAX_KB)


@pytest.mark.parametrize("lang", NEW)
def test_feedback_failure_message(root, make_app, monkeypatch, lang):
    i18n.set_lang(lang, persist=False)
    shown_boxes = []
    monkeypatch.setattr(gui.webbrowser, "open", lambda url, *a, **k: False)
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda *a, **k: shown_boxes.append(a))
    app = make_app()
    app.send_feedback()
    url = uc.feedback_url(uc.SLUG, APP_VERSION, lang)
    assert shown_boxes == [(i18n.t("app_title"), i18n.t("err_feedback_open", url=url))]
    assert "/en/tools/photoresize" in shown_boxes[0][1]


@pytest.mark.parametrize("lang", NEW)
def test_update_notice_in_the_new_languages(root, make_app, monkeypatch, lang):
    opened = []
    monkeypatch.setattr(gui.webbrowser, "open", lambda url, *a, **k: opened.append(url) or True)
    i18n.set_lang(lang, persist=False)
    app = make_app()
    info = uc.UpdateInfo("0.2.0", APP_VERSION, uc.SITE + "tools/photoresize", uc.SITE + "en/tools/photoresize")
    app._on_update_result(info, True)
    pump(root, timeout=0.2)
    texts = shown(app)
    assert i18n.t("update_available", latest="0.2.0", current=APP_VERSION) in texts
    assert i18n.t("btn_update") in texts and i18n.t("btn_later") in texts
    buttons = [w for w in app.update_area.winfo_children()[0].winfo_children() if w.winfo_class() == "TButton"]
    next(b for b in buttons if b.cget("text") == i18n.t("btn_update")).invoke()
    assert opened == [uc.SITE + "en/tools/photoresize"]


# ------------------------------------------------------------------ f. same results in every language
def test_results_are_the_same_bytes_in_every_language(capsys, tmp_path):
    src = tmp_path / "src"
    ms.make_all(str(src))
    sums = {}
    for lang in ALL:
        work = tmp_path / lang
        shutil.copytree(src, work)
        assert main.main([str(work), "--target", "300KB", "--lang", lang]) == 0
        capsys.readouterr()
        made = files_under(work / "_small")
        sums[lang] = {p: (sha1(work / "_small" / p), os.stat(work / "_small" / p).st_mtime_ns) for p in made}
    assert sums["ko"] and all(sums[lang] == sums["ko"] for lang in ALL)


@pytest.mark.parametrize("lang", ALL)
def test_feedback_and_update_addresses_by_language(root, make_app, monkeypatch, lang):
    opened = []
    monkeypatch.setattr(gui.webbrowser, "open", lambda url, *a, **k: opened.append(url) or True)
    i18n.set_lang(lang, persist=False)
    app = make_app()
    app.send_feedback()
    prefix = "" if lang == "ko" else "en/"
    assert opened == [f"{uc.SITE}{prefix}tools/photoresize?utm_source=app&utm_medium=feedback&v={APP_VERSION}"
                      "#feedback"]
    info = uc.UpdateInfo("0.2.0", APP_VERSION, uc.SITE + "tools/photoresize", uc.SITE + "en/tools/photoresize")
    assert uc.page_url(info, lang) == uc.SITE + prefix + "tools/photoresize"


# ------------------------------------------------------------------ g. odd settings, missing files
@pytest.mark.parametrize("value", ["fr", "JA", "zh", "zh_CN", "zh-TW", "", None, 3, True, ["ja"], {"ja": 1}])
def test_odd_language_in_settings_gives_the_os_language(isolated_settings, monkeypatch, value):
    monkeypatch.setattr(i18n, "detect_os_lang", lambda: "en")
    with open(isolated_settings, "w", encoding="utf-8") as f:
        json.dump({"lang": value, "mode": "size"}, f)
    assert i18n.init() == "en" and i18n.current_lang() == "en"
    assert prefs_mod.load().mode == "size"  # the rest of the file still counts


def test_a_broken_settings_file_gives_the_os_language(isolated_settings, monkeypatch):
    monkeypatch.setattr(i18n, "detect_os_lang", lambda: "ja")
    with open(isolated_settings, "w", encoding="utf-8") as f:
        f.write('{"lang": "zh-CN"')  # cut short
    assert i18n.init() == "ja"


class FakeKernel:
    def __init__(self, lcid):
        self.lcid = lcid

    def GetUserDefaultUILanguage(self):  # noqa: N802  (the Windows name)
        return self.lcid


@pytest.mark.skipif(not hasattr(ctypes, "windll"), reason="Windows only")
@pytest.mark.parametrize("lcid, lang", [(0x0411, "ja"), (0x0804, "zh-CN"), (0x1004, "zh-CN"), (0x0412, "ko"),
                                        (0x0409, "en"), (0x0809, "en"), (0x040C, "en"), (0x0407, "en")])
def test_first_start_follows_the_windows_language(monkeypatch, lcid, lang):
    """A Windows language the program has no file for falls to the locale, then English."""
    monkeypatch.setattr(ctypes, "windll", type("W", (), {"kernel32": FakeKernel(lcid)})())
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(i18n.locale, "getlocale", lambda *a: ("French_France", "1252"))
    assert i18n.detect_os_lang() == lang


@pytest.mark.parametrize("env, lang", [("ja_JP.UTF-8", "ja"), ("zh_CN.UTF-8", "zh-CN"), ("Japanese_Japan", "ja"),
                                       ("Chinese (Simplified)_China", "zh-CN"), ("fr_FR", "en")])
def test_the_locale_fallback_knows_both(monkeypatch, env, lang):
    monkeypatch.setattr(i18n.sys, "platform", "linux")
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANG", env)
    assert i18n.detect_os_lang() == lang


def test_first_start_with_no_settings_uses_the_os_language(isolated_settings, monkeypatch):
    monkeypatch.setattr(ctypes, "windll", type("W", (), {"kernel32": FakeKernel(0x0411)})(), raising=False)
    monkeypatch.setattr(i18n.sys, "platform", "win32")
    assert not os.path.exists(isolated_settings)
    assert i18n.init() == "ja" and i18n.t("btn_run") == load("ja")["btn_run"]


@pytest.fixture
def resources(tmp_path, monkeypatch):
    """A copy of lang/ the test may break; LANGS is read again from it."""
    res = tmp_path / "res"
    shutil.copytree(os.path.join(ROOT, "lang"), res / "lang")
    shutil.copytree(os.path.join(ROOT, "assets"), res / "assets")
    monkeypatch.setattr(i18n, "resource_dir", lambda: str(res))

    def reload():
        monkeypatch.setattr(i18n, "LANGS", i18n.available_langs())
        return i18n.LANGS

    return res, reload


@pytest.mark.parametrize("gone", NEW)
def test_a_missing_language_file_drops_that_language(resources, isolated_settings, monkeypatch, gone):
    res, reload = resources
    (res / "lang" / f"{gone}.json").unlink()
    assert gone not in reload() and len(i18n.LANGS) == 3
    monkeypatch.setattr(i18n, "detect_os_lang", lambda: "en")
    with open(isolated_settings, "w", encoding="utf-8") as f:
        json.dump({"lang": gone}, f)
    assert i18n.init() == "en" and i18n.t("btn_run") == load("en")["btn_run"]
    i18n.set_lang(gone, persist=False)
    assert i18n.current_lang() == "en"


def test_the_os_language_without_its_file_gives_english(resources, monkeypatch):
    res, reload = resources
    (res / "lang" / "ja.json").unlink()
    reload()
    monkeypatch.setattr(ctypes, "windll", type("W", (), {"kernel32": FakeKernel(0x0411)})(), raising=False)
    monkeypatch.setattr(i18n.sys, "platform", "win32")
    assert i18n.detect_os_lang() == "en"


@pytest.mark.parametrize("content", ["{broken", "", "[1, 2]", '"text"', "null"])
def test_a_broken_language_file_shows_english_not_keys(resources, content):
    res, reload = resources
    (res / "lang" / "ja.json").write_text(content, encoding="utf-8")
    reload()
    i18n.set_lang("ja", persist=False)
    assert i18n.t("btn_run") == load("en")["btn_run"]
    assert i18n.t("lbl_count", count=3) == load("en")["lbl_count"].format(count=3)


def test_a_language_file_missing_some_keys_fills_them_in_english(resources):
    res, reload = resources
    data = load("zh-CN")
    del data["btn_run"], data["status_done"]
    (res / "lang" / "zh-CN.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    reload()
    i18n.set_lang("zh-CN", persist=False)
    assert i18n.t("btn_run") == load("en")["btn_run"] and i18n.t("btn_clear") == load("zh-CN")["btn_clear"]


def test_the_window_opens_with_a_missing_language_file(root, make_app, resources, monkeypatch):
    res, reload = resources
    (res / "lang" / "zh-CN.json").unlink()
    reload()
    i18n.set_lang("zh-CN", persist=False)
    app = make_app()
    assert i18n.LANG_NAMES["zh-CN"] not in app.cb_lang.cget("values")
    assert app.root.title().startswith(load("en")["app_title"])
    switch(app, "ja")
    assert app.root.title().startswith(load("ja")["app_title"])
