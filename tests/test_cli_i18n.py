"""Command line, language files and settings.json."""
from __future__ import annotations

import ast
import json
import os
import re

import pytest

import i18n
import main
import make_samples as ms
import prefs as prefs_mod
import shrink
from conftest import ROOT, files_under
from version import APP_VERSION


# ------------------------------------------------------------------ command line
def test_cli_shrinks_a_folder(tmp_path, capsys):
    ms.make_all(str(tmp_path))
    assert main.main([str(tmp_path), "--target", "300KB", "--lang", "en"]) == 0
    out = capsys.readouterr().out
    assert "location removed from" in out
    made = [f for f in files_under(tmp_path) if f.startswith("_small/")]
    assert len(made) >= 6
    for f in made:
        assert os.path.getsize(tmp_path / f) <= 300_000


def test_cli_modes_and_suffix(tmp_path):
    src = ms.jpeg(str(tmp_path / "a.jpg"), 3000, 2000, seed=1)
    assert main.main([src, "--mode", "size", "--size", "1280", "--output", "suffix"]) == 0
    from PIL import Image

    with Image.open(tmp_path / "a_small.jpg") as im:
        assert im.size == (1280, 853)
    assert main.main([src, "--mode", "quality", "--quality", "low"]) == 0
    assert (tmp_path / "_small" / "a.jpg").exists()


def test_cli_exit_codes(tmp_path, capsys):
    assert main.main([str(tmp_path / "missing.jpg"), "--lang", "en"]) == 2
    err = capsys.readouterr().err
    assert "cannot open" in err and "no photos" in err
    (tmp_path / "bad.jpg").write_bytes(b"nope")
    ms.jpeg(str(tmp_path / "good.jpg"), 900, 600, seed=1)
    assert main.main([str(tmp_path), "--lang", "en"]) == 1  # one failure in the batch


def test_cli_version_and_translated_help(capsys):
    with pytest.raises(SystemExit) as e:
        main.main(["--version"])
    assert e.value.code == 0 and APP_VERSION in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main.main(["--lang", "ko", "--help"])
    out = capsys.readouterr().out
    assert out.startswith("사용법:") and "목표 용량" in out and "옵션" in out


def test_cli_bad_values_are_explained(capsys):
    with pytest.raises(SystemExit) as e:
        main.main(["--lang", "ko", "x.jpg", "--target", "big"])
    assert e.value.code == 2
    assert "목표 용량을 읽을 수 없습니다" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main.main(["x.jpg", "--mode", "zip", "--lang", "en"])
    assert "invalid choice" in capsys.readouterr().err


# ------------------------------------------------------------------ language files
def load(lang):
    with open(os.path.join(ROOT, "lang", f"{lang}.json"), encoding="utf-8") as f:
        return json.load(f)


def placeholders(text):
    return sorted(re.findall(r"\{(\w+)\}", text)) + sorted(re.findall(r"%\((\w+)\)", text))


def test_korean_and_english_are_offered():
    assert {"ko", "en"} <= set(i18n.LANGS)


@pytest.mark.parametrize("lang", [lang for lang in i18n.LANGS if lang != "en"])
def test_same_keys_and_placeholders(lang):
    en, other = load("en"), load(lang)
    assert set(en) == set(other)
    for key in en:
        assert placeholders(en[key]) == placeholders(other[key]), key
        assert other[key].strip(), key


def _code_files():
    for name in sorted(os.listdir(ROOT)):
        if name.endswith(".py"):
            yield os.path.join(ROOT, name)


def test_every_key_used_in_the_code_exists_and_none_is_unused():
    en = load("en")
    asked, literals = set(), set()
    for path in _code_files():
        src = open(path, encoding="utf-8").read()
        asked |= set(re.findall(r"""(?<![\w.])(?:t|self\._show_status)\(\s*["']([a-z0-9_]+)["']""", src))
        literals |= set(re.findall(r"""["']([a-z][a-z0-9_]+)["']""", src))
    built = {f"col_{c}" for c in ("name", "before", "after", "pixels", "status")}  # t(f"col_{name}")
    built |= {f"quality_{lv}" for lv in shrink.QUALITY_LEVELS}  # t(f"quality_{lv}")
    assert sorted(asked - set(en)) == []
    assert sorted(set(en) - literals - built) == []


def test_no_hard_coded_screen_text_in_the_code():
    """Only the language names in i18n.py may be non-ASCII string literals (docstrings and
    comments do not count)."""
    import theme

    allowed = set(i18n.LANG_NAMES.values()) | set(theme.MALGUN)  # language names, a font name
    found = []
    for path in _code_files():
        tree = ast.parse(open(path, encoding="utf-8").read())
        docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
                      and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                if any(ord(c) > 127 for c in node.value) and node.value not in allowed:
                    found.append((os.path.basename(path), node.value[:40]))
    assert found == []


def test_unknown_language_falls_back_to_english():
    i18n.set_lang("xx", persist=False)
    assert i18n.current_lang() == "en"
    assert i18n.t("no_such_key") == "no_such_key"


# ------------------------------------------------------------------ settings.json
def test_broken_settings_file_gives_defaults(isolated_settings):
    with open(isolated_settings, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert prefs_mod.load() == prefs_mod.Prefs()


def test_wrong_types_and_values_give_defaults(isolated_settings):
    with open(isolated_settings, "w", encoding="utf-8") as f:
        json.dump({"mode": "zip", "target_kb": "500", "long_edge": 1234, "quality_level": "max",
                   "output": 3, "keep_png": "yes", "recursive": 0, "update_check": "no"}, f)
    assert prefs_mod.load() == prefs_mod.Prefs()


def test_target_out_of_range_gives_the_default(isolated_settings):
    with open(isolated_settings, "w", encoding="utf-8") as f:
        json.dump({"target_kb": 5, "mode": "size", "long_edge": 1280}, f)
    p = prefs_mod.load()
    assert p.target_kb == shrink.DEFAULT_TARGET_KB and p.mode == "size" and p.long_edge == 1280


def test_settings_round_trip_keeps_the_language(isolated_settings):
    i18n.set_lang("ko")
    p = prefs_mod.Prefs(mode="quality", quality_level="high", target_kb=750, keep_png=True)
    prefs_mod.save(p)
    assert prefs_mod.load() == p
    assert i18n.load_settings()["lang"] == "ko"
