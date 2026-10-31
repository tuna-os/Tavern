"""Contracts for the transport shared by backend leaves."""

import subprocess
import sys
from pathlib import Path
from urllib.request import Request

import pytest

from tavern import backend_transport, brew_env


def test_transport_import_does_not_load_composition_root_or_gtk():
    # A fresh interpreter catches transitive imports hidden by test collection.
    source_dir = Path(__file__).parents[1]
    subprocess.run([
        sys.executable, '-c',
        'import sys; from src import backend_transport; '
        'assert "src.backend" not in sys.modules; '
        'assert "gi" not in sys.modules',
    ], cwd=source_dir, check=True)


def test_command_uses_refreshed_environment(monkeypatch):
    monkeypatch.setattr(brew_env, 'IN_FLATPAK', False)
    monkeypatch.setattr(brew_env, 'BREW_BIN', '/first/brew')
    assert backend_transport._brew_cmd(['list']) == ['/first/brew', 'list']
    monkeypatch.setattr(brew_env, 'BREW_BIN', '/new/brew')
    assert backend_transport._brew_cmd(['list']) == ['/new/brew', 'list']


def test_media_rejects_unsafe_url_before_opening(monkeypatch):
    calls = []
    monkeypatch.setattr(backend_transport._MEDIA_OPENER, 'open',
                        lambda *a, **kw: calls.append((a, kw)))
    with pytest.raises(ValueError):
        backend_transport.media_urlopen(Request('http://127.0.0.1/secret'))
    assert calls == []
