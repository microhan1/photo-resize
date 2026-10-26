"""The list's columns (v0.1.2): at the smallest and the default window, at 100 % and 150 %,
in all four languages, every heading fits and the status column ends inside the list (v0.1.0
and v0.1.1 pushed it off the right edge at the smallest window). A long name or status is
shortened inside its own column with an ellipsis and shown whole in a tip; the room left
over goes to the name; resizing, switching languages and 0 / 1 / 500 rows keep it so."""
from __future__ import annotations

import os
import time
import tkinter.font as tkfont
from tkinter import ttk
from types import SimpleNamespace

import pytest

import gui
import i18n
import shrink
import theme
from test_gui import make_app, pump, root  # noqa: F401  (fixtures)
from test_lang_ja_zh import load, switch

ALL = ("ko", "en", "zh-CN", "ja")
SIZES = {"min": theme.WINDOW_MIN, "default": theme.WINDOW}
LONG_NAME = ("여름휴가_夏休み_\U0001F3D6️_" * 12 + "sunset_\U0001F305_") * 2
LONG_NAME = (LONG_NAME[:196] + ".jpg")


@pytest.fixture(params=[1.0, 1.5], ids=["100", "150"])
def scale(request, root):
    """The window as a 100 % (96 dpi) or 150 % screen draws it, on whatever screen runs the tests."""
    before_tk, before_scale = root.tk.call("tk", "scaling"), theme.SCALE
    root.tk.call("tk", "scaling", 96 * request.param / 72)
    theme.SCALE = request.param
    yield request.param
    root.tk.call("tk", "scaling", before_tk)
    theme.SCALE = before_scale


def usual_rows(app, base, n=7, name=None):
    """n rows with every usual status (made, over, nothing made, already small, cancelled, an
    expected size, an expected miss) without touching a photo."""
    app.items = [shrink.Item(src=os.path.join(base, name or f"IMG_{i:04d}.jpg"), base=base, size=3_456_789)
                 for i in range(n)]
    big, out = (4032, 3024), (2016, 1512)
    made = dict(src="x", dst="y", in_size=3_456_789, out_size=480_123, in_pixels=big, out_pixels=out)
    kinds = [shrink.Result(status=shrink.DONE, quality=shrink.MAX_QUALITY, **made),
             shrink.Result(status=shrink.OVER, **made),
             shrink.Result(src="x", status=shrink.OVER, in_size=3_456_789, in_pixels=big),
             shrink.Result(src="x", status=shrink.SMALL, in_size=3_456_789, in_pixels=big),
             shrink.Result(src="x", status=shrink.CANCELLED, in_size=3_456_789, in_pixels=big)]
    guesses = [shrink.Result(status=shrink.DONE, quality=shrink.MAX_QUALITY, **made),
               shrink.Result(status=shrink.OVER, **dict(made, out_size=900_000))]
    app.results, app.measured = {}, {}
    for i in range(n):
        if i % 7 < 5:
            app.results[i] = kinds[i % 7]
        else:
            app.measured[i] = guesses[i % 7 - 5]
    app._fill_table()
    pump(app.root.master, timeout=0.3)


def column_problems(app):
    """Where Tk really puts the columns: they fill the list exactly (no gap, nothing past the
    right edge), no heading is cut, and the status column's cells end inside the list."""
    tree = app.tree
    inset = app._tree_inset()
    inner = tree.winfo_width() - 2 * inset
    widths = {c: int(tree.column(c, "width")) for c in gui.COLUMN_NAMES}
    problems = []
    if sum(widths.values()) != inner:
        problems.append(("columns != list", sum(widths.values()), inner))
    bold = tkfont.Font(root=app.root, font=app.f_bold)
    for c in gui.COLUMN_NAMES:
        if bold.measure(tree.heading(c, "text")) + gui.px(8) > widths[c]:
            problems.append(("heading cut", c, tree.heading(c, "text")))
    left = inset + sum(widths[c] for c in gui.COLUMN_NAMES[:-1])
    y = gui.px(12)
    if tree.identify_region(left + widths["status"] // 2, y) != "heading" or \
            tree.identify_column(left + widths["status"] // 2) != f"#{len(widths)}":
        problems.append(("status heading not where it should be",))
    rows = tree.get_children()
    if rows:
        tree.see(rows[0])
        app.root.update()
        box = tree.bbox(rows[0], "status")
        if not box or box[0] + box[2] > inset + inner or box[0] < inset:
            problems.append(("status cell outside", box, inset + inner))
    cell_font = ttk.Style(app.root).lookup("Treeview", "font")  # what the cells are drawn with
    for iid in rows[:50]:
        for c in gui.COLUMN_NAMES:
            shown = tree.set(iid, c)
            if shown and int(app.root.tk.call("font", "measure", cell_font, shown)) > widths[c] - gui.px(gui.CELL_PAD):
                problems.append(("cell wider than its column", iid, c))
    return problems


def statuses_whole(app):
    return [(iid, app.tree.set(iid, "status")) for iid in app.tree.get_children()
            if app.cell_tip(iid, "status")]


# ------------------------------------------------------------------ a. sizes x languages x scaling
@pytest.mark.parametrize("size", SIZES.values(), ids=SIZES.keys())
@pytest.mark.parametrize("lang", ALL)
def test_every_column_shows(root, make_app, tmp_path, scale, lang, size):
    i18n.set_lang(lang, persist=False)
    app = make_app(size=size)
    usual_rows(app, str(tmp_path))
    assert column_problems(app) == []
    assert statuses_whole(app) == []  # the usual statuses are never shortened
    assert [app.cell_tip(i, "name") for i in app.tree.get_children()] == [""] * 7
    assert [app.tree.heading(c, "text") for c in gui.COLUMN_NAMES] == [i18n.t(f"col_{c}") for c in gui.COLUMN_NAMES]
    # the name has at least its share and the short columns their usual values
    w = {c: int(app.tree.column(c, "width")) for c in gui.COLUMN_NAMES}
    assert w["name"] >= int(sum(w.values()) * gui.NAME_SHARE)
    assert app.tree.set("0", "pixels") == gui.pixels_text((2016, 1512))


# ------------------------------------------------------------------ b. long values
def longest_error(lang):
    """The longest text of the language's file, made up to the 300 characters an error keeps."""
    text = max(load(lang).values(), key=len).replace("\n", " ")
    return (text * 3)[:300]


@pytest.mark.parametrize("size", SIZES.values(), ids=SIZES.keys())
@pytest.mark.parametrize("lang", ALL)
def test_long_name_and_long_error_stay_in_their_columns(root, make_app, tmp_path, scale, lang, size):
    i18n.set_lang(lang, persist=False)
    app = make_app(size=size)
    usual_rows(app, str(tmp_path), n=3, name=LONG_NAME)
    error = longest_error(lang)
    app.results[0] = shrink.Result(src="x", status=shrink.FAILED, in_size=10, error=error)
    app._fill_table()
    pump(root, timeout=0.3)
    assert len(LONG_NAME) == 200
    assert column_problems(app) == []
    name, status = app.tree.set("0", "name"), app.tree.set("0", "status")
    # the name keeps its start and its ending; the status keeps its mark and its first words
    assert gui.ELLIPSIS in name and name.endswith(".jpg") and name.startswith(LONG_NAME[:3])
    assert status.startswith(f"{gui.CROSS} {i18n.t('st_failed', error='').strip()}") and status.endswith(gui.ELLIPSIS)
    # shown whole in the tip
    assert app.cell_tip("0", "name") == LONG_NAME
    assert app.cell_tip("0", "status") == f"{gui.CROSS} {i18n.t('st_failed', error=error)}"
    assert app.cell_tip("1", "status") == ""  # a status that fits has no tip


def hover(app, iid, column):
    x, y, w, h = app.tree.bbox(iid, column)
    ev = SimpleNamespace(x=x + w // 2, y=y + h // 2, x_root=app.tree.winfo_rootx() + x + w // 2,
                         y_root=app.tree.winfo_rooty() + y + h // 2)
    app._on_tree_motion(ev)
    app.root.update()


def tip_text(app):
    if app.tip is None or not app.tip.winfo_exists() or not app.tip.winfo_viewable():
        return ""
    return app.tip.winfo_children()[0].cget("text")


@pytest.mark.parametrize("lang", ALL)
def test_the_tip_shows_the_whole_text_and_goes_away(root, make_app, tmp_path, lang):
    i18n.set_lang(lang, persist=False)
    app = make_app(size=theme.WINDOW_MIN)
    usual_rows(app, str(tmp_path), n=3, name=LONG_NAME)
    app.items[1] = shrink.Item(src=os.path.join(str(tmp_path), "a.jpg"), base=str(tmp_path), size=10)
    app._fill_table()
    pump(root, timeout=0.3)
    hover(app, "0", "name")
    assert tip_text(app) == LONG_NAME
    hover(app, "1", "name")  # a short name: no tip
    assert tip_text(app) == ""
    hover(app, "0", "name")
    app._show_tip("")  # what <Leave> does
    assert tip_text(app) == ""
    hover(app, "0", "name")
    switch(app, "en" if lang != "en" else "ko")  # a rebuild hides it too
    assert tip_text(app) == ""


@pytest.mark.parametrize("text, width", [("", 50), ("a", 1), ("abc", 1000), ("x" * 500, 40)])
@pytest.mark.parametrize("middle", [False, True])
def test_fit_never_goes_over_the_width(root, make_app, text, width, middle):
    app = make_app()
    out = app._fit(text, width, middle=middle)
    if app._measure(text, app.f_body) <= width:
        assert out == text
    else:
        assert gui.ELLIPSIS in out and len(out) <= len(text)
        assert app._measure(out, app.f_body) <= width or out == gui.ELLIPSIS


# ------------------------------------------------------------------ c. resizing
def set_size(app, size=None, zoomed=False):
    top = app.root
    if zoomed:
        top.state("zoomed")
    else:
        top.state("normal")
        top.geometry(f"{gui.px(size[0])}x{gui.px(size[1])}")
    pump(top.master, timeout=0.4)


@pytest.mark.parametrize("lang", ALL)
def test_min_default_maximized_min(root, make_app, tmp_path, lang):
    i18n.set_lang(lang, persist=False)
    app = make_app(size=theme.WINDOW_MIN)
    usual_rows(app, str(tmp_path), n=7, name=LONG_NAME)
    seen = []
    for step in ("min", "default", "zoomed", "min"):
        set_size(app, SIZES.get(step), zoomed=step == "zoomed")
        assert column_problems(app) == [], step
        assert statuses_whole(app) == [], step
        w = {c: int(app.tree.column(c, "width")) for c in gui.COLUMN_NAMES}
        seen.append((app.tree.winfo_width(), w, app.tree.set("0", "name")))
    (w0, c0, n0), (w1, c1, n1), (w2, c2, n2), (w3, c3, n3) = seen
    assert w0 < w1 < w2 and w3 == w0
    # everything a wider list gains goes to the name; the other columns keep their widths
    for a, b in ((c0, c1), (c1, c2)):
        assert {c: b[c] for c in gui.COLUMN_NAMES if c != "name"} == {c: a[c] for c in gui.COLUMN_NAMES if c != "name"}
    assert c1["name"] - c0["name"] == w1 - w0 and c2["name"] - c1["name"] == w2 - w1
    # and the name shows more of itself, then the same again at the smallest size
    assert len(n0) < len(n1) < len(n2) and (c3, n3) == (c0, n0)


def test_dragging_through_many_sizes_never_overlaps(root, make_app, tmp_path):
    app = make_app(size=theme.WINDOW_MIN)
    usual_rows(app, str(tmp_path), n=7, name=LONG_NAME)
    for w in range(theme.WINDOW_MIN[0], theme.WINDOW[0] + 1, 37):
        app.root.geometry(f"{gui.px(w)}x{gui.px(theme.WINDOW_MIN[1])}")
        app.root.update()
        widths = [int(app.tree.column(c, "width")) for c in gui.COLUMN_NAMES]
        assert sum(widths) == app.tree.winfo_width() - 2 * app._tree_inset(), w
    pump(root, timeout=0.3)
    assert column_problems(app) == []


# ------------------------------------------------------------------ d. switching languages
def test_switching_languages_at_the_smallest_window(root, make_app, tmp_path, scale):
    app = make_app(size=theme.WINDOW_MIN)
    usual_rows(app, str(tmp_path), n=7, name=LONG_NAME)
    for lang in ("ko", "ja", "zh-CN", "en", "ko"):
        switch(app, lang)
        pump(root, timeout=0.3)
        assert column_problems(app) == [], lang
        assert statuses_whole(app) == [], lang
        assert app.tree.heading("status", "text") == i18n.t("col_status")
        assert app.cell_tip("0", "name") == LONG_NAME
        assert app.tree.set("0", "status").startswith(gui.CHECK)


# ------------------------------------------------------------------ e. 0, 1 and 500 rows
@pytest.mark.parametrize("n", [0, 1, 500])
def test_row_counts(root, make_app, tmp_path, n):
    app = make_app(size=theme.WINDOW_MIN)
    start = time.perf_counter()
    usual_rows(app, str(tmp_path), n=n, name=LONG_NAME if n == 500 else None)
    took = time.perf_counter() - start
    assert len(app.tree.get_children()) == n
    assert column_problems(app) == []
    if n == 0:
        assert app.drop.winfo_ismapped()
        return
    assert not app.drop.winfo_ismapped()
    assert statuses_whole(app) == []
    last = str(n - 1)
    app.tree.yview_moveto(1.0)
    app.root.update()
    assert app.tree.bbox(last, "status")  # the last row scrolls into view, status and all
    assert app.tree.yview()[1] == 1.0 and (n == 1 or app.tree.yview()[0] > 0)
    if n == 500:
        assert took < 10, took
        assert app.tree.set(last, "name").endswith(".jpg") and gui.ELLIPSIS in app.tree.set(last, "name")
        before = app.tree.set(last, "name")
        set_size(app, theme.WINDOW)  # a resize refits all 500
        assert len(app.tree.set(last, "name")) > len(before) and column_problems(app) == []
        assert app.tree.set(last, "name") == app._fit_values(app.full_rows[last])[0]


def test_a_row_updated_while_running_is_fitted_too(root, make_app, tmp_path):
    app = make_app(size=theme.WINDOW_MIN)
    usual_rows(app, str(tmp_path), n=3, name=LONG_NAME)
    app.results[2] = shrink.Result(src="x", status=shrink.FAILED, in_size=10, error="E" * 300)
    app._update_row(2)
    assert app.tree.set("2", "status").endswith(gui.ELLIPSIS)
    assert app.cell_tip("2", "status").endswith("E" * 300)
    assert column_problems(app) == []
