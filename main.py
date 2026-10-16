"""Entry point for photo-resize.

    python main.py                          -> GUI
    python main.py photo.jpg folder [...]   -> CLI (results next to the originals)
"""
from __future__ import annotations

import argparse
import os
import sys

import i18n
import prefs as prefs_mod
import shrink
import texts
from i18n import t
from version import APP_VERSION


def _preselect_lang(argv: list[str]) -> str | None:
    """--lang has to be known before the parser is built, so help is translated."""
    for i, a in enumerate(argv):
        if a == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--lang="):
            return a.split("=", 1)[1]
    return None


def _localize_argparse() -> None:
    """argparse's own labels go through gettext; route them to lang files."""
    table = {
        "usage: ": t("cli_usage"),
        "positional arguments": t("cli_positional"),
        "options": t("cli_options"),
        "show this help message and exit": t("cli_help"),
        "show program's version number and exit": t("cli_version"),
        "%(prog)s: error: %(message)s\n": t("cli_error"),
        "invalid choice: %(value)r (choose from %(choices)s)": t("cli_invalid_choice"),
        "argument %(argument_name)s: %(message)s": t("cli_argument"),
        "expected one argument": t("cli_expected_one"),
        "unrecognized arguments: %s": t("cli_unrecognized"),
    }
    argparse._ = lambda s: table.get(s, s)  # type: ignore[attr-defined]


def _target(text: str) -> int:
    kb = shrink.parse_size(text)
    if kb is None:
        raise argparse.ArgumentTypeError(t("cli_bad_target", value=text))
    return kb


def _quality(text: str) -> int:
    if text in shrink.QUALITY_LEVELS:
        return shrink.QUALITY_LEVELS[text]
    try:
        return int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(t("cli_bad_quality", value=text))


def build_parser() -> argparse.ArgumentParser:
    _localize_argparse()
    p = argparse.ArgumentParser(prog="photo-resize", description=t("cli_desc"))
    p.add_argument("inputs", nargs="*", help=t("cli_inputs"))
    p.add_argument("--mode", choices=shrink.MODES, default=shrink.TARGET, help=t("cli_mode"))
    p.add_argument("--target", type=_target, default=shrink.DEFAULT_TARGET_KB, metavar="SIZE", help=t("cli_target"))
    p.add_argument("--size", type=int, default=shrink.DEFAULT_SIZE, metavar="PX", help=t("cli_size"))
    p.add_argument("--quality", type=_quality, default=shrink.QUALITY_LEVELS[shrink.DEFAULT_QUALITY_LEVEL],
                   metavar="Q", help=t("cli_quality"))
    p.add_argument("--output", choices=shrink.OUTPUTS, default=shrink.FOLDER, help=t("cli_output"))
    p.add_argument("--keep-png", action="store_true", help=t("cli_keep_png"))
    p.add_argument("--no-recursive", action="store_true", help=t("cli_no_recursive"))
    p.add_argument("--lang", choices=i18n.LANGS, help=t("cli_lang"))
    p.add_argument("--gui", action="store_true", help=t("cli_gui"))
    p.add_argument("--version", action="version", version=f"photo-resize {APP_VERSION}")
    return p


STATUS_KEYS = {shrink.DONE: "st_done", shrink.OVER: "st_over", shrink.SMALL: "st_small",
               shrink.FAILED: "st_failed", shrink.CANCELLED: "st_cancelled"}


def run_cli(args: argparse.Namespace) -> int:
    items, missing = shrink.collect(args.inputs, recursive=not args.no_recursive)
    for p in missing:
        print(t("err_open_failed", name=p), file=sys.stderr)
    if not items:
        print(t("cli_no_input"), file=sys.stderr)
        return 2
    opts = shrink.Options(mode=args.mode, target_kb=args.target, long_edge=args.size, quality=args.quality,
                          output=args.output, keep_png=args.keep_png).validated()
    jobs = shrink.plan(items, opts)
    print(t("cli_start", count=len(jobs), how=describe(opts)))
    done = [0]

    def show(i: int, r: shrink.Result) -> None:
        done[0] += 1
        name = os.path.basename(r.src)
        status = t(STATUS_KEYS[r.status], error=r.error)
        size = f"{shrink.format_bytes(r.in_size)} -> {shrink.format_bytes(r.out_size)}" if r.dst else \
            shrink.format_bytes(r.in_size)
        print(f"[{done[0]}/{len(jobs)}] {name}: {status} ({size})" + (f" -> {r.dst}" if r.dst else ""), flush=True)

    try:
        results = shrink.run_batch(jobs, opts, on_result=show)
    except KeyboardInterrupt:
        print(t("status_cancelled"))
        return 130
    print(texts.summary_text(shrink.summarize(results)))
    return 1 if any(r.status == shrink.FAILED for r in results) else 0


def describe(opts: shrink.Options) -> str:
    if opts.mode == shrink.TARGET:
        return t("cli_how_target", target=shrink.format_target(opts.target_kb))
    if opts.mode == shrink.SIZE:
        return t("cli_how_size", size=opts.long_edge)
    return t("cli_how_quality", q=opts.quality)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Windows consoles default to cp949; Chinese/Japanese file names would crash print().
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    i18n.init(_preselect_lang(argv))
    # A windowed exe has no console, so dropping photos on it opens the GUI with them
    # instead of running the CLI into nowhere.
    headless = getattr(sys, "frozen", False) and sys.stdout is None
    if headless:
        import gui

        gui.launch([a for a in argv if not a.startswith("-")] or None)
        return 0
    args = build_parser().parse_args(argv)
    if args.lang:
        i18n.set_lang(args.lang, persist=False)
    if args.gui or not args.inputs:
        import gui

        gui.launch(args.inputs or None)
        return 0
    return run_cli(args)


if __name__ == "__main__":
    sys.exit(main())
