"""Start the built exe and time its start-up picture and its window (2026-11-10, splash work).

    python tools/measure_startup.py <exe> [<exe2> ...] [-n rounds=4] [--shot folder]

With two exes (before and after a change) the rounds alternate between them, so a machine
that gets busier or quieter during the measurement does not favour one of them.

- Each exe is copied into a fresh temporary folder, so its settings.json lands there and the
  user's own settings (next to their exe or in %APPDATA%) are never touched. APPDATA and TEMP
  point into that folder too; what a forced kill leaves behind (_MEI*) is removed with it.
- The internet is cut with a dead proxy (HTTP_PROXY=HTTPS_PROXY=http://127.0.0.1:9), so the
  update check cannot reach the tools server (global rule 8). netstat is sampled once the
  window is up: any remote address other than the dead proxy is reported.
- Only windows of this exe's own processes (the one-file loader and its child) are counted;
  a photo-resize window the user has open is not.
- A visible top-level window with a title bar (WS_CAPTION) is the program window; one
  without is the start-up picture (PyInstaller's splash is a Tk window titled "tk" with no
  caption, so a check that goes by title would mistake it for the program).
- Taskbar buttons: visible windows with no owner and without WS_EX_TOOLWINDOW.
- A run ends 1.5 s after the window is up and the picture is gone, or GRACE seconds after
  the window if the picture is still there ("left"). The whole machine's CPU use during the
  run is printed too, because other work on the machine stretches every number.
- Round 1 is the cold start right after the copy; the summary averages the rounds after it.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes

sys.stdout.reconfigure(encoding="utf-8")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.SetProcessDPIAware()

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CAPTION, WS_EX_TOOLWINDOW = 0x00C00000, 0x00000080
GW_OWNER = 4
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindow.restype = wintypes.HWND
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
DEAD_PROXY = "http://127.0.0.1:9"
SETTLE = 1.5  # seconds after window up and picture gone before the final look
GRACE = 10.0  # seconds after the window before a picture still there counts as left behind


class PE(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


def family(root_pid: int) -> set[int]:
    """root_pid and every descendant (the one-file loader starts the real program as a child)."""
    snap = kernel32.CreateToolhelp32Snapshot(2, 0)
    pe = PE()
    pe.dwSize = ctypes.sizeof(PE)
    parents = {}
    ok = kernel32.Process32FirstW(snap, ctypes.byref(pe))
    while ok:
        parents[pe.th32ProcessID] = pe.th32ParentProcessID
        ok = kernel32.Process32NextW(snap, ctypes.byref(pe))
    kernel32.CloseHandle(snap)
    found = {root_pid}
    grew = True
    while grew:
        grew = False
        for pid, parent in parents.items():
            if parent in found and pid not in found:
                found.add(pid)
                grew = True
    return found


def windows_of(pids: set[int]) -> list[dict]:
    """Visible top-level windows owned by these processes."""
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            style = user32.GetWindowLongW(hwnd, GWL_STYLE)
            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            out.append(dict(hwnd=hwnd, title=buf.value, pid=pid.value,
                            caption=(style & WS_CAPTION) == WS_CAPTION,
                            taskbar=not (ex & WS_EX_TOOLWINDOW) and not user32.GetWindow(hwnd, GW_OWNER),
                            size=(r.right - r.left, r.bottom - r.top)))
        return True

    user32.EnumWindows(cb, 0)
    return out


def shot(hwnd: int, path: str) -> None:
    """Grab the window as it is on screen (the splash is not DPI-aware, so PrintWindow would scale it wrong)."""
    from PIL import ImageGrab

    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    ImageGrab.grab((r.left, r.top, r.right, r.bottom), all_screens=True).save(path)


def print_window(hwnd: int, path: str) -> None:
    """Render the window itself (PrintWindow), so other windows lying over it do not show up.
    Used for the program window; the splash is grabbed from the screen instead (see shot)."""
    from PIL import Image

    gdi32 = ctypes.windll.gdi32
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    user32.PrintWindow(hwnd, mem, 2)  # PW_RENDERFULLCONTENT

    class BMI(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    bmi = BMI(ctypes.sizeof(BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1).save(path)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)


def remote_connections(pids: set[int]) -> list[str]:
    """Remote addresses of this exe's TCP connections, except the dead proxy."""
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
    found = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "TCP" and parts[-1].isdigit() and int(parts[-1]) in pids:
            if not parts[2].startswith("127.0.0.1:9"):
                found.append(f"{parts[2]} {parts[3]}")
    return found


def offline_env(base: dict) -> dict:
    env = dict(base)
    env.update(HTTPS_PROXY=DEAD_PROXY, HTTP_PROXY=DEAD_PROXY, https_proxy=DEAD_PROXY, http_proxy=DEAD_PROXY,
               NO_PROXY="", no_proxy="")
    return env


def _system_times() -> tuple[int, int]:
    """(idle, total) CPU time of the whole machine in 100 ns units."""
    idle, kern, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))

    def ft(f):
        return (f.dwHighDateTime << 32) | f.dwLowDateTime

    return ft(idle), ft(kern) + ft(user)


def measure(exe: str, shot_dir: str | None = None, limit: float = 60.0) -> dict:
    root = os.path.dirname(exe)
    tmp = os.path.join(root, "tmp")
    os.makedirs(tmp, exist_ok=True)
    env = offline_env(dict(os.environ, APPDATA=os.path.join(root, "appdata"), TEMP=tmp, TMP=tmp))
    idle0, total0 = _system_times()
    t0 = time.perf_counter()
    proc = subprocess.Popen([exe], env=env, cwd=root)
    res = dict(splash=None, window=None, splash_gone=None, tasks_max=0, tasks_after=None, leftover=None,
               title="", remote=[], mei=0, cpu=None)
    try:
        pids = family(proc.pid)
        last_family = 0.0
        while time.perf_counter() - t0 < limit:
            now = time.perf_counter() - t0
            if now - last_family > 0.1:
                pids = family(proc.pid)
                last_family = now
            ws = windows_of(pids)
            plain = [w for w in ws if not w["caption"]]
            main = [w for w in ws if w["caption"] and w["title"]]
            res["tasks_max"] = max(res["tasks_max"], sum(w["taskbar"] for w in ws))
            if plain and res["splash"] is None:
                res["splash"] = now
                res["splash_info"] = plain[0]
                if shot_dir:
                    time.sleep(0.15)
                    shot(plain[0]["hwnd"], os.path.join(shot_dir, "splash.png"))
            if main and res["window"] is None:
                res["window"] = now
                res["title"] = main[0]["title"]
                if shot_dir:  # what the window looks like the moment it is counted as up
                    print_window(main[0]["hwnd"], os.path.join(shot_dir, "window_first.png"))
            if res["window"] is not None and not plain and res["splash_gone"] is None:
                res["splash_gone"] = now
                if shot_dir and res["splash"] is not None:  # the window the moment the picture is gone
                    print_window(main[0]["hwnd"], os.path.join(shot_dir, "window_at_close.png"))
            if res["window"] is not None:
                done = res["splash_gone"] is not None and now - res["splash_gone"] > SETTLE
                if done or now - res["window"] > GRACE:
                    res["tasks_after"] = sum(w["taskbar"] for w in ws)
                    res["leftover"] = len(plain)
                    res["remote"] = remote_connections(pids)
                    if shot_dir:
                        print_window(main[0]["hwnd"], os.path.join(shot_dir, "window.png"))
                    break
            time.sleep(0.01)
        idle1, total1 = _system_times()
        if total1 > total0:
            res["cpu"] = 100.0 * (1 - (idle1 - idle0) / (total1 - total0))
        res["mei"] = len([d for d in os.listdir(tmp) if d.startswith("_MEI")])
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        time.sleep(1.0)
        shutil.rmtree(tmp, ignore_errors=True)  # whatever the forced kill left (_MEI*) is only in here
    return res


def fmt(v) -> str:
    return f"{v:.2f}" if isinstance(v, float) else "-"


def main() -> int:
    args = sys.argv[1:]
    shot_dir = None
    if "--shot" in args:
        i = args.index("--shot")
        shot_dir = args[i + 1]
        os.makedirs(shot_dir, exist_ok=True)
        del args[i:i + 2]
    n = 4
    if "-n" in args:
        i = args.index("-n")
        n = int(args[i + 1])
        del args[i:i + 2]
    sources = args
    labels = [chr(ord("A") + k) for k in range(len(sources))]
    roots, exes = [], []
    for src in sources:
        root = tempfile.mkdtemp(prefix="photo_resize_measure_")
        exe = os.path.join(root, os.path.basename(src))
        shutil.copy2(src, exe)
        roots.append(root)
        exes.append(exe)
    for label, src, root in zip(labels, sources, roots):
        print(f"{label}: {src}  ({os.path.getsize(src) / 1024 / 1024:.2f} MB)  copied to {root}")
    print("exe | round | splash (s) | window (s) | splash gone (s) | taskbar max | taskbar after | splash left"
          " | _MEI | remote | CPU %")
    rows: dict[str, list] = {label: [] for label in labels}
    try:
        for k in range(1, n + 1):
            for label, exe in zip(labels, exes):
                sd = os.path.join(shot_dir, label) if shot_dir and k == 2 else None
                if sd:
                    os.makedirs(sd, exist_ok=True)
                r = measure(exe, sd)
                rows[label].append(r)
                print(f"{label} | {k} | {fmt(r['splash'])} | {fmt(r['window'])} | {fmt(r['splash_gone'])} | "
                      f"{r['tasks_max']} | {r['tasks_after']} | {r['leftover']} | {r['mei']} | {r['remote'] or 0}"
                      f" | {fmt(r['cpu'])}", flush=True)
                if k == 1:
                    print(f"   window title: {r['title']!r}", flush=True)
                    if r.get("splash_info"):
                        print("   splash window:", {k2: r["splash_info"][k2] for k2 in ("title", "taskbar", "size")},
                              flush=True)
    finally:
        for root in roots:
            shutil.rmtree(root, ignore_errors=True)
    for label in labels:
        win = [r["window"] for r in rows[label][1:] if r["window"]]
        spl = [r["splash"] for r in rows[label][1:] if r["splash"]]
        gone = [r["splash_gone"] - r["window"] for r in rows[label][1:] if r["splash_gone"] and r["window"]]
        if win:
            print(f"{label} average from round 2: window {sum(win) / len(win):.2f} s"
                  + (f" / splash {sum(spl) / len(spl):.2f} s" if spl else " / no splash")
                  + (f" / picture closes {sum(gone) / len(gone):.2f} s after the window" if gone and spl else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
