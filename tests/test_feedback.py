"""[Send feedback]: the address it builds, the link in the window, what happens when no
browser opens. webbrowser.open is always faked and the network is blocked by conftest -
these tests never open a browser or reach the server."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tkinter as tk
import urllib.parse
import webbrowser

import pytest

import conftest
import gui
import i18n
import prefs as prefs_mod
import update_check as uc
from conftest import ROOT
from test_gui import make_app, pump, root  # noqa: F401  (fixtures)
from version import APP_VERSION

SLUG = "photoresize"
KO = "https://chaekgalpi.co.kr/tools/photoresize?utm_source=app&utm_medium=feedback&v=0.2.1#feedback"
EN = "https://chaekgalpi.co.kr/en/tools/photoresize?utm_source=app&utm_medium=feedback&v=0.2.1#feedback"


def parts(url):
    """scheme, host, path, the query as a dict (blank values kept), fragment."""
    s = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(s.query, keep_blank_values=True, strict_parsing=True)
    return s.scheme, s.netloc, s.path, {k: v[0] for k, v in query.items()}, s.fragment


# ------------------------------------------------------------------ a. the address
@pytest.mark.parametrize("lang, expected", [("ko", KO), ("en", EN), ("ja", EN), ("zh-CN", EN)])
def test_the_four_languages(lang, expected):
    assert uc.feedback_url(SLUG, "0.2.1", lang) == expected


@pytest.mark.parametrize("lang", [None, "", "xx", "fr", "zh-TW", "zh", "  ", "kor", "e n"])
def test_unknown_language_gets_the_korean_page(lang):
    assert uc.feedback_url(SLUG, "0.2.1", lang) == KO


@pytest.mark.parametrize("lang", ["EN", "En", "JA", "zh-cn", "ZH-CN", "zh_CN", " en "])
def test_language_codes_in_any_case(lang):
    assert uc.feedback_url(SLUG, "0.2.1", lang) == EN


@pytest.mark.parametrize("lang", ["KO", "Ko", " ko"])
def test_korean_in_any_case(lang):
    assert uc.feedback_url(SLUG, "0.2.1", lang) == KO


@pytest.mark.parametrize("lang", [None, "ko", "en", "ja", "zh-CN", "xx"])
@pytest.mark.parametrize("version", [APP_VERSION, "", None])
def test_shape_of_every_address(lang, version):
    url = uc.feedback_url(SLUG, version, lang)
    assert url.startswith("https://chaekgalpi.co.kr/") and url.startswith(uc.SITE)
    assert url.endswith("#feedback") and url.count("#") == 1
    scheme, host, path, query, fragment = parts(url)
    assert (scheme, host, fragment) == ("https", "chaekgalpi.co.kr", "feedback")
    assert path in ("/tools/photoresize", "/en/tools/photoresize")
    assert query["utm_source"] == "app" and query["utm_medium"] == "feedback"
    assert set(query) <= {"utm_source", "utm_medium", "v"}


def test_this_programs_slug_and_version():
    url = uc.feedback_url(uc.SLUG, APP_VERSION, "ko")
    assert uc.SLUG == SLUG and "/tools/photoresize?" in url and parts(url)[3]["v"] == APP_VERSION


# ------------------------------------------------------------------ b. the version
@pytest.mark.parametrize("version", ["0.2.1", "v0.2.1", "1.0.0-beta+3", "1.0 beta", "a&b=c", "x#y", "q?r",
                                     "50%", "a/b", "버전 1.0", "{v}", " 0.2.1 ", "éè", "1\t2"])
def test_odd_versions_are_encoded_and_read_back(version):
    url = uc.feedback_url(SLUG, version, "en")
    scheme, host, path, query, fragment = parts(url)
    assert query["v"] == version  # exactly what was given, nothing lost or added
    assert fragment == "feedback" and path == "/en/tools/photoresize"
    assert query["utm_source"] == "app" and query["utm_medium"] == "feedback"
    assert all(c.isascii() and not c.isspace() for c in url)  # nothing left unencoded


def test_plain_versions_stay_readable():
    assert uc.feedback_url(SLUG, "v0.2.1", "ko").endswith("&v=v0.2.1#feedback")
    assert "&v=1.0.0-beta%2B3#" in uc.feedback_url(SLUG, "1.0.0-beta+3", "ko")


@pytest.mark.parametrize("version", ["", None, " ", "\t"])
def test_empty_version_leaves_v_out(version):
    url = uc.feedback_url(SLUG, version, "ko")
    assert url == "https://chaekgalpi.co.kr/tools/photoresize?utm_source=app&utm_medium=feedback#feedback"
    assert "v" not in parts(url)[3]


def test_nothing_is_sent_while_building_the_address():
    for lang in ("ko", "en", "ja", "zh-CN"):
        uc.feedback_url(SLUG, APP_VERSION, lang)
    assert conftest.attempts == []


# ------------------------------------------------------------------ c. the link in the window
@pytest.fixture
def browser(monkeypatch):
    """A fake webbrowser.open: records the address and answers `result` (or raises it)."""
    class Fake:
        calls: list = []
        result: object = True

        def __call__(self, url, *a, **k):
            self.calls.append(url)
            if isinstance(self.result, BaseException):
                raise self.result
            return self.result

    fake = Fake()
    fake.calls = []
    monkeypatch.setattr(gui.webbrowser, "open", fake)
    return fake


@pytest.fixture
def boxes(monkeypatch):
    """Message boxes are recorded, never shown."""
    shown = []
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda *a, **k: shown.append((a, k)))
    return shown


def test_link_sits_next_to_update_check(root, make_app):
    app = make_app()
    assert app.lnk_feedback.winfo_parent() == app.chk_update.winfo_parent()
    assert app.lnk_feedback.winfo_ismapped() and app.lnk_feedback.cget("text") == "Send feedback"
    assert str(app.lnk_feedback.cget("cursor")) == "hand2"


def test_click_opens_the_page_once(root, make_app, browser, boxes):
    app = make_app()
    app.send_feedback()
    assert browser.calls == [uc.feedback_url(SLUG, APP_VERSION, "en")]
    assert browser.calls[0].startswith("https://chaekgalpi.co.kr/en/tools/photoresize?") and not boxes


def test_the_click_binding_is_wired(root, make_app, browser, boxes):
    """A Tk event on the label itself (generated inside Tk, not a fake mouse message)."""
    app = make_app()
    pump(root, timeout=0.2)
    app.lnk_feedback.event_generate("<Button-1>", x=2, y=2)
    pump(root, timeout=0.1)
    assert browser.calls == [uc.feedback_url(SLUG, APP_VERSION, "en")] and not boxes


def test_two_clicks_open_twice_with_the_same_address(root, make_app, browser, boxes):
    app = make_app()
    app.send_feedback()
    app.send_feedback()
    assert len(browser.calls) == 2 and browser.calls[0] == browser.calls[1]


def test_switching_language_changes_the_next_address_and_the_text(root, make_app, browser, boxes):
    app = make_app()
    app.send_feedback()
    app.v_lang.set(i18n.LANG_NAMES["ko"])
    app._on_lang()
    assert app.lnk_feedback.cget("text") == "의견 보내기"
    app.send_feedback()
    app.v_lang.set(i18n.LANG_NAMES["en"])
    app._on_lang()
    assert app.lnk_feedback.cget("text") == "Send feedback"
    app.send_feedback()
    assert browser.calls == [uc.feedback_url(SLUG, APP_VERSION, "en"), uc.feedback_url(SLUG, APP_VERSION, "ko"),
                             uc.feedback_url(SLUG, APP_VERSION, "en")]
    assert "/en/" not in browser.calls[1] and "/en/" in browser.calls[2]


def test_japanese_and_chinese_files_get_the_english_page(root, make_app, tmp_path, monkeypatch, browser, boxes):
    """No ja/zh-CN screen ships yet; added as files (i18n.available_langs), their link
    text shows and the English page opens."""
    res = tmp_path / "res"
    shutil.copytree(os.path.join(ROOT, "lang"), res / "lang")
    shutil.copytree(os.path.join(ROOT, "assets"), res / "assets")
    base = json.load(open(res / "lang" / "en.json", encoding="utf-8"))
    for code, text in (("ja", "ご意見を送る"), ("zh-CN", "发送反馈")):
        json.dump({**base, "btn_feedback": text}, open(res / "lang" / f"{code}.json", "w", encoding="utf-8"),
                  ensure_ascii=False)
    monkeypatch.setattr(i18n, "resource_dir", lambda: str(res))
    monkeypatch.setattr(i18n, "LANGS", i18n.available_langs())
    app = make_app()
    for code, text in (("ja", "ご意見を送る"), ("zh-CN", "发送反馈")):
        app.v_lang.set(i18n.LANG_NAMES[code])
        app._on_lang()
        assert app.lnk_feedback.cget("text") == text
        app.send_feedback()
    assert browser.calls == [EN.replace("0.2.1", APP_VERSION)] * 2


def test_link_works_while_shrinking(root, make_app, browser, boxes):
    """The browser does not touch the photos; the link stays usable during a run."""
    app = make_app()
    app._set_busy(True)
    app.send_feedback()
    app._set_busy(False)
    assert len(browser.calls) == 1


# ------------------------------------------------------------------ d. no browser
def state(app):
    return (app.status, len(app.items), app.running, app.closed, repr(app.prefs), app._update_info,
            app.root.title(), app.lnk_feedback.cget("text"))


@pytest.mark.parametrize("result", [False, None, webbrowser.Error("no runnable browser"),
                                    OSError("[WinError 1155] no app associated"), RuntimeError("odd")])
def test_no_browser_shows_the_address_and_nothing_breaks(root, make_app, browser, boxes, result):
    app = make_app(prefs=prefs_mod.Prefs())
    before = state(app)
    browser.result = result
    app.send_feedback()  # no exception
    url = uc.feedback_url(SLUG, APP_VERSION, "en")
    assert browser.calls == [url] and len(boxes) == 1
    (title, message), kw = boxes[0]
    assert url in message and message.rstrip().endswith(url) and title == "Photo Resize"
    assert kw.get("parent") is app.root
    assert state(app) == before
    browser.result = True
    app.send_feedback()  # works again once a browser is there
    assert len(browser.calls) == 2 and len(boxes) == 1


def test_no_browser_message_in_korean(root, make_app, browser, boxes):
    i18n.set_lang("ko", persist=False)
    app = make_app()
    browser.result = False
    app.send_feedback()
    (title, message), _ = boxes[0]
    assert "브라우저를 열지 못했습니다" in message and uc.feedback_url(SLUG, APP_VERSION, "ko") in message


def test_even_a_failing_message_box_does_not_break(root, make_app, browser, monkeypatch):
    def broken(*a, **k):
        raise tk.TclError("cannot show")

    monkeypatch.setattr(gui.messagebox, "showwarning", broken)
    app = make_app()
    browser.result = False
    app.send_feedback()
    assert not app.closed


# ------------------------------------------------------------------ e. the words
@pytest.mark.parametrize("lang", i18n.LANGS)
def test_feedback_words_in_every_language(lang):
    data = json.load(open(os.path.join(ROOT, "lang", f"{lang}.json"), encoding="utf-8"))
    for key in ("btn_feedback", "err_feedback_open"):
        assert isinstance(data.get(key), str) and data[key].strip(), (lang, key)
    assert "{url}" in data["err_feedback_open"]


def test_the_words_the_hub_asked_for():
    assert json.load(open(os.path.join(ROOT, "lang", "ko.json"), encoding="utf-8"))["btn_feedback"] == "의견 보내기"
    assert json.load(open(os.path.join(ROOT, "lang", "en.json"), encoding="utf-8"))["btn_feedback"] == "Send feedback"


# ------------------------------------------------------------------ f. nothing else changed
def test_update_check_is_scheduled_as_before(root, make_app, monkeypatch, browser, boxes):
    calls = []
    monkeypatch.setattr(gui.update_check, "check_async", lambda *a, **k: calls.append(a) or True)
    app = make_app()
    app.send_feedback()
    assert len(calls) == 1 and calls[0][1:3] == (uc.SLUG, APP_VERSION)


def test_feedback_leaves_the_update_notice_and_switch_alone(root, make_app, browser, boxes):
    info = uc.UpdateInfo("9.9.9", APP_VERSION, uc.SITE + "tools/photoresize")
    app = make_app()
    app._on_update_result(info, True)
    checked = (app.prefs.update_check, app.prefs.update_check_last, app.prefs.update_check_skipped)
    app.send_feedback()
    assert app._update_info is info and app.update_area.winfo_children()
    assert (app.prefs.update_check, app.prefs.update_check_last, app.prefs.update_check_skipped) == checked
    app._update_open()  # [Update] still opens the update page, not the feedback box
    assert browser.calls[-1] == info.url and "#feedback" not in browser.calls[-1]


@pytest.mark.parametrize("args, out", [(["--version"], f"photo-resize {APP_VERSION}"), (["--help"], "--target")])
def test_command_line_help_and_version_unchanged(args, out):
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "main.py"), *args, "--lang", "en"],
                          capture_output=True, text=True, encoding="utf-8", timeout=60,
                          env={**os.environ, "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9"})
    assert proc.returncode == 0 and out in proc.stdout and "feedback" not in proc.stdout.lower()


# ------------------------------------------------------------------ g. no outside calls
def test_the_browser_is_guarded_for_every_test():
    """conftest swaps webbrowser.open for a recorder: a test that forgets to fake it fails."""
    assert webbrowser.open is conftest._no_browser and webbrowser.open_new_tab is conftest._no_browser
    webbrowser.open("https://chaekgalpi.co.kr/")
    assert conftest.attempts == ["browser https://chaekgalpi.co.kr/"]
    conftest.attempts.clear()  # the guard did its job
    del conftest.total_attempts[-1:]


def test_a_whole_feedback_session_reaches_nothing(root, make_app, browser, boxes):
    app = make_app()
    for lang in ("ko", "en", "ko"):
        app.v_lang.set(i18n.LANG_NAMES[lang])
        app._on_lang()
        app.send_feedback()
    browser.result = False
    app.send_feedback()
    browser.result = OSError("x")
    app.send_feedback()
    pump(root, timeout=0.2)
    assert len(browser.calls) == 5 and len(boxes) == 2
    assert conftest.attempts == []  # no urlopen, no socket, no real browser
