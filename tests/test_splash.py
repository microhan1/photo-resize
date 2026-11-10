"""The start-up picture (splash.py, build.bat --splash): closed once the window is drawn, or
at once when no window is coming, and never a reason for an error."""
from __future__ import annotations

import os
import subprocess
import sys
import types

import pytest

import gui
import main
import splash

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def fake_pyi_splash(monkeypatch):
    mod = types.ModuleType("pyi_splash")
    mod.calls = []
    mod.close = lambda: mod.calls.append("close")
    monkeypatch.setitem(sys.modules, "pyi_splash", mod)
    return mod


# ------------------------------------------------------------------ splash.close
def test_close_does_nothing_from_plain_python(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyi_splash", None)  # "import pyi_splash" raises ImportError
    splash.close()


def test_close_closes_the_picture(fake_pyi_splash):
    splash.close()
    assert fake_pyi_splash.calls == ["close"]


def test_close_swallows_a_failing_picture(fake_pyi_splash):
    def boom():
        raise RuntimeError("splash already gone")

    fake_pyi_splash.close = boom
    splash.close()  # no exception


# ------------------------------------------------------------------ gui.launch
class _Root:
    def __init__(self, log):
        self.log = log

    def update(self):
        self.log.append("update")

    def mainloop(self):
        self.log.append("mainloop")


def _fake_launch(monkeypatch, log, app=None):
    monkeypatch.setattr(gui, "make_root", lambda: _Root(log))
    monkeypatch.setattr(gui, "App", app or (lambda root, paths=None: log.append(("app", paths))))
    monkeypatch.setattr(splash, "close", lambda: log.append("close"))


def test_launch_closes_the_picture_after_the_window_is_drawn(monkeypatch):
    log = []
    _fake_launch(monkeypatch, log)
    gui.launch(["a.jpg"])
    assert log == [("app", ["a.jpg"]), "update", "close", "mainloop"]


def test_launch_closes_the_picture_when_the_window_fails(monkeypatch):
    log = []

    def broken(root, paths=None):
        raise RuntimeError("no window")

    _fake_launch(monkeypatch, log, app=broken)
    with pytest.raises(RuntimeError):
        gui.launch(None)
    assert "close" in log and "mainloop" not in log  # the error is not hidden behind the picture


# ------------------------------------------------------------------ main (CLI)
def test_cli_closes_the_picture_before_it_prints(monkeypatch, tmp_path):
    log = []
    monkeypatch.setattr(splash, "close", lambda: log.append("close"))
    monkeypatch.setattr(main, "run_cli", lambda args: log.append("cli") or 0)
    assert main.main([str(tmp_path), "--lang", "en"]) == 0
    assert log == ["close", "cli"]


def test_version_closes_the_picture(monkeypatch, capsys):
    log = []
    monkeypatch.setattr(splash, "close", lambda: log.append("close"))
    with pytest.raises(SystemExit):
        main.main(["--version"])
    assert log == ["close"]


def test_gui_branch_leaves_the_picture_to_launch(monkeypatch):
    log = []
    monkeypatch.setattr(splash, "close", lambda: log.append("close"))
    monkeypatch.setattr(gui, "launch", lambda paths=None: log.append(("launch", paths)))
    assert main.main([]) == 0
    assert log == [("launch", None)]  # launch closes it once the window is drawn, not before


# ------------------------------------------------------------------ build
def test_build_script_shows_the_picture():
    bat = open(os.path.join(ROOT, "build.bat"), encoding="utf-8").read()
    assert '--splash "assets\\splash.png"' in bat
    png = os.path.join(ROOT, "assets", "splash.png")
    data = open(png, "rb").read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) < 20_000  # small, so it does not slow the start it is meant to cover


HEAVY = "sorted(m for m in ('PIL', 'pi_heif', 'numpy') if m in sys.modules)"


def test_window_modules_load_no_image_library():
    """The heavy imports are already deferred: importing the GUI and the entry point pulls in
    neither Pillow nor pi-heif, so the window needs no further delaying of imports."""
    code = f"import main, gui, sys; print({HEAVY})"
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"


def test_first_update_loads_no_image_library(tmp_path):
    """The first update() (the window's first drawing, with the start-up picture still up)
    must not pay for Pillow either: the preview's hint is drawn without it."""
    code = (
        "import os, sys\n"
        f"os.environ['PHOTO_RESIZE_SETTINGS'] = {str(tmp_path / 'settings.json')!r}\n"
        "import gui, update_check\n"
        "update_check.check_async.__kwdefaults__ = {**(update_check.check_async.__kwdefaults__ or {}),"
        " 'fetcher': lambda slug, version: None}\n"
        "root = gui.make_root()\n"
        "gui.App(root, None)\n"
        "root.update()\n"
        f"print({HEAVY})\n"
        "root.destroy()\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"
