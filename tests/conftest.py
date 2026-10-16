from __future__ import annotations

import hashlib
import os
import socket
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "samples"))

import i18n  # noqa: E402
import update_check as _uc  # noqa: E402

# ---- No test ever reaches the real tools server or any other host (global rule §8: one
# full pytest run of photo-organizer sent 51 requests to chaekgalpi.co.kr through the GUI
# tests' App; 511 hits in two days). fetch() binds opener=urlopen and check_async() binds
# fetcher=fetch at definition time, so the defaults themselves are replaced, not only the
# module attributes; urlopen and socket connections are refused as a second line.
attempts: list[str] = []  # every outside call a test tried, for this test
total_attempts: list[str] = []  # for the whole run (printed at the end, must be 0)


def _no_fetch(slug, version):
    """What every App gets instead of fetch(): the server did not answer."""
    return None


def _no_network(req, timeout=None, *a, **k):
    import urllib.error

    url = req.full_url if hasattr(req, "full_url") else str(req)
    attempts.append(url)
    total_attempts.append(url)
    raise urllib.error.URLError("blocked by tests/conftest.py: tests never reach a server")


def _is_local(address) -> bool:
    host = address[0] if isinstance(address, tuple) and address else str(address)
    return host in ("127.0.0.1", "::1", "localhost")


_real_connect = socket.socket.connect
_real_create_connection = socket.create_connection


def _guard_connect(self, address):
    if not _is_local(address):
        attempts.append(f"socket {address}")
        total_attempts.append(f"socket {address}")
        raise OSError("blocked by tests/conftest.py: no outside connections in tests")
    return _real_connect(self, address)


def _guard_create_connection(address, *a, **k):
    if not _is_local(address):
        attempts.append(f"socket {address}")
        total_attempts.append(f"socket {address}")
        raise OSError("blocked by tests/conftest.py: no outside connections in tests")
    return _real_create_connection(address, *a, **k)


@pytest.fixture(autouse=True)
def no_outside_calls(monkeypatch):
    import urllib.request

    monkeypatch.setitem(_uc.check_async.__kwdefaults__, "fetcher", _no_fetch)
    monkeypatch.setitem(_uc.fetch.__kwdefaults__, "opener", _no_network)
    monkeypatch.setattr(urllib.request, "urlopen", _no_network)
    monkeypatch.setattr(socket.socket, "connect", _guard_connect)
    monkeypatch.setattr(socket, "create_connection", _guard_create_connection)
    attempts.clear()
    yield
    assert not attempts, f"a test tried to reach a server: {attempts}"


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path_factory, monkeypatch):
    """Every test gets its own settings.json (never the user's, never the repo's) and English."""
    path = str(tmp_path_factory.mktemp("settings") / "settings.json")
    monkeypatch.setattr(i18n, "_settings_path", path)
    monkeypatch.setenv(i18n.SETTINGS_ENV, path)
    i18n.set_lang("en", persist=False)
    yield path


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    terminalreporter.write_line(f"outside calls attempted during the run: {len(total_attempts)} (blocked)")


def pytest_sessionfinish(session, exitstatus):
    if total_attempts and session.exitstatus == 0:
        session.exitstatus = 1


def sha1(path) -> str:
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


def snapshot(root) -> dict:
    """Every file under root with its SHA-1 and modified time."""
    out = {}
    for here, dirs, files in os.walk(str(root)):
        for name in files:
            p = os.path.join(here, name)
            out[os.path.relpath(p, str(root))] = (sha1(p), os.stat(p).st_mtime_ns)
    return out


def files_under(root) -> list[str]:
    out = []
    for here, dirs, files in os.walk(str(root)):
        for name in files:
            out.append(os.path.relpath(os.path.join(here, name), str(root)).replace(os.sep, "/"))
    return sorted(out)
