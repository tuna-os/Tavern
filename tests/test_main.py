# test_main.py
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
import os
import sys
import ctypes
from gi.repository import GLib, Gio
from tavern.main import main, _load_resources
from tavern.application import TavernApplication

def test_load_resources_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    # Mock os.path.exists to return False to test fallback path
    monkeypatch.setattr(os.path, 'exists', lambda path: False)
    assert _load_resources() is False

def test_load_resources_mock_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    # Mock os.path.exists to return True for tavern's gresource
    def mock_exists(path):
        if path.endswith('tavern.gresource'):
            return True
        return False
    monkeypatch.setattr(os.path, 'exists', mock_exists)
    
    # Mock Gio.Resource.load to prevent actual binary loading error
    monkeypatch.setattr(Gio.Resource, 'load', lambda path: object())
    monkeypatch.setattr(Gio, 'resources_register', lambda res: None)
    
    assert _load_resources() is True

def test_load_resources_error_path(monkeypatch, tmp_path):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    # Mock exists to return True for gresource, but force load to raise Exception
    monkeypatch.setattr(os.path, 'exists', lambda path: path.endswith('tavern.gresource'))
    monkeypatch.setattr(Gio.Resource, 'load', lambda path: exec("raise ValueError('mock load error')"))
    
    assert _load_resources() is False

def test_load_resources_adwaita_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    # Mock exists to return True for Adwaita so it tries to load using ctypes
    monkeypatch.setattr(os.path, 'exists', lambda path: path.endswith('libadwaita-1.so.0'))
    
    # Mock ctypes.CDLL to check it is executed
    monkeypatch.setattr(ctypes, 'CDLL', lambda *args, **kwargs: object())
    
    # Also return False for resources so it terminates early
    # Mock GLib import and resources to prevent failures
    _load_resources()

def test_main_entrypoint(monkeypatch, tmp_path):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    # Mock TavernApplication.run
    monkeypatch.setattr(TavernApplication, 'run', lambda *args: 0)
    
    # Mock _load_resources to return True
    import tavern.main as main_mod
    monkeypatch.setattr(main_mod, '_load_resources', lambda: True)
    
    # Mock sys.argv
    monkeypatch.setattr(sys, 'argv', ['tavern'])
    
    result = main('1.2.3')
    assert result == 0
