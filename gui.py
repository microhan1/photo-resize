"""Tk window: drop photos, choose how small, see the expected sizes and a side-by-side
preview, run, read the summary.

Layout: photo list and preview on the left; on the right a side panel with the options
card (method, target chips, where results go, the promises) and the result card (big
before -> after numbers, progress, the Shrink button).

Threads: the estimate, the preview and the run each work on a background thread that
only puts tuples into `App.queue` and holds no Tk object; the Tk thread drains the queue
every POLL_MS. Nothing is written before [Shrink] is pressed. Closing the window waits
for every background thread.
"""
from __future__ import annotations

import gc
import io
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from tkinter import filedialog, ttk

import i18n
import prefs as prefs_mod
import shrink
import texts
import theme
import update_check
from i18n import t
from version import APP_VERSION

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    _HAS_DND = True
except Exception:  # pragma: no cover - optional dependency
    _HAS_DND = False

try:
    import sv_ttk

    _HAS_SV = True
except Exception:  # pragma: no cover - optional dependency
    _HAS_SV = False

px = theme.px
TIMES, ARROW, ABOUT, DOT, ELLIPSIS = chr(0xD7), chr(0x2192), chr(0x2248), chr(0xB7), chr(0x2026)
CHECK, CROSS, DASH, EM, NBSP = chr(0x2713), chr(0x2715), chr(0x2013), chr(0x2014), chr(0xA0)
GLYPHS = {shrink.DONE: CHECK, shrink.OVER: "!", shrink.SMALL: DASH, shrink.FAILED: CROSS, shrink.CANCELLED: DASH}
POLL_MS = 50
ESTIMATE_DELAY_MS = 350
PREVIEW_DELAY_MS = 150
ESTIMATE_SAMPLE = 12
ZOOMS = ("fit", 1.0, 2.0, 4.0)
COLUMNS = (("name", 280, True, "w"), ("before", 84, False, "e"), ("after", 92, False, "e"),
           ("pixels", 120, False, "center"), ("status", 150, False, "w"))
CUSTOM = "custom"


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def open_path(path: str, select: bool = False) -> None:
    try:
        if sys.platform == "win32":
            if select:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", path if not select else os.path.dirname(path)])
    except OSError:
        pass


def pixels_text(a: tuple[int, int] | None) -> str:
    if not a or not a[0]:
        return ""
    return f"{a[0]}{TIMES}{a[1]}"


def _collect_now() -> None:
    """Free the widgets just thrown away (chips and their Tk variables sit in reference
    cycles) here on the Tk thread. Left to the garbage collector, they may be freed on a
    worker thread, and a Tk variable freed off the Tk thread is an error or, in a frozen
    exe, a Tcl abort ("Tcl_AsyncDelete: async handler deleted by the wrong thread")."""
    gc.collect()


# ------------------------------------------------------------------ background work
# Module-level so a thread never holds the App (and through it Tk objects).
def _estimate_worker(gen: int, items: list, opts: shrink.Options, cancel: threading.Event, out: queue.Queue) -> None:
    """A first estimate from ESTIMATE_SAMPLE photos, then better ones as the others are
    measured in memory too, until every photo is (nothing is written)."""
    try:
        for snapshot in shrink.estimate_iter(items, opts, cancel, first=ESTIMATE_SAMPLE):
            out.put(("estimate", gen, snapshot))
    except shrink.Cancelled:
        pass
    except Exception:
        out.put(("estimate", gen, None))


def _preview_worker(gen: int, item: shrink.Item, opts: shrink.Options, cancel: threading.Event,
                    out: queue.Queue) -> None:
    from PIL import Image

    try:
        src = shrink.open_source(item.src)
        fmt = shrink.final_format(shrink.output_format(item.src, opts.keep_png), src)
        enc = shrink.shrink(src, fmt, opts, cancel)
        res = Image.open(io.BytesIO(enc.data))
        res.load()
        orig = shrink._flatten(src.image) if fmt == "JPEG" else src.image
        info = {"in_size": src.size, "in_pixels": src.pixels, "out_size": len(enc.data), "out_pixels": enc.pixels,
                "quality": enc.quality, "fits": enc.fits, "fmt": fmt, "small": len(enc.data) >= src.size}
        out.put(("preview", gen, (orig, res, info)))
    except shrink.Cancelled:
        pass
    except Exception as exc:
        out.put(("preview", gen, f"{exc.__class__.__name__}: {exc}"[:200]))


def _run_worker(jobs: list, opts: shrink.Options, cancel: threading.Event, out: queue.Queue) -> None:
    try:
        shrink.run_batch(jobs, opts, cancel, on_result=lambda i, r: out.put(("result", i, r)))
    finally:
        out.put(("done", None, None))


class ChipGroup:
    """A row of chips (one choice, like radio buttons) drawn with plain labels, so the
    chosen one is clearly marked: accent background, white text. sv-ttk's Toolbutton does
    not show a radio button's selected state."""

    def __init__(self, parent, choices: list[tuple[str, str]], var: tk.StringVar, command, font,
                 columns: int | None = None, pad: int = 6):
        C = theme.COLORS
        self.var, self.command, self.enabled = var, command, True
        self.frame = ttk.Frame(parent)
        self.chips: dict[str, tk.Label] = {}
        columns = columns or len(choices)
        for c in range(columns):
            self.frame.columnconfigure(c, weight=1, uniform="chip")
        for n, (value, text) in enumerate(choices):
            chip = tk.Label(self.frame, text=text, font=font, bg=C["surface"], fg=C["text"], padx=px(pad),
                            pady=px(5), highlightthickness=1, highlightbackground=C["chip_line"], cursor="hand2")
            chip.grid(row=n // columns, column=n % columns, sticky="ew", padx=px(2), pady=px(2))
            chip.bind("<Button-1>", lambda e, v=value: self.pick(v))
            chip.bind("<Enter>", lambda e, v=value: self._hover(v, True))
            chip.bind("<Leave>", lambda e, v=value: self._hover(v, False))
            self.chips[value] = chip
        self.refresh()

    def pick(self, value: str) -> None:
        """What a click does (tests and the capture harness call it too)."""
        if not self.enabled:
            return
        self.var.set(value)
        self.refresh()
        self.command()

    def _hover(self, value: str, inside: bool) -> None:
        if self.enabled and value != self.var.get():
            self.chips[value].configure(bg=theme.COLORS["chip_hover"] if inside else theme.COLORS["surface"])

    def refresh(self) -> None:
        C = theme.COLORS
        for value, chip in self.chips.items():
            if value == self.var.get():
                chip.configure(bg=C["accent"] if self.enabled else C["muted"], fg="#FFFFFF",
                               highlightbackground=C["accent"] if self.enabled else C["muted"])
            else:
                chip.configure(bg=C["surface"], fg=C["text"] if self.enabled else C["muted"],
                               highlightbackground=C["chip_line"])

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        for chip in self.chips.values():
            chip.configure(cursor="hand2" if enabled else "arrow")
        self.refresh()


# ------------------------------------------------------------------ the window
class App:
    def __init__(self, root: tk.Misc, paths: list[str] | None = None, prefs: prefs_mod.Prefs | None = None):
        self.root = root
        self.prefs = prefs or prefs_mod.load()
        self.items: list[shrink.Item] = []
        self.results: dict[int, shrink.Result] = {}
        self.measured: dict[int, shrink.Result] = {}
        self.guessed: dict[int, int] = {}
        self.queue: queue.Queue = queue.Queue()
        self.est_gen = 0
        self.est_cancel: threading.Event | None = None
        self.est_after = None
        self.prev_gen = 0
        self.prev_cancel: threading.Event | None = None
        self.prev_after = None
        self.prev_index: int | None = None
        self.preview = None  # (original image, result image, info) or an error text
        self.preview_hint = ""
        self.zoom = "fit"
        self.center = (0.5, 0.5)  # preview centre, as a fraction of the picture
        self._drag = None
        self._photos: list = []  # PhotoImage references
        self._redraw_after = None
        self.run_thread: threading.Thread | None = None
        self.run_cancel: threading.Event | None = None
        self.running = False
        self.total_jobs = 0
        self.summary: shrink.Summary | None = None
        self.threads: list[threading.Thread] = []  # every background thread, waited for on close
        self.closing = False
        self.closed = False
        self._update_info: update_check.UpdateInfo | None = None
        self.status = ("status_ready", {})
        self.lockable: list = []  # widgets disabled while a run is going
        self._after_ids: set[str] = set()  # this App's own pending "after" calls
        self.chip_groups: list[ChipGroup] = []

        self._apply_style()
        self._build()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        if _HAS_DND and hasattr(root, "drop_target_register"):
            try:
                root.drop_target_register(DND_FILES)
                root.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass
        root.after(POLL_MS, self._poll)
        update_check.check_async(root, update_check.SLUG, APP_VERSION, self.prefs, self._on_update_result)
        if paths:
            self.add_paths(paths)

    # -------------------------------------------------------------- look
    def _apply_style(self) -> None:
        if _HAS_SV:
            try:
                sv_ttk.set_theme("light")
            except Exception:
                pass
        style = ttk.Style(self.root)
        style.configure("Treeview", rowheight=px(theme.ROW_HEIGHT))

    def _fonts(self) -> None:
        families = set(tkfont.families(self.root))
        name = theme.pick_font(families, theme.UI_FONTS.get(i18n.current_lang(), ()))
        self.f_body = (name, theme.BODY_PT)
        self.f_bold = (name, theme.BODY_PT, "bold")
        self.f_title = (name, theme.TITLE_PT, "bold")
        self.f_big = (name, theme.BIG_PT, "bold")
        self.f_small = (name, theme.BODY_PT - 1)
        # the named fonts behind every ttk widget (sv-ttk's own and Tk's defaults)
        for fname in tkfont.names(self.root):
            if fname.startswith(("SunValley", "Tk")):
                try:
                    tkfont.nametofont(fname, root=self.root).configure(family=name)
                except tk.TclError:
                    pass
        style = ttk.Style(self.root)
        for s in ("TLabel", "TButton", "TRadiobutton", "TCheckbutton", "TCombobox", "TEntry", "Treeview",
                  "Toolbutton", "Accent.TButton"):
            style.configure(s, font=self.f_body)
        style.configure("Treeview.Heading", font=self.f_bold)
        style.configure("Section.TLabel", font=self.f_bold)
        style.configure("Muted.TLabel", foreground=theme.COLORS["muted"])
        style.configure("Small.TLabel", foreground=theme.COLORS["muted"], font=self.f_small)
        style.configure("Big.TLabel", font=self.f_big)
        style.configure("Pct.TLabel", font=self.f_bold, foreground=theme.COLORS["accent"])
        style.configure("Ok.TLabel", foreground=theme.COLORS["ok"])
        style.configure("Promise.TLabel", foreground=theme.COLORS["ok_text"], font=self.f_small)
        style.configure("Err.TLabel", foreground=theme.COLORS["err"], font=self.f_small)
        style.configure("Big.Accent.TButton", font=self.f_bold, padding=(px(12), px(8)))
        self.root.option_add("*TCombobox*Listbox.font", self.f_body)

    # -------------------------------------------------------------- building
    def _build(self) -> None:
        """(Re)build every widget: at start and when the language changes. All state lives
        in the App and the prefs, so nothing is lost."""
        for w in list(self.root.winfo_children()):
            if not isinstance(w, tk.Toplevel):
                w.destroy()
        _collect_now()
        self._fonts()
        self.lockable, self.chip_groups = [], []
        self.root.title(f"{t('app_title')} {APP_VERSION}")
        P = px(theme.PAD)
        outer = ttk.Frame(self.root, padding=(px(theme.PAD_OUT), px(12), px(theme.PAD_OUT), px(theme.PAD_OUT)))
        outer.pack(fill="both", expand=True)
        self.outer = outer

        self._build_header(outer)
        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True, pady=(P * 2, 0))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, minsize=px(theme.SIDE_WIDTH))
        body.rowconfigure(0, weight=1)
        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, P * 2))
        side = ttk.Frame(body, width=px(theme.SIDE_WIDTH))
        side.grid(row=0, column=1, sticky="nsew")
        self._build_list(left)
        self._build_side(side)

        self._fill_table()
        self._show_preview()
        self._refresh_info()
        self._set_busy(self.running)
        self._show_status(self.status[0], **self.status[1])
        if self._update_info is not None:
            self._show_update_notice()

    def _build_header(self, outer) -> None:
        P = px(theme.PAD)
        head = ttk.Frame(outer)
        head.pack(fill="x")
        right = ttk.Frame(head)
        right.pack(side="right", anchor="n")
        names = [i18n.LANG_NAMES.get(c, c) for c in i18n.LANGS]
        self.v_lang = tk.StringVar(value=i18n.LANG_NAMES.get(i18n.current_lang(), i18n.current_lang()))
        self.cb_lang = ttk.Combobox(right, textvariable=self.v_lang, values=names, state="readonly",
                                    width=max(len(n) for n in names) + 2, font=self.f_body)
        self.cb_lang.pack(side="right")
        self.cb_lang.bind("<<ComboboxSelected>>", self._on_lang)
        self.v_update = tk.BooleanVar(value=self.prefs.update_check)
        self.chk_update = ttk.Checkbutton(right, text=t("opt_update_check"), variable=self.v_update,
                                          command=self._on_update_toggle)
        self.chk_update.pack(side="right", padx=(0, P * 2))
        ttk.Label(head, text=t("app_title"), font=self.f_title).pack(side="left")
        ttk.Label(head, text=t("app_tagline"), style="Muted.TLabel").pack(side="left", padx=(P * 2, 0),
                                                                          pady=(px(4), 0))

    def _build_list(self, left) -> None:
        P = px(theme.PAD)
        C = theme.COLORS
        tools = ttk.Frame(left)
        tools.pack(fill="x")
        self.btn_files = ttk.Button(tools, text=t("btn_add_files"), command=self.pick_files)
        self.btn_files.pack(side="left")
        self.btn_folder = ttk.Button(tools, text=t("btn_add_folder"), command=self.pick_folder)
        self.btn_folder.pack(side="left", padx=(P, 0))
        self.btn_clear = ttk.Button(tools, text=t("btn_clear"), command=self.clear)
        self.btn_clear.pack(side="left", padx=(P, 0))
        self.v_recursive = tk.BooleanVar(value=self.prefs.recursive)
        self.chk_recursive = ttk.Checkbutton(tools, text=t("opt_recursive"), variable=self.v_recursive,
                                             command=self._on_recursive)
        self.chk_recursive.pack(side="left", padx=(P * 2, 0))
        self.lbl_count = ttk.Label(tools, text="", style="Muted.TLabel")
        self.lbl_count.pack(side="right")
        self.lockable += [self.btn_files, self.btn_folder, self.btn_clear, self.chk_recursive]

        # the update notice: one line at the bottom of the window, under the list, so the side
        # panel keeps its height whether or not the notice is shown
        self.update_area = ttk.Frame(left)
        self.update_area.pack(side="bottom", fill="x")
        promises = "   ".join(f"{CHECK}{NBSP}{t(k)}" for k in ("promise_original", "promise_gps", "promise_keep",
                                                          "promise_bigger"))
        self.lbl_promises = ttk.Label(left, text=promises, style="Promise.TLabel", justify="left")
        self.lbl_promises.pack(side="bottom", fill="x", pady=(P, 0))
        self.lbl_promises.bind("<Configure>", lambda e: self.lbl_promises.configure(wraplength=max(100, e.width)))
        self.paned = ttk.Panedwindow(left, orient="vertical")
        self.paned.pack(fill="both", expand=True, pady=(P, 0))

        table = ttk.Frame(self.paned)
        cols = [c[0] for c in COLUMNS]
        self.tree = ttk.Treeview(table, columns=cols, show="headings", selectmode="extended")
        for name, width, stretch, anchor in COLUMNS:
            self.tree.heading(name, text=t(f"col_{name}"), anchor=anchor)
            self.tree.column(name, width=px(width), minwidth=px(60), stretch=stretch, anchor=anchor)
        self.tree.tag_configure("odd", background=C["stripe"])
        self.tree.tag_configure(shrink.OVER, foreground=C["warn"])
        self.tree.tag_configure(shrink.FAILED, foreground=C["err"])
        self.tree.tag_configure(shrink.SMALL, foreground=C["muted"])
        self.tree.tag_configure(shrink.CANCELLED, foreground=C["muted"])
        self.tree.tag_configure("guess", foreground=C["muted"])
        vsb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Delete>", lambda e: self.remove_selected())
        # empty list: a dashed drop area over the table
        self.drop = tk.Canvas(table, bg=C["surface"], highlightthickness=0, cursor="hand2")
        self.drop.bind("<Configure>", lambda e: self._draw_drop())
        self.drop.bind("<Button-1>", lambda e: None if self.running else self.pick_files())
        self.paned.add(table, weight=3)

        pv = ttk.Frame(self.paned)
        top = ttk.Frame(pv)
        top.pack(fill="x", pady=(P * 2, P))
        ttk.Label(top, text=t("lbl_preview"), style="Section.TLabel").pack(side="left")
        ttk.Label(top, text=t("lbl_drag_hint"), style="Small.TLabel").pack(side="left", padx=(P, 0))
        self.v_zoom = tk.StringVar(value=str(self.zoom))
        zooms = [(str(z), t("zoom_fit") if z == "fit" else f"{int(z * 100)}%") for z in ZOOMS]
        self.zoom_chips = ChipGroup(top, zooms, self.v_zoom, self._on_zoom, self.f_small, pad=8)
        self.zoom_chips.frame.pack(side="right")
        pair = ttk.Frame(pv)
        pair.pack(fill="both", expand=True)
        pair.columnconfigure(0, weight=1, uniform="pv")
        pair.columnconfigure(1, weight=1, uniform="pv")
        pair.rowconfigure(1, weight=1)
        self.lbl_orig = ttk.Label(pair, text=t("lbl_original"), style="Muted.TLabel")
        self.lbl_orig.grid(row=0, column=0, sticky="w", pady=(0, px(4)))
        self.lbl_res = ttk.Label(pair, text=t("lbl_result"), style="Muted.TLabel")
        self.lbl_res.grid(row=0, column=1, sticky="w", padx=(P, 0), pady=(0, px(4)))
        self.cv_orig = tk.Canvas(pair, bg=C["canvas"], highlightthickness=1, highlightbackground=C["border"],
                                 height=px(160))
        self.cv_orig.grid(row=1, column=0, sticky="nsew")
        self.cv_res = tk.Canvas(pair, bg=C["canvas"], highlightthickness=1, highlightbackground=C["border"],
                                height=px(160))
        self.cv_res.grid(row=1, column=1, sticky="nsew", padx=(P, 0))
        for cv in (self.cv_orig, self.cv_res):
            cv.bind("<Configure>", lambda e: self._schedule_redraw())
            cv.bind("<ButtonPress-1>", self._drag_start)
            cv.bind("<B1-Motion>", self._drag_move)
            cv.bind("<MouseWheel>", self._on_wheel)
        self.paned.add(pv, weight=2)

    def _build_side(self, side) -> None:
        P = px(theme.PAD)
        wrap = px(theme.SIDE_WIDTH) - P * 6
        card_style = "Card.TFrame" if _HAS_SV else "TFrame"

        # result card at the bottom of the side panel
        res = ttk.Frame(side, style=card_style, padding=P * 2)
        res.pack(side="bottom", fill="x", pady=(P * 2, 0))
        self.lbl_big = ttk.Label(res, text="", style="Big.TLabel")
        self.lbl_big.pack(anchor="w")
        self.lbl_pct = ttk.Label(res, text="", style="Pct.TLabel")
        self.lbl_pct.pack(anchor="w")
        self.lbl_detail = ttk.Label(res, text="", style="Small.TLabel", wraplength=wrap, justify="left")
        self.lbl_detail.pack(anchor="w", fill="x", pady=(px(4), 0))
        self.progress = ttk.Progressbar(res, mode="determinate")
        self.progress.pack(fill="x", pady=(P + px(4), px(4)))
        self.lbl_status = ttk.Label(res, text="", style="Small.TLabel", wraplength=wrap, justify="left")
        self.lbl_status.pack(anchor="w", fill="x")
        self.btn_run = ttk.Button(res, text=t("btn_run"), style="Big.Accent.TButton", command=self.run)
        self.btn_run.pack(fill="x", pady=(P + px(4), 0))
        row = ttk.Frame(res)
        row.pack(fill="x", pady=(P, 0))
        row.columnconfigure(0, weight=1, uniform="b")
        row.columnconfigure(1, weight=1, uniform="b")
        self.btn_cancel = ttk.Button(row, text=t("btn_cancel"), command=self.cancel)
        self.btn_cancel.grid(row=0, column=0, sticky="ew", padx=(0, px(4)))
        self.btn_open = ttk.Button(row, text=t("btn_open_results"), command=self.open_results)
        self.btn_open.grid(row=0, column=1, sticky="ew", padx=(px(4), 0))

        # options card
        opt = ttk.Frame(side, style=card_style, padding=P * 2)
        opt.pack(side="top", fill="both", expand=True)
        ttk.Label(opt, text=t("lbl_how"), style="Section.TLabel").pack(anchor="w")
        self.v_mode = tk.StringVar(value=self.prefs.mode)
        modes = [(shrink.TARGET, t("mode_target")), (shrink.SIZE, t("mode_size")),
                 (shrink.QUALITY, t("mode_quality"))]
        self.mode_chips = ChipGroup(opt, modes, self.v_mode, self._on_mode, self.f_bold)
        self.mode_chips.frame.pack(fill="x", pady=(P, 0))
        self.chip_groups.append(self.mode_chips)
        self.mode_area = ttk.Frame(opt)
        self.mode_area.pack(fill="x", pady=(P + px(4), 0))
        self._build_mode_widgets()

        ttk.Separator(opt).pack(fill="x", pady=(P + px(4), P + px(4)))
        ttk.Label(opt, text=t("lbl_output"), style="Section.TLabel").pack(anchor="w")
        self.v_output = tk.StringVar(value=self.prefs.output)
        outputs = [(shrink.FOLDER, t("opt_output_folder")), (shrink.SUFFIX, t("opt_output_suffix"))]
        self.output_chips = ChipGroup(opt, outputs, self.v_output, self._on_output, self.f_body, pad=2)
        self.output_chips.frame.pack(fill="x", pady=(px(4), 0))
        self.chip_groups.append(self.output_chips)
        self.v_keep_png = tk.BooleanVar(value=self.prefs.keep_png)
        self.chk_png = ttk.Checkbutton(opt, text=t("opt_keep_png"), variable=self.v_keep_png,
                                       command=self._on_keep_png)
        self.chk_png.pack(anchor="w", pady=(P, 0))
        self.lockable.append(self.chk_png)

    def _chip_grid(self, parent, choices: list[tuple[str, str]], var: tk.StringVar, command) -> ChipGroup:
        group = ChipGroup(parent, choices, var, command, self.f_body, pad=2)
        group.frame.pack(fill="x", pady=(px(4), 0))
        group.set_enabled(not self.running)
        self.chip_groups.append(group)
        self.option_chips = group
        return group

    def _build_mode_widgets(self) -> None:
        for w in self.mode_area.winfo_children():
            w.destroy()
        _collect_now()
        self.chip_groups = [g for g in self.chip_groups if g.frame.winfo_exists()]
        self.mode_widgets = []
        mode = self.prefs.mode
        P = px(theme.PAD)
        wrap = px(theme.SIDE_WIDTH) - P * 6
        if mode == shrink.TARGET:
            ttk.Label(self.mode_area, text=t("lbl_target")).pack(anchor="w")
            custom = self.prefs.target_kb not in shrink.TARGET_PRESETS_KB
            self.v_target = tk.StringVar(value=CUSTOM if custom else str(self.prefs.target_kb))
            choices = [(str(k), shrink.format_target(k)) for k in shrink.TARGET_PRESETS_KB] + [(CUSTOM, t("opt_custom"))]
            self._chip_grid(self.mode_area, choices, self.v_target, self._on_target)
            self.custom_row = ttk.Frame(self.mode_area)
            self.v_custom = tk.StringVar(value=str(self.prefs.target_kb))
            self.ent_custom = ttk.Entry(self.custom_row, textvariable=self.v_custom, width=8, justify="right",
                                        font=self.f_body)
            self.ent_custom.pack(side="left")
            self.ent_custom.bind("<KeyRelease>", self._on_custom)
            self.ent_custom.bind("<FocusOut>", self._on_custom)
            ttk.Label(self.custom_row, text="KB").pack(side="left", padx=(px(6), 0))
            self.lbl_custom_err = ttk.Label(self.mode_area, text="", style="Err.TLabel", wraplength=wrap)
            self.mode_widgets.append(self.ent_custom)
            note = t("lbl_target_note")
        elif mode == shrink.SIZE:
            ttk.Label(self.mode_area, text=t("lbl_long_edge")).pack(anchor="w")
            self.v_size = tk.StringVar(value=str(self.prefs.long_edge))
            self._chip_grid(self.mode_area, [(str(s), str(s)) for s in shrink.SIZES], self.v_size, self._on_size)
            note = t("lbl_size_note")
        else:
            ttk.Label(self.mode_area, text=t("lbl_quality")).pack(anchor="w")
            self.v_quality = tk.StringVar(value=self.prefs.quality_level)
            choices = [(lv, t(f"quality_{lv}", q=q)) for lv, q in shrink.QUALITY_LEVELS.items()]
            self._chip_grid(self.mode_area, choices, self.v_quality, self._on_quality)
            note = t("lbl_quality_note")
        self.lbl_mode_note = ttk.Label(self.mode_area, text=note, style="Small.TLabel", wraplength=wrap,
                                       justify="left")
        self.lbl_mode_note.pack(anchor="w", fill="x", pady=(px(6), 0))
        if mode == shrink.TARGET and self.v_target.get() == CUSTOM:
            self._show_custom(True)
        if self.running:
            for w in self.mode_widgets:
                w.configure(state="disabled")

    def _show_custom(self, show: bool) -> None:
        if show:
            self.custom_row.pack(anchor="w", pady=(px(6), 0), before=self.lbl_mode_note)
            self.lbl_custom_err.pack(anchor="w", after=self.custom_row)
        else:
            self.custom_row.pack_forget()
            self.lbl_custom_err.pack_forget()

    def _draw_drop(self) -> None:
        cv = self.drop
        cv.delete("all")
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 20 or h < 20:
            return
        C = theme.COLORS
        m = px(12)
        cv.create_rectangle(m, m, w - m, h - m, outline=C["drop_line"], dash=(6, 4), width=px(2))
        first, _, second = t("lbl_drop").partition("\n")
        cv.create_text(w // 2, h // 2 - px(12), text=first, fill=C["text"], font=self.f_bold)
        cv.create_text(w // 2, h // 2 + px(14), text=second, fill=C["muted"], font=self.f_small)

    # -------------------------------------------------------------- option handlers
    def _save(self) -> None:
        prefs_mod.save(self.prefs)

    def options_changed(self) -> None:
        """Results on screen were made with the old options: drop them, estimate again."""
        self._save()
        if self.results:
            self.results.clear()
            self.summary = None
        self._fill_table()
        self._request_estimate()
        self._request_preview()

    def _on_mode(self) -> None:
        if self.v_mode.get() == self.prefs.mode:
            return
        self.prefs.mode = self.v_mode.get()
        self._build_mode_widgets()
        self.options_changed()

    def _on_target(self) -> None:
        value = self.v_target.get()
        if value != CUSTOM:
            self._show_custom(False)
            kb = int(value)
            if self.prefs.target_kb != kb:
                self.prefs.target_kb = kb
                self.options_changed()
            return
        self._show_custom(True)
        self.ent_custom.focus_set()
        self.ent_custom.select_range(0, "end")
        self._on_custom()

    def _on_custom(self, event=None) -> None:
        kb = shrink.parse_size(self.v_custom.get())
        if kb is None or not shrink.TARGET_MIN_KB <= kb <= shrink.TARGET_MAX_KB:
            self.lbl_custom_err.configure(text=t("err_custom_target", lo=shrink.TARGET_MIN_KB,
                                                 hi=shrink.TARGET_MAX_KB))
            return
        self.lbl_custom_err.configure(text="")
        if kb != self.prefs.target_kb:
            self.prefs.target_kb = kb
            self.options_changed()

    def _on_size(self) -> None:
        edge = int(self.v_size.get())
        if edge != self.prefs.long_edge:
            self.prefs.long_edge = edge
            self.options_changed()

    def _on_quality(self) -> None:
        level = self.v_quality.get()
        if level in shrink.QUALITY_LEVELS and level != self.prefs.quality_level:
            self.prefs.quality_level = level
            self.options_changed()

    def _on_output(self) -> None:
        if self.v_output.get() != self.prefs.output:
            self.prefs.output = self.v_output.get()
            self._save()
            if self.results:
                self.results.clear()
                self.summary = None
                self._fill_table()

    def _on_keep_png(self) -> None:
        self.prefs.keep_png = bool(self.v_keep_png.get())
        self.options_changed()

    def _on_recursive(self) -> None:
        self.prefs.recursive = bool(self.v_recursive.get())
        self._save()  # applies to the next folder added

    def _on_lang(self, event=None) -> None:
        names = {i18n.LANG_NAMES.get(c, c): c for c in i18n.LANGS}
        code = names.get(self.v_lang.get())
        if code and code != i18n.current_lang():
            i18n.set_lang(code)
            self._build()

    def _on_update_toggle(self) -> None:
        self.prefs.update_check = bool(self.v_update.get())
        self._save()
        if not self.prefs.update_check:
            self._hide_update_notice()

    # -------------------------------------------------------------- adding photos
    def _on_drop(self, event) -> None:
        if self.running:
            return
        self.add_paths(list(self.root.tk.splitlist(event.data)))

    def pick_files(self) -> None:
        types = [(t("dlg_photos"), " ".join(f"*{e}" for e in shrink.EXTS)), (t("dlg_all_files"), "*.*")]
        paths = filedialog.askopenfilenames(parent=self.root, title=t("dlg_add_files"), filetypes=types)
        if paths:
            self.add_paths(list(paths))

    def pick_folder(self) -> None:
        path = filedialog.askdirectory(parent=self.root, title=t("dlg_add_folder"))
        if path:
            self.add_paths([path])

    def add_paths(self, paths: list[str]) -> int:
        if self.running:
            return 0
        known = {os.path.normcase(i.src) for i in self.items}
        items, missing = shrink.collect(paths, self.prefs.recursive, known)
        if self.results:
            self.results.clear()
            self.summary = None
        first_new = len(self.items)
        self.items.extend(items)
        self._fill_table()
        if missing:
            self._show_status("err_missing", name=missing[0], count=len(missing))
        elif not items:
            self._show_status("msg_no_photos")
        else:
            self._show_status("msg_added", count=len(items))
        self._request_estimate()
        if items:
            iid = str(first_new)
            self.tree.selection_set(iid)
            self.tree.see(iid)
        return len(items)

    def clear(self) -> None:
        if self.running:
            return
        self.items, self.results = [], {}
        self.summary = None
        self.prev_index, self.preview = None, None
        self._request_estimate()  # stops an estimate still running and drops what it sends
        self._request_preview()
        self._fill_table()
        self._show_status("status_ready")

    def remove_selected(self) -> None:
        if self.running:
            return
        drop = {int(i) for i in self.tree.selection()}
        if not drop:
            return
        self.items = [it for i, it in enumerate(self.items) if i not in drop]
        self.results, self.measured, self.guessed = {}, {}, {}
        self.summary = None
        self.prev_index, self.preview = None, None
        self._fill_table()
        self._show_preview()
        self._request_estimate()

    # -------------------------------------------------------------- table
    def _row(self, i: int) -> tuple[tuple, str]:
        item = self.items[i]
        try:
            name = os.path.relpath(item.src, item.base).replace(os.sep, "/")
        except ValueError:
            name = os.path.basename(item.src)
        before = shrink.format_bytes(item.size)
        r = self.results.get(i)
        if r is not None:
            after = shrink.format_bytes(r.out_size) if r.dst else ""
            return (name, before, after, pixels_text(r.out_pixels if r.dst else r.in_pixels),
                    self._status_text(r)), r.status
        m = self.measured.get(i)
        if m is not None:
            made = m.status in (shrink.DONE, shrink.OVER) and m.out_size < m.in_size
            after = shrink.format_bytes(m.out_size) if made else ""
            return (name, before, after, pixels_text(m.out_pixels if made else m.in_pixels),
                    self._status_text(m, preview=True)), "guess" if m.status == shrink.DONE else m.status
        if i in self.guessed:
            return (name, before, f"{ABOUT} {shrink.format_bytes(self.guessed[i])}", "", ""), "guess"
        return (name, before, "", "", ""), "wait"

    def _status_text(self, r: shrink.Result, preview: bool = False) -> str:
        if r.status == shrink.DONE:
            text = t("st_done_q", q=r.quality) if r.quality else t("st_done")
        elif r.status == shrink.OVER:
            text = t("st_over") if (r.dst or preview and r.out_size < r.in_size) else t("st_over_none")
        elif r.status == shrink.SMALL:
            text = t("st_small")
        elif r.status == shrink.CANCELLED:
            text = t("st_cancelled")
        else:
            text = t("st_failed", error=r.error)
        if preview and r.status == shrink.DONE:
            text = t("st_expected", text=text)
        return f"{GLYPHS.get(r.status, '')} {text}"

    def _fill_table(self) -> None:
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for i in range(len(self.items)):
            values, tag = self._row(i)
            self.tree.insert("", "end", iid=str(i), values=values, tags=(tag, "odd" if i % 2 else "even"))
        keep = [s for s in sel if self.tree.exists(s)]
        if keep:
            self.tree.selection_set(keep)
        if self.items:
            self.drop.place_forget()
        else:
            self.drop.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.lbl_count.configure(text=t("lbl_count", count=len(self.items)) if self.items else "")
        self._refresh_info()
        self._set_busy(self.running)

    def _update_row(self, i: int) -> None:
        if self.tree.exists(str(i)):
            values, tag = self._row(i)
            self.tree.item(str(i), values=values, tags=(tag, "odd" if i % 2 else "even"))

    def _refresh_info(self) -> None:
        """The result card: big before -> after, the percentage, the details."""
        s = self.summary
        if s is not None:
            big = t("info_big", before=shrink.format_bytes(s.before), after=shrink.format_bytes(s.after))
            pct = t("info_pct", percent=s.percent, count=s.count)
            parts = []
            for n, key in ((s.over, "summary_over"), (s.small, "summary_small"), (s.failed, "summary_failed"),
                           (s.cancelled, "summary_cancelled")):
                if n:
                    parts.append(t(key, count=n))
            parts.append(t("summary_gps", count=s.gps))
            detail = f" {DOT} ".join(parts)
        elif self.items:
            before = sum(it.size for it in self.items)
            known = bool(self.measured or self.guessed)
            after = 0
            for i, it in enumerate(self.items):
                after += shrink.expected_size(self.measured[i]) if i in self.measured else self.guessed.get(i, it.size)
            if known:
                percent = int(round(100 * (1 - after / before))) if before else 0
                key = "info_big" if len(self.measured) >= len(self.items) else "info_big_estimate"
                big = t(key, before=shrink.format_bytes(before), after=shrink.format_bytes(after))
                pct = t("info_pct", percent=percent, count=len(self.items))
                if len(self.measured) >= len(self.items):
                    detail = t("info_estimate_exact")
                else:
                    detail = t("info_estimate_note", n=len(self.measured), total=len(self.items))
            else:
                big = shrink.format_bytes(before)
                pct = t("lbl_count", count=len(self.items))
                detail = t("info_estimating")
        else:
            big, pct, detail = EM, "", t("info_empty")
        self.lbl_big.configure(foreground=theme.COLORS["muted"] if big == EM else theme.COLORS["text"])
        self.lbl_big.configure(text=big)
        self.lbl_pct.configure(text=pct)
        self.lbl_detail.configure(text=detail)

    def info_text(self) -> str:
        """Everything the result card says, in one line (for tests and captions)."""
        return " | ".join(w.cget("text") for w in (self.lbl_big, self.lbl_pct, self.lbl_detail) if w.cget("text"))

    summary_text = staticmethod(texts.summary_text)

    def _show_status(self, key: str, **kwargs) -> None:
        self.status = (key, kwargs)
        self.lbl_status.configure(text=t(key, **kwargs))

    # -------------------------------------------------------------- estimate
    def _request_estimate(self) -> None:
        if self.est_after is not None:
            try:
                self.root.after_cancel(self.est_after)
            except Exception:
                pass
            self.est_after = None
        if self.est_cancel is not None:
            self.est_cancel.set()
        self.est_gen += 1
        self.measured, self.guessed = {}, {}
        self._refresh_info()
        if self.items and not self.running:
            self.est_after = self.root.after(ESTIMATE_DELAY_MS, self._start_estimate)

    def _start_estimate(self) -> None:
        self.est_after = None
        if self.closing or self.running or not self.items:
            return
        self.est_cancel = threading.Event()
        self._spawn(_estimate_worker, "estimate",
                    (self.est_gen, list(self.items), self.prefs.options(), self.est_cancel, self.queue))

    def _spawn(self, target, name: str, args: tuple) -> threading.Thread:
        self.threads = [th for th in self.threads if th.is_alive()]
        th = threading.Thread(target=target, name=name, args=args, daemon=True)
        self.threads.append(th)
        th.start()
        return th

    # -------------------------------------------------------------- preview
    def _on_select(self, event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        i = int(sel[0])
        if i != self.prev_index:
            self.prev_index = i
            self.center = (0.5, 0.5)
            self._request_preview()

    def _request_preview(self) -> None:
        if self.prev_after is not None:
            try:
                self.root.after_cancel(self.prev_after)
            except Exception:
                pass
            self.prev_after = None
        if self.prev_cancel is not None:
            self.prev_cancel.set()
        self.prev_gen += 1
        self.preview = None
        self._show_preview(loading=self.prev_index is not None)
        if self.prev_index is not None and self.prev_index < len(self.items):
            self.prev_after = self.root.after(PREVIEW_DELAY_MS, self._start_preview)

    def _start_preview(self) -> None:
        self.prev_after = None
        if self.closing or self.prev_index is None or self.prev_index >= len(self.items):
            return
        self.prev_cancel = threading.Event()
        self._spawn(_preview_worker, "preview",
                    (self.prev_gen, self.items[self.prev_index], self.prefs.options(), self.prev_cancel, self.queue))

    def _show_preview(self, loading: bool = False) -> None:
        C = theme.COLORS
        p = self.preview
        if isinstance(p, tuple):
            info = p[2]
            self.lbl_orig.configure(text=t("lbl_original_info", size=shrink.format_bytes(info["in_size"]),
                                           pixels=pixels_text(info["in_pixels"])), foreground=C["text"])
            if info["small"]:
                text, color = t("lbl_result_small", size=shrink.format_bytes(info["out_size"])), C["muted"]
            else:
                q = t("lbl_quality_value", q=info["quality"]) if info["fmt"] == "JPEG" else "PNG"
                text = t("lbl_result_info", size=shrink.format_bytes(info["out_size"]),
                         pixels=pixels_text(info["out_pixels"]), quality=q)
                color = C["text"] if info["fits"] else C["warn"]
                if not info["fits"]:
                    text += f" {DOT} " + t("st_over")
            self.lbl_res.configure(text=text, foreground=color)
        else:
            self.lbl_orig.configure(text=t("lbl_original"), foreground=C["muted"])
            self.lbl_res.configure(text=t("lbl_result"), foreground=C["muted"])
            if isinstance(p, str):
                self.preview_hint = t("st_failed", error=p)
            else:
                self.preview_hint = t("lbl_preview_loading" if loading else "lbl_preview_none")
        self._redraw()

    def _schedule_redraw(self) -> None:
        if self._redraw_after is None:
            self._redraw_after = self.root.after(60, self._redraw)
            self._after_ids.add(self._redraw_after)

    def _redraw(self) -> None:
        """Both pictures at the same scale and the same place: the result is stretched back
        to the original's size, so one look shows what was lost."""
        self._redraw_after = None
        from PIL import Image, ImageTk

        self._photos = []
        for cv in (self.cv_orig, self.cv_res):
            cv.delete("all")
        W, H = self.cv_orig.winfo_width(), self.cv_orig.winfo_height()
        if not isinstance(self.preview, tuple):
            if W > 40 and H > 20:
                for cv in (self.cv_orig, self.cv_res):
                    cv.create_text(W // 2, H // 2, text=self.preview_hint, fill=theme.COLORS["muted"],
                                   font=self.f_small, width=W - px(32), justify="center")
            return
        orig, res, _ = self.preview
        if W < 4 or H < 4:
            return
        ow, oh = orig.size
        z = min(W / ow, H / oh, 1.0) if self.zoom == "fit" else float(self.zoom)
        vw, vh = min(ow, W / z), min(oh, H / z)
        cx = min(max(self.center[0] * ow, vw / 2), ow - vw / 2)
        cy = min(max(self.center[1] * oh, vh / 2), oh - vh / 2)
        self.center = (cx / ow, cy / oh)
        box = (cx - vw / 2, cy - vh / 2, cx + vw / 2, cy + vh / 2)
        out = (max(1, round(vw * z)), max(1, round(vh * z)))
        for cv, img in ((self.cv_orig, orig), (self.cv_res, res)):
            s = img.width / ow
            crop = img.crop(tuple(round(v * s) for v in box))
            factor = out[0] / max(1, crop.width)
            method = Image.Resampling.NEAREST if factor >= 2 else Image.Resampling.BILINEAR
            shown = crop.resize(out, method, reducing_gap=2.0 if factor < 1 else None)
            photo = ImageTk.PhotoImage(shown, master=cv)
            self._photos.append(photo)
            cv.create_image(W // 2, H // 2, image=photo, anchor="center")

    def _on_zoom(self) -> None:
        value = self.v_zoom.get()
        self.zoom = "fit" if value == "fit" else float(value)
        self._redraw()

    def _on_wheel(self, event) -> None:
        i = ZOOMS.index(self.zoom)
        i = min(len(ZOOMS) - 1, i + 1) if event.delta > 0 else max(0, i - 1)
        if ZOOMS[i] != self.zoom:
            self.zoom = ZOOMS[i]
            self.v_zoom.set(str(self.zoom))
            self._redraw()

    def _drag_start(self, event) -> None:
        self._drag = (event.x, event.y, self.center)

    def _drag_move(self, event) -> None:
        if self._drag is None or not isinstance(self.preview, tuple) or self.zoom == "fit":
            return
        x0, y0, (c0x, c0y) = self._drag
        ow, oh = self.preview[0].size
        z = float(self.zoom)
        self.center = (c0x - (event.x - x0) / z / ow, c0y - (event.y - y0) / z / oh)
        self._redraw()

    # -------------------------------------------------------------- run
    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for w in (*self.lockable, *getattr(self, "mode_widgets", [])):
            try:
                w.configure(state=state)
            except tk.TclError:
                pass
        for group in self.chip_groups:
            if group.frame.winfo_exists():
                group.set_enabled(not busy)
        self.cb_lang.configure(state="disabled" if busy else "readonly")
        self.btn_run.configure(state="disabled" if busy or not self.items else "normal")
        self.btn_cancel.configure(state="normal" if busy else "disabled")
        has_results = any(r.dst for r in self.results.values())
        self.btn_open.configure(state="normal" if has_results and not busy else "disabled")

    def run(self) -> None:
        if self.running or not self.items:
            return
        if self.est_cancel is not None:
            self.est_cancel.set()
        self.est_gen += 1  # an estimate still on its way is dropped
        opts = self.prefs.options()
        jobs = shrink.plan(self.items, opts)
        self.results.clear()
        self.summary = None
        self.total_jobs = len(jobs)
        self.running = True
        self._fill_table()
        self.progress.configure(maximum=max(1, len(jobs)), value=0)
        self._show_status("status_running", done=0, total=len(jobs))
        self.run_cancel = threading.Event()
        self.run_thread = self._spawn(_run_worker, "shrink", (jobs, opts, self.run_cancel, self.queue))

    def cancel(self) -> None:
        if self.running and self.run_cancel is not None:
            self.run_cancel.set()
            self._show_status("status_cancelling")

    def _finish_run(self) -> None:
        self.running = False
        self.run_thread = None
        self.summary = shrink.summarize(self.results.values())
        self._refresh_info()
        self._set_busy(False)
        if self.run_cancel is not None and self.run_cancel.is_set():
            self._show_status("status_cancelled")
        else:
            self._show_status("status_done")

    def open_results(self) -> None:
        written = [r.dst for i, r in sorted(self.results.items()) if r.dst]
        if written:
            open_path(written[0], select=True)

    # -------------------------------------------------------------- the queue
    def _poll(self) -> None:
        if self.closed:
            return
        try:
            while True:
                kind, a, b = self.queue.get_nowait()
                if kind == "result":
                    self.results[a] = b
                    self._update_row(a)
                    self.progress.configure(value=len(self.results))
                    self._show_status("status_running", done=len(self.results), total=self.total_jobs)
                elif kind == "done":
                    self._finish_run()
                elif kind == "estimate" and a == self.est_gen and b is not None:
                    self.measured, self.guessed = b
                    if not self.results:
                        for i in range(len(self.items)):
                            self._update_row(i)
                    self._refresh_info()
                elif kind == "preview" and a == self.prev_gen:
                    self.preview = b
                    self._show_preview()
        except queue.Empty:
            pass
        except tk.TclError:
            return
        self._after_ids.discard(getattr(self, "_poll_after", None))
        self._poll_after = self.root.after(POLL_MS, self._poll)
        self._after_ids.add(self._poll_after)

    # -------------------------------------------------------------- closing
    def on_close(self) -> None:
        """Cancel and wait for every background thread to stop (a photo being written is
        finished or removed, never left half-written), then close."""
        if self.closing:
            return
        self.closing = True
        for after in (self.est_after, self.prev_after):
            if after is not None:
                try:
                    self.root.after_cancel(after)
                except Exception:
                    pass
        for ev in (self.est_cancel, self.prev_cancel, self.run_cancel):
            if ev is not None:
                ev.set()
        self._save()
        self._wait_close()

    def _wait_close(self) -> None:
        if any(th.is_alive() for th in self.threads):
            self._after_ids.add(self.root.after(POLL_MS, self._wait_close))
            return
        self._destroy()

    def _destroy(self) -> None:
        self.closed = True
        self._photos = []
        # Calls still waiting in Tk's "after" queue (the poll loops, a redraw, the update
        # check's poll) would wake up after the window is gone: "invalid command name".
        try:
            pending = self.root.tk.splitlist(self.root.tk.call("after", "info"))
            if isinstance(self.root, tk.Tk):
                mine = pending  # the whole program is closing
            else:
                mine = [a for a in pending if a in self._after_ids]
            for aid in mine:
                self.root.after_cancel(aid)
        except tk.TclError:
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        _collect_now()

    # -------------------------------------------------------------- new version notice
    def _on_update_result(self, info: update_check.UpdateInfo | None, answered: bool) -> None:
        """Tk thread. The day is recorded only when the server answered, so an offline
        start asks again next time."""
        if self.closed:
            return
        if answered:
            self.prefs.update_check_last = update_check.today()
            self._save()
        if info is not None and self.prefs.update_check:
            self._update_info = info
            self._show_update_notice()

    def _show_update_notice(self) -> None:
        """One line at the bottom of the window, never a dialog: text, [Update], [Later]."""
        for w in self.update_area.winfo_children():
            w.destroy()
        info = self._update_info
        if info is None:
            return
        P = px(theme.PAD)
        bg = theme.COLORS["band"]
        band = tk.Frame(self.update_area, bg=bg, padx=P * 2, pady=P, highlightthickness=1,
                        highlightbackground=theme.COLORS["band_line"])
        band.pack(fill="x", pady=(P, 0))
        ttk.Button(band, text=t("btn_later"), command=self._update_later).pack(side="right")
        ttk.Button(band, text=t("btn_update"), style="Accent.TButton", command=self._update_open).pack(
            side="right", padx=(0, P))
        tk.Label(band, text=t("update_available", latest=info.latest, current=info.current), bg=bg,
                 fg=theme.COLORS["text"], font=self.f_body, anchor="w").pack(side="left", fill="x", expand=True)

    def _hide_update_notice(self) -> None:
        self._update_info = None
        for w in self.update_area.winfo_children():
            w.destroy()

    def _update_open(self) -> None:
        """The tools page, never a download: the site counts and serves the download."""
        info = self._update_info
        if info is not None and info.url.startswith(update_check.SITE):
            try:
                webbrowser.open(update_check.page_url(info, i18n.current_lang()))
            except Exception:
                pass
        self._hide_update_notice()

    def _update_later(self) -> None:
        if self._update_info is not None:
            self.prefs.update_check_skipped = self._update_info.latest  # a newer one is shown again
            self._save()
        self._hide_update_notice()


def _icon(root: tk.Tk) -> None:
    path = os.path.join(i18n.resource_dir(), "assets", "icon.png")
    try:
        img = tk.PhotoImage(file=path)
        root.iconphoto(True, img)
        root._icon = img  # keep a reference
    except tk.TclError:
        pass


def size_window(root: tk.Tk) -> None:
    """Sizes are design pixels: grow them with the screen scaling, never past the screen."""
    theme.set_scale(root.winfo_fpixels("1i"))
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w, h = min(px(theme.WINDOW[0]), sw), min(px(theme.WINDOW[1]), sh - px(48))
    root.geometry(f"{w}x{h}")
    root.minsize(min(px(theme.WINDOW_MIN[0]), sw), min(px(theme.WINDOW_MIN[1]), sh - px(48)))


def make_root() -> tk.Tk:
    _enable_dpi_awareness()
    root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()
    size_window(root)
    _icon(root)
    return root


def launch(paths: list[str] | None = None) -> None:
    root = make_root()
    App(root, paths)
    root.mainloop()
