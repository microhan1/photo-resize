"""The start-up picture a one-file exe shows while it unpacks (build.bat: --splash
assets/splash.png). PyInstaller draws it before any Python runs; the program only has to
take it away: once the window is drawn (gui.launch), or at once when the CLI is going to
print instead (main). Run from Python there is no pyi_splash module and nothing happens.
"""
from __future__ import annotations


def close() -> None:
    """Close the start-up picture. Harmless when there is none (plain Python, an exe built
    without --splash, or a picture already closed): every failure is swallowed, because a
    missing picture must never stop the program or hide its own error message."""
    try:
        import pyi_splash  # exists only inside an exe built with --splash
    except Exception:
        return
    try:
        pyi_splash.close()
    except Exception:
        pass
