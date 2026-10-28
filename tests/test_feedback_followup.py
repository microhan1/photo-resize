"""[Send feedback], series follow-up (hub, 2026-10-28): Tab reaches the link and the
focus can be seen, Enter and Space open it, a tooltip says what it does, one language
rule for every page of the tools site, the README links.

Keys are never sent as real key events: Tk delivers a generated key event only while
this program has the keyboard, so a test would have to take it from whatever the user is
typing in. Instead the binding Tk would run is run directly (run_binding) and the Tab
order is read with tk_focusNext / tk_focusPrev. webbrowser.open is faked and the network
blocked by conftest."""
from __future__ import annotations

import json
import os
import re
import urllib.parse

import pytest

import conftest
import gui
import i18n
import theme
import update_check as uc
from conftest import ROOT
from test_feedback import EN, KO, boxes, browser  # noqa: F401  (fixtures)
from test_gui import make_app, pump, root  # noqa: F401  (fixtures)
from version import APP_VERSION

SLUG = "photoresize"
TIPS = {"ko": "안 되는 것·불편한 것·바라는 기능을 알려 주세요(브라우저가 열립니다)",
        "en": "Tell us what's broken or missing (opens your browser)",
        "ja": "不具合・ご要望をお知らせください（ブラウザが開きます）",
        "zh-CN": "告诉我们问题或建议（将打开浏览器）"}
ALL = ("ko", "en", "ja", "zh-CN")


def address(lang):
    return uc.feedback_url(SLUG, APP_VERSION, lang)


# Tk's %-fields for a binding script: what a real event would fill in
FIELDS = {"#": "0", "b": "0", "f": "0", "h": "0", "k": "0", "s": "0", "t": "0", "w": "0", "x": "0", "y": "0",
          "E": "0", "N": "0", "T": "2", "X": "0", "Y": "0", "D": "0"}
KEYS = {"<Return>": ("Return", "\r"), "<KP_Enter>": ("KP_Enter", "\r"), "<space>": ("space", " "),
        "<KeyPress-a>": ("a", "a"), "<Escape>": ("Escape", "\x1b"), "<Up>": ("Up", ""), "<Down>": ("Down", ""),
        "<BackSpace>": ("BackSpace", "\b"), "<Delete>": ("Delete", ""), "<Control-c>": ("c", "\x03"),
        "<F1>": ("F1", ""), "<<NextWindow>>": ("Tab", "\t"), "<<PrevWindow>>": ("Tab", "")}


def run_binding(widget, seq):
    """Run what Tk runs when `seq` reaches `widget`: each bind tag in order (the widget,
    its class, its window, all) until one says break - with no key event at all."""
    keysym, char = KEYS[seq]
    fields = dict(FIELDS, W=str(widget), K=keysym, A=char)
    for tag in widget.bindtags():
        script = widget.tk.call("bind", tag, seq)
        if not script:
            continue
        script = re.sub(r"%(.)", lambda m: "{%s}" % fields.get(m.group(1), m.group(1)) if m.group(1) != "%" else "%",
                        script)
        code = int(widget.tk.call("catch", script))
        if code == 3:  # TCL_BREAK: the later tags do not run
            break
        assert code in (0, 4), (tag, seq, widget.tk.call("set", "errorInfo"))


def focused(app):
    """The widget Tk keeps the focus on in this window (focus_get() is None while another
    program has the keyboard, which says nothing about where Tab moved the focus)."""
    return app.root.focus_lastfor()


def switch(app, lang):
    app.v_lang.set(i18n.LANG_NAMES[lang])
    app._on_lang()


def hover(root, app):
    app.lnk_feedback.event_generate("<Enter>", x=3, y=3)
    assert pump(root, lambda: app.tip_feedback.tip is not None and app.tip_feedback.tip.winfo_viewable(), timeout=5)
    root.update()
    return app.tip_feedback


def rect(w):
    w.update_idletasks()
    return w.winfo_rootx(), w.winfo_rooty(), w.winfo_rootx() + w.winfo_width(), w.winfo_rooty() + w.winfo_height()


def tip_rect(tip):
    t = tip.tip
    t.update()
    return t.winfo_rootx(), t.winfo_rooty(), t.winfo_rootx() + t.winfo_reqwidth(), t.winfo_rooty() + t.winfo_reqheight()


# ================================================================== a. keyboard
def test_the_link_takes_the_focus(root, make_app):
    app = make_app()
    assert str(app.lnk_feedback.cget("takefocus")) in ("1", "True", "true")


def test_tab_order_reaches_the_link_and_back(root, make_app):
    """The header in the order it is seen: [Send feedback] -> [update check] -> [language]."""
    app = make_app()
    root.update()
    assert app.lnk_feedback.tk_focusNext() is app.chk_update
    assert app.chk_update.tk_focusNext() is app.cb_lang
    assert app.cb_lang.tk_focusPrev() is app.chk_update
    assert app.chk_update.tk_focusPrev() is app.lnk_feedback
    before = app.lnk_feedback.tk_focusPrev()
    assert before is not app.lnk_feedback and before.tk_focusNext() is app.lnk_feedback


@pytest.mark.parametrize("lang", ALL)
def test_tab_order_is_the_order_seen(root, make_app, lang):
    """Left to right on the screen is the Tab order, in every language and at the smallest size."""
    i18n.set_lang(lang, persist=False)
    app = make_app(size=theme.WINDOW_MIN)
    root.update()
    seen = sorted((app.lnk_feedback, app.chk_update, app.cb_lang), key=lambda w: w.winfo_rootx())
    assert seen == [app.lnk_feedback, app.chk_update, app.cb_lang]
    assert [app.lnk_feedback.tk_focusNext(), app.chk_update.tk_focusNext()] == [app.chk_update, app.cb_lang]


def test_tab_moves_the_focus_onto_the_link(root, make_app, browser):
    app = make_app()
    before = app.lnk_feedback.tk_focusPrev()
    before.focus_set()
    root.update()
    run_binding(before, "<<NextWindow>>")  # what Tab is bound to
    root.update()
    assert focused(app) is app.lnk_feedback
    assert browser.calls == []  # reaching it opens nothing
    run_binding(app.lnk_feedback, "<<NextWindow>>")
    root.update()
    assert focused(app) is app.chk_update
    run_binding(app.chk_update, "<<NextWindow>>")
    root.update()
    assert focused(app) is app.cb_lang and browser.calls == []


def test_shift_tab_comes_back_to_the_link(root, make_app, browser):
    app = make_app()
    app.cb_lang.focus_set()
    root.update()
    run_binding(app.cb_lang, "<<PrevWindow>>")
    root.update()
    assert focused(app) is app.chk_update
    run_binding(app.chk_update, "<<PrevWindow>>")
    root.update()
    assert focused(app) is app.lnk_feedback
    run_binding(app.lnk_feedback, "<<PrevWindow>>")
    root.update()
    assert focused(app) is app.lnk_feedback.tk_focusPrev() and browser.calls == []


def test_tab_and_shift_tab_are_the_next_and_previous_window_keys(root):
    """Tk binds Tab and Shift+Tab through these two virtual events (run_binding runs them)."""
    assert "<Key-Tab>" in root.event_info("<<NextWindow>>")
    assert "<Shift-Key-Tab>" in root.event_info("<<PrevWindow>>")
    assert "tk_focusNext" in root.bind_class("all", "<<NextWindow>>")
    assert "tk_focusPrev" in root.bind_class("all", "<<PrevWindow>>")


@pytest.mark.parametrize("seq", ["<Return>", "<KP_Enter>", "<space>"])
def test_enter_and_space_open_the_page_exactly_once(root, make_app, browser, boxes, seq):
    app = make_app()
    app.lnk_feedback.focus_set()
    run_binding(app.lnk_feedback, seq)
    root.update()
    assert browser.calls == [address("en")] and not boxes
    run_binding(app.lnk_feedback, seq)  # once more per press
    root.update()
    assert browser.calls == [address("en")] * 2


@pytest.mark.parametrize("seq", ["<Return>", "<space>"])
def test_the_key_stops_at_the_link(root, make_app, browser, seq):
    """The binding says break: the window's own bindings for the key do not run too."""
    app = make_app()
    script = app.lnk_feedback.bind(seq)
    assert "break" in script
    hits = []
    app.root.bind(seq, lambda e: hits.append(1))
    run_binding(app.lnk_feedback, seq)
    assert hits == [] and len(browser.calls) == 1


@pytest.mark.parametrize("lang", ALL)
def test_keyboard_opens_the_page_of_the_screen_language(root, make_app, browser, lang):
    i18n.set_lang(lang, persist=False)
    app = make_app()
    run_binding(app.lnk_feedback, "<Return>")
    run_binding(app.lnk_feedback, "<space>")
    assert browser.calls == [address(lang)] * 2
    assert ("/en/tools/" in browser.calls[0]) == (lang != "ko")


@pytest.mark.parametrize("seq", ["<KeyPress-a>", "<Escape>", "<Up>", "<Down>", "<BackSpace>", "<Delete>",
                                 "<Control-c>", "<F1>"])
def test_other_keys_do_nothing(root, make_app, browser, boxes, seq):
    app = make_app()
    app.lnk_feedback.focus_set()
    root.update()
    before = (app.lnk_feedback.cget("text"), str(app.lnk_feedback.cget("background")), app.status)
    run_binding(app.lnk_feedback, seq)
    root.update()
    assert browser.calls == [] and not boxes
    assert (app.lnk_feedback.cget("text"), str(app.lnk_feedback.cget("background")), app.status) == before


def test_only_enter_and_space_are_bound_on_the_link(root, make_app):
    """Every other key falls through to Tk's usual handling (Tab moves on, the rest nothing)."""
    app = make_app()
    keys = {s for s in app.lnk_feedback.bind() if "Key" in s}
    assert keys == {"<Key-Return>", "<Key-KP_Enter>", "<Key-space>"}
    assert not [s for s in app.root.bind() if "Key" in s]  # the window takes no keys either


def test_tab_from_the_link_opens_nothing(root, make_app, browser):
    app = make_app()
    app.lnk_feedback.focus_set()
    root.update()
    run_binding(app.lnk_feedback, "<<NextWindow>>")
    root.update()
    assert focused(app) is app.lnk_feedback.tk_focusNext() and browser.calls == []


def test_focus_can_be_seen_and_goes_away_without_changing_size(root, make_app):
    app = make_app()
    lnk = app.lnk_feedback
    root.update()
    before = str(lnk.cget("background"))
    size = (lnk.winfo_reqwidth(), lnk.winfo_reqheight(), lnk.winfo_width(), lnk.winfo_height())
    lnk.event_generate("<FocusIn>")
    root.update()
    assert str(lnk.cget("background")) == theme.COLORS["link_focus"] != before
    assert (lnk.winfo_reqwidth(), lnk.winfo_reqheight(), lnk.winfo_width(), lnk.winfo_height()) == size
    lnk.event_generate("<FocusOut>")
    root.update()
    assert str(lnk.cget("background")) == before
    assert (lnk.winfo_reqwidth(), lnk.winfo_reqheight(), lnk.winfo_width(), lnk.winfo_height()) == size


def test_focus_shading_differs_from_the_window(root, make_app):
    """Something a keyboard user can see: not the colour already behind the link."""
    assert theme.COLORS["link_focus"].upper() not in ("#FFFFFF", "#FAFAFA", theme.COLORS["bg"].upper(),
                                                      theme.COLORS["surface"].upper())


@pytest.mark.parametrize("lang", ALL)
def test_focus_shading_keeps_the_size_in_every_language(root, make_app, lang):
    i18n.set_lang(lang, persist=False)
    app = make_app(size=theme.WINDOW_MIN)
    lnk = app.lnk_feedback
    root.update()
    size = (lnk.winfo_reqwidth(), lnk.winfo_reqheight())
    others = [(w, w.winfo_rootx(), w.winfo_width()) for w in (app.chk_update, app.cb_lang)]
    lnk.event_generate("<FocusIn>")
    root.update()
    assert (lnk.winfo_reqwidth(), lnk.winfo_reqheight()) == size
    assert [(w, w.winfo_rootx(), w.winfo_width()) for w, _, _ in others] == others  # nothing moved


def test_the_link_is_still_a_link_after_a_language_change(root, make_app, browser):
    app = make_app()
    switch(app, "ko")
    root.update()
    assert str(app.lnk_feedback.cget("takefocus")) in ("1", "True", "true")
    assert app.lnk_feedback.tk_focusNext() is app.chk_update
    run_binding(app.lnk_feedback, "<Return>")
    assert browser.calls == [address("ko")]


def test_keyboard_works_while_shrinking(root, make_app, browser):
    app = make_app()
    app._set_busy(True)
    run_binding(app.lnk_feedback, "<space>")
    app._set_busy(False)
    assert browser.calls == [address("en")]


# ================================================================== b. tooltip
def test_the_tooltip_words_are_the_agreed_ones():
    for lang in ALL:
        data = json.load(open(os.path.join(ROOT, "lang", f"{lang}.json"), encoding="utf-8"))
        assert data["tip_feedback"] == TIPS[lang]
    assert len(set(TIPS.values())) == 4 and all(v.strip() for v in TIPS.values())


def test_the_delay_is_about_half_a_second():
    assert 400 <= gui.Tooltip.DELAY_MS <= 500


def test_hover_shows_and_leaving_hides(root, make_app):
    app = make_app()
    tip = hover(root, app)
    assert tip.label.cget("text") == TIPS["en"]
    assert tip.tip.wm_overrideredirect()
    app.lnk_feedback.event_generate("<Leave>")
    root.update()
    assert app.tip_feedback.tip is None


def test_nothing_shows_before_the_delay(root, make_app):
    app = make_app()
    app.lnk_feedback.event_generate("<Enter>", x=3, y=3)
    pump(root, timeout=0.15)
    assert app.tip_feedback.tip is None  # not yet
    assert pump(root, lambda: app.tip_feedback.tip is not None, timeout=5)


def test_leaving_before_the_delay_shows_nothing(root, make_app):
    app = make_app()
    app.lnk_feedback.event_generate("<Enter>", x=3, y=3)
    pump(root, timeout=0.1)
    app.lnk_feedback.event_generate("<Leave>")
    pump(root, timeout=gui.Tooltip.DELAY_MS / 1000 + 0.4)
    assert app.tip_feedback.tip is None and app.tip_feedback._job is None


def test_hovering_again_shows_one_note_not_two(root, make_app):
    app = make_app()
    hover(root, app)
    first = app.tip_feedback.tip
    app.lnk_feedback.event_generate("<Enter>", x=4, y=4)  # a second Enter while it is open
    pump(root, timeout=gui.Tooltip.DELAY_MS / 1000 + 0.3)
    assert app.tip_feedback.tip is first
    notes = [w for w in app.lnk_feedback.winfo_children() if w.winfo_class() == "Toplevel"]
    assert len(notes) == 1
    for _ in range(3):
        app.lnk_feedback.event_generate("<Leave>")
        hover(root, app)
    assert len([w for w in app.lnk_feedback.winfo_children() if w.winfo_class() == "Toplevel"]) == 1


def test_click_hides_the_tooltip_and_opens_once(root, make_app, browser, boxes):
    app = make_app()
    hover(root, app)
    app.lnk_feedback.event_generate("<Button-1>", x=3, y=3)
    root.update()
    assert app.tip_feedback.tip is None
    assert browser.calls == [address("en")] and not boxes


def test_click_before_the_delay_cancels_the_note(root, make_app, browser):
    app = make_app()
    app.lnk_feedback.event_generate("<Enter>", x=3, y=3)
    app.lnk_feedback.event_generate("<Button-1>", x=3, y=3)
    pump(root, timeout=gui.Tooltip.DELAY_MS / 1000 + 0.3)
    assert app.tip_feedback.tip is None and len(browser.calls) == 1


@pytest.mark.parametrize("lang", ALL)
def test_tooltip_text_in_every_language(root, make_app, lang):
    i18n.set_lang(lang, persist=False)
    app = make_app()
    assert hover(root, app).label.cget("text") == TIPS[lang]


def test_language_change_changes_an_open_tooltip(root, make_app):
    app = make_app()
    hover(root, app)
    seen = []
    for lang in ("ko", "ja", "zh-CN", "en"):
        switch(app, lang)
        root.update()
        tip = app.tip_feedback
        assert tip.tip is not None and tip.tip.winfo_viewable()
        seen.append(tip.label.cget("text"))
        assert tip.tip.master is app.lnk_feedback  # under the new link, not the old one
    assert seen == [TIPS[c] for c in ("ko", "ja", "zh-CN", "en")]
    assert len([w for w in app.root.winfo_children() if isinstance(w, gui.tk.Toplevel)]) <= 1  # no stale notes


def test_language_change_reaches_the_next_tooltip(root, make_app):
    app = make_app()
    switch(app, "ja")
    assert hover(root, app).label.cget("text") == TIPS["ja"]


def test_tooltip_does_not_take_the_focus(root, make_app):
    app = make_app()
    app.lnk_feedback.focus_set()
    root.update()
    hover(root, app)
    assert focused(app) is app.lnk_feedback
    assert str(app.tip_feedback.tip.cget("takefocus")) in ("", "0")


def place_window(app, where):
    """The window at the minimum size against the left or right edge of the screen, or
    half off the right / left edge."""
    top = app.root
    top.geometry(f"{gui.px(theme.WINDOW_MIN[0])}x{gui.px(theme.WINDOW_MIN[1])}")
    top.update()
    frame = max(0, top.winfo_rootx() - top.winfo_x())
    outer = top.winfo_width() + 2 * frame
    sw = top.winfo_screenwidth()
    x = {"left": 0, "right": sw - outer, "off_right": sw - outer // 2, "off_left": -(outer // 2)}[where]
    top.geometry(f"+{x}+0")
    top.update()
    pump(top, lambda: abs(top.winfo_x() - x) <= 2, timeout=3)
    pump(top, timeout=0.1)


@pytest.mark.parametrize("where", ["left", "right"])
@pytest.mark.parametrize("lang", ALL)
def test_tooltip_fits_the_minimum_window_at_either_screen_edge(root, make_app, lang, where):
    i18n.set_lang(lang, persist=False)
    app = make_app(size=theme.WINDOW_MIN)
    place_window(app, where)
    tip = hover(root, app)
    x0, y0, x1, y1 = tip_rect(tip)
    wx0, wy0, wx1, wy1 = rect(app.root)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    assert wx0 <= x0 and x1 <= wx1 and wy0 <= y0 and y1 <= wy1, ((x0, y0, x1, y1), (wx0, wy0, wx1, wy1))
    assert 0 <= x0 and x1 <= sw and 0 <= y0 and y1 <= sh
    assert y0 >= app.lnk_feedback.winfo_rooty() + app.lnk_feedback.winfo_height()  # under the link
    assert tip.label.cget("text") == TIPS[lang]


@pytest.mark.parametrize("where", ["off_right", "off_left"])
def test_tooltip_stays_on_screen_with_the_window_half_off_it(root, make_app, where):
    app = make_app(size=theme.WINDOW_MIN)
    place_window(app, where)
    tip = hover(root, app)
    x0, _, x1, _ = tip_rect(tip)
    wx0, _, wx1, _ = rect(app.root)
    sw = root.winfo_screenwidth()
    assert max(wx0, 0) <= x0 and x1 <= min(wx1, sw), ((x0, x1), (wx0, wx1, sw))


def test_placement_with_a_note_wider_than_the_window(root, make_app):
    """The rule itself: a note wider than the window starts at the window's left edge."""
    app = make_app(size=theme.WINDOW_MIN)
    tip = hover(root, app)
    tip.label.configure(text="x" * 600, wraplength=0)
    x, _ = tip.place()
    assert x == max(rect(app.root)[0], 0)


def test_closing_with_a_tooltip_open_or_pending_is_clean(root, make_app):
    app = make_app()
    hover(root, app)
    app.on_close()
    assert pump(root, lambda: app.closed, timeout=10)
    app2 = make_app()
    app2.lnk_feedback.event_generate("<Enter>", x=3, y=3)  # pending when the window closes
    app2.on_close()
    assert pump(root, lambda: app2.closed, timeout=10)
    pump(root, timeout=gui.Tooltip.DELAY_MS / 1000 + 0.3)  # the pending show must not fire on a dead window
    assert app2.tip_feedback.tip is None


def test_the_tooltip_holds_no_app(root, make_app):
    app = make_app()
    tip = hover(root, app)
    assert set(vars(tip)) == {"widget", "key", "tip", "label", "_job"}
    assert tip.widget is app.lnk_feedback and tip.key == "tip_feedback"


def test_cell_tips_are_untouched(root, make_app):
    """The list's own note for shortened cells is a different one and still works."""
    app = make_app()
    hover(root, app)
    app._show_tip("whole name.jpg", 100, 100)
    root.update()
    assert app.tip is not None and app.tip.winfo_viewable() and app.tip_feedback.tip is not None
    app._show_tip("")


# ================================================================== c. one language rule
KOREAN = ["ko", "KO", "Ko", " ko ", "ko-KR", "ko_KR", "KO-kr", "ko-Kore-KR"]
OTHERS = ["en", "ja", "zh", "zh-CN", "zh_CN", "zh-TW", "fr", "de", "EN", "en-US", "xx", "kor", "k", "e n", "ja-JP",
          "zh-Hans", "es", "-ko", "123"]


@pytest.mark.parametrize("lang", KOREAN)
def test_korean_codes_get_the_korean_page(lang):
    assert uc.is_korean_page(lang)
    assert uc.feedback_url(SLUG, "0.2.1", lang) == KO


@pytest.mark.parametrize("lang", OTHERS)
def test_every_other_code_gets_the_english_page(lang):
    assert not uc.is_korean_page(lang)
    assert uc.feedback_url(SLUG, "0.2.1", lang) == EN


@pytest.mark.parametrize("lang", [None, "", " ", "\t", "  \n"])
def test_no_language_follows_the_default_screen_language(lang, monkeypatch):
    assert i18n.DEFAULT_LANG == "en"
    assert uc.feedback_url(SLUG, "0.2.1", lang) == EN
    monkeypatch.setattr(uc, "DEFAULT_LANG", "ko")  # a tool whose default screen were Korean
    assert uc.feedback_url(SLUG, "0.2.1", lang) == KO


@pytest.mark.parametrize("lang", [3, 1.5, b"ko", ["ko"], object()])
def test_not_a_string_is_no_language(lang):
    assert uc.feedback_url(SLUG, "0.2.1", lang) == EN


@pytest.mark.parametrize("lang", KOREAN + OTHERS + [None, ""])
def test_every_address_has_the_same_shape(lang):
    url = uc.feedback_url(SLUG, APP_VERSION, lang)
    s = urllib.parse.urlsplit(url)
    assert (s.scheme, s.netloc, s.fragment) == ("https", "chaekgalpi.co.kr", "feedback")
    assert s.path == ("/tools/photoresize" if uc.is_korean_page(lang) else "/en/tools/photoresize")
    assert urllib.parse.parse_qs(s.query) == {"utm_source": ["app"], "utm_medium": ["feedback"], "v": [APP_VERSION]}
    assert url.count("#") == 1 and url.endswith("#feedback")


def test_the_windows_slug_is_not_the_web_one():
    assert uc.SLUG == "photoresize" and "photoresizeweb" not in address("ko") + address("en")


UPDATE = uc.UpdateInfo("9.9.9", APP_VERSION, uc.SITE + "tools/photoresize?utm_source=app&utm_medium=update",
                       uc.SITE + "en/tools/photoresize?utm_source=app&utm_medium=update")


@pytest.mark.parametrize("lang", KOREAN + OTHERS + [None, "", " "])
def test_update_page_follows_the_same_rule(lang):
    expected = UPDATE.url if uc.is_korean_page(lang) else UPDATE.url_en
    assert uc.page_url(UPDATE, lang) == expected
    # the same choice as the feedback address, for every code
    assert ("/en/" in uc.page_url(UPDATE, lang)) == ("/en/" in uc.feedback_url(SLUG, "1", lang))


@pytest.mark.parametrize("lang", OTHERS + [None, ""])
def test_update_page_without_an_english_one_stays_korean(lang):
    info = uc.UpdateInfo("9.9.9", APP_VERSION, UPDATE.url)
    assert uc.page_url(info, lang) == UPDATE.url


@pytest.mark.parametrize("lang", ALL)
def test_update_button_opens_the_page_of_the_screen_language(root, make_app, browser, lang):
    i18n.set_lang(lang, persist=False)
    app = make_app()
    app._on_update_result(UPDATE, True)
    app._update_open()
    assert browser.calls == [UPDATE.url if lang == "ko" else UPDATE.url_en]


# ================================================================== d. README links
README_LANGS = {"README.md": "ko", "README.en.md": "en", "README.ja.md": "ja", "README.zh-CN.md": "zh-CN"}
FULLWIDTH = "（），。、：；！？「」—“”"


def links(text):
    """Every address a Markdown reader turns into a link: [text](url), <url>, and a bare
    one (where autolinking takes everything up to the next space)."""
    out = [m.group(1) for m in re.finditer(r"\]\((https?://[^)\s]+)\)", text)]
    out += [m.group(1) for m in re.finditer(r"<(https?://[^>\s]+)>", text)]
    rest = re.sub(r"\]\(https?://[^)\s]+\)|<https?://[^>\s]+>", "", text)
    bare = re.findall(r"https?://\S+", rest)
    return out, bare


def release_notes():
    folder = os.path.join(ROOT, "docs", "releases")
    return [os.path.join("docs", "releases", n) for n in sorted(os.listdir(folder)) if n == f"v{APP_VERSION}.md"]


@pytest.mark.parametrize("name", list(README_LANGS))
def test_readme_feedback_and_tool_page_links(name):
    text = open(os.path.join(ROOT, name), encoding="utf-8").read()
    found, bare = links(text)
    prefix = "" if README_LANGS[name] == "ko" else "en/"
    feedback = [u for u in found if u.endswith("#feedback")]
    page = [u for u in found if "utm_source=github" in u]
    assert feedback == [f"https://chaekgalpi.co.kr/{prefix}tools/photoresize#feedback"]
    assert page == [f"https://chaekgalpi.co.kr/{prefix}tools/photoresize?utm_source=github&utm_medium=referral"
                    "&utm_campaign=tool_cta&utm_content=photoresize"]
    assert bare == []


@pytest.mark.parametrize("name", list(README_LANGS) + ["@notes"])
def test_no_link_swallows_what_follows_it(name):
    names = release_notes() if name == "@notes" else [name]
    for n in names:
        text = open(os.path.join(ROOT, n), encoding="utf-8").read()
        found, bare = links(text)
        assert bare == [], (n, bare)
        assert found, n
        for url in found:
            assert url.isascii(), (n, url)  # no Hangul, kana, hanzi or full-width mark in an address
            assert url[-1] not in ").,;:!?'\"" + FULLWIDTH, (n, url)
            assert not any(c in url for c in FULLWIDTH), (n, url)


def test_the_chinese_tool_page_link_ends_before_the_dash():
    """README.zh-CN: the link is followed straight by a full-width dash; it is written as
    [text](url), so the address ends at the bracket."""
    text = open(os.path.join(ROOT, "README.zh-CN.md"), encoding="utf-8").read()
    m = re.search(r"\]\((https://chaekgalpi\.co\.kr/en/tools/photoresize\?[^)]*)\)(.)", text)
    assert m and m.group(1).endswith("utm_content=photoresize") and m.group(2) == "—"


def test_the_release_notes_draft_exists():
    assert release_notes() == [os.path.join("docs", "releases", f"v{APP_VERSION}.md")]


# ================================================================== f. nothing reaches anything
def test_a_whole_keyboard_and_tooltip_session_sends_nothing(root, make_app, browser, boxes):
    app = make_app()
    for lang in ("ko", "ja", "zh-CN", "en"):
        switch(app, lang)
        hover(root, app)
        run_binding(app.lnk_feedback, "<Return>")
        run_binding(app.lnk_feedback, "<space>")
        app.lnk_feedback.event_generate("<Leave>")
        app.lnk_feedback.event_generate("<FocusIn>")
        app.lnk_feedback.event_generate("<FocusOut>")
    browser.result = False
    run_binding(app.lnk_feedback, "<Return>")
    pump(root, timeout=0.2)
    assert len(browser.calls) == 9 and len(boxes) == 1
    assert browser.calls[:2] == [address("ko")] * 2 and browser.calls[-1] == address("en")
    assert conftest.attempts == []  # no urlopen, no socket, no real browser
