# test_brewfile_page.py
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from gi.repository import Gtk, GLib, Adw
from tavern.brewfile_page import TavernBrewfilePage
from tavern.backend import Package, BrewBackend
from tavern.task_manager import TaskManager
from tavern.package_tile import TavernPackageTile

# ─── Mock Helpers ─────────────────────────────────────────────────────────────

class MockFuture:
    def __init__(self, res):
        self._res = res
    def result(self):
        return self._res

class SynchronousExecutor:
    def __init__(self, max_workers=None):
        pass
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
    def submit(self, fn, *args, **kwargs):
        res = fn(*args, **kwargs)
        return MockFuture(res)

class SynchronousThread:
    def __init__(self, target, args=(), kwargs={}, daemon=True):
        self.target = target
        self.args = args
        self.kwargs = kwargs
    
    def start(self):
        self.target(*self.args, **self.kwargs)

class MockCompletedProcess:
    def __init__(self, returncode=0, stdout='', stderr=''):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

# ─── Tests ────────────────────────────────────────────────────────────────────

def test_brewfile_page_workflows(tmp_path, monkeypatch):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    # 1. Setup Mocking for synchronous test execution
    monkeypatch.setattr('tavern.brewfile_page.ThreadPoolExecutor', SynchronousExecutor)
    monkeypatch.setattr('tavern.brewfile_page.as_completed', lambda futures: list(futures))
    monkeypatch.setattr(threading, 'Thread', SynchronousThread)
    
    # Executing GLib.idle_add synchronously
    def mock_idle_add(callback, *args, **kwargs):
        callback(*args, **kwargs)
        return False
    monkeypatch.setattr(GLib, 'idle_add', mock_idle_add)
    
    # Prevent graphical MessageDialogs from popping up on the user's desktop
    monkeypatch.setattr(Adw.MessageDialog, 'present', lambda self: None)
    
    # Mock subprocess runs
    subprocess_calls = []
    def mock_subprocess_run(args, **kwargs):
        subprocess_calls.append(args)
        if 'tap' in args:
            if 'fail-tap' in args:
                return MockCompletedProcess(1, '', 'Failed to tap')
            return MockCompletedProcess(0, 'Tapped successfully', '')
        return MockCompletedProcess(0, 'Done', '')
    
    monkeypatch.setattr('tavern.brewfile_page.subprocess.run', mock_subprocess_run)
    monkeypatch.setattr('tavern.brewfile_page.subprocess.Popen', lambda args, **kwargs: subprocess_calls.append(args))
    
    # 2. Setup Tavern Backend and Task Manager
    backend = BrewBackend()
    task_manager = TaskManager(backend)
    
    # Mock Backend methods to return mock packages
    mock_pkg_f = Package({'name': 'ripgrep', 'desc': 'rg'}, 'formula')
    mock_pkg_c = Package({'token': 'firefox', 'name': ['Firefox'], 'desc': 'browser'}, 'cask')
    
    backend._formulae = [mock_pkg_f]
    backend._casks = [mock_pkg_c]
    
    # Mock parse_brewfile
    def mock_parse(path):
        return {
            'taps': ['homebrew/cask-fonts', 'fail-tap'],
            'formulae': ['ripgrep', 'wget'],
            'casks': ['firefox', 'iterm2'],
            'flatpaks': ['org.mozilla.firefox', 'fail-flatpak']
        }
    monkeypatch.setattr(backend, 'parse_brewfile', mock_parse)
    
    # Mock get_flatpak_info
    def mock_get_flatpak_info(app_id):
        if app_id == 'fail-flatpak':
            raise Exception('Flathub API Error')
        return {
            'id': app_id,
            'name': 'Firefox Flatpak',
            'summary': 'Mozilla Firefox',
            'urls': {'homepage': 'https://firefox.org'}
        }
    monkeypatch.setattr(backend, 'get_flatpak_info', mock_get_flatpak_info)
    
    # Mock get_package_info
    def mock_get_package_info(name, pkg_type):
        if name == 'wget':
            return {'name': 'wget', 'desc': 'GNU wget', 'versions': {'stable': '1.21'}}
        if name == 'iterm2':
            return None # Trigger None metadata fallback
        raise Exception('API error') # Trigger Exception metadata fallback

    monkeypatch.setattr(backend, 'get_package_info', mock_get_package_info)
    
    # Mock fetch_icon_async
    def mock_fetch_icon(pkg, callback):
        callback(pkg, object()) # Return dummy pixbuf
    monkeypatch.setattr(backend, 'fetch_icon_async', mock_fetch_icon)
    
    # 3. Instantiate Brewfile Page
    page = TavernBrewfilePage()
    page.set_backend_and_manager(backend, task_manager)
    
    # Load brewfile path
    dummy_brewfile = tmp_path / 'my.Brewfile'
    dummy_brewfile.write_text('tap "homebrew/cask-fonts"\nbrew "ripgrep"\ncask "firefox"\n')
    
    page.load_brewfile(str(dummy_brewfile))
    
    # 4. Verify Loaded Data & UI State
    assert page.parsed_data is not None
    assert len(page._packages) == 6 # ripgrep, wget, firefox, iterm2, firefox flatpak, fail-flatpak
    
    # Verify taps were added to taps_flow
    taps_in_flow = []
    child = page.taps_flow.get_first_child()
    while child is not None:
        taps_in_flow.append(child)
        child = child.get_next_sibling()
    assert len(taps_in_flow) == 2
    
    # Verify formulae, casks, and flatpaks tiles are created
    formula_tiles = []
    child = page.formulae_flow.get_first_child()
    while child is not None:
        formula_tiles.append(child)
        child = child.get_next_sibling()
    assert len(formula_tiles) == 2
    
    cask_tiles = []
    child = page.casks_flow.get_first_child()
    while child is not None:
        cask_tiles.append(child)
        child = child.get_next_sibling()
    assert len(cask_tiles) == 2
    
    flatpak_tiles = []
    child = page.flatpaks_flow.get_first_child()
    while child is not None:
        flatpak_tiles.append(child)
        child = child.get_next_sibling()
    assert len(flatpak_tiles) == 2
    
    # 5. Verify Click Actions & Dialog Popups
    activated_pkgs = []
    install_reqs = []
    page.connect('package-activated', lambda page, pkg: activated_pkgs.append(pkg))
    page.connect('install-requested', lambda page, pkg: install_reqs.append(pkg))
    
    # Test formula tile activation & install signals
    rg_tile = formula_tiles[0].get_child()
    page._on_tile_clicked(rg_tile)
    assert len(activated_pkgs) == 1
    assert activated_pkgs[0].name == 'ripgrep'
    
    page._on_tile_install_requested(rg_tile)
    assert len(install_reqs) == 1
    assert install_reqs[0].name == 'ripgrep'
    
    # Test flatpak tile clicked (routes to open in Bazaar)
    flatpak_tile = flatpak_tiles[0].get_child()
    page._on_tile_clicked(flatpak_tile)
    # Check that xdg-open was popped
    assert any('appstream://org.mozilla.firefox' in c for c in subprocess_calls)
    
    # Test click on failed tap
    # Manually trigger `_on_tap_clicked` for 'fail-tap'
    # We first need to mock page.get_root() to return a mock window
    mock_window = Gtk.Window()
    monkeypatch.setattr(page, 'get_root', lambda: mock_window)
    
    # Verify warning tooltip is set for failed tap
    assert page._tap_errors['fail-tap'] == 'Failed to tap'
    page._on_tap_clicked('fail-tap')
    
    # Click on success tap should not show dialog
    page._on_tap_clicked('homebrew/cask-fonts')
    
    # 6. Test Install All
    page._on_install_all_clicked(None)
    # Assert that brew bundle command was run
    assert any('bundle' in c for c in subprocess_calls)
    
    # 7. Test Remove All
    page._on_remove_all_clicked(None)
    # Assert that uninstall commands were run
    assert any('uninstall' in c for c in subprocess_calls)
    assert any('flatpak' in c and 'uninstall' in c for c in subprocess_calls)

def test_brewfile_page_empty_load(tmp_path, monkeypatch):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    backend = BrewBackend()
    task_manager = TaskManager(backend)
    monkeypatch.setattr(backend, 'parse_brewfile', lambda p: None)
    
    page = TavernBrewfilePage()
    page.set_backend_and_manager(backend, task_manager)
    
    page.load_brewfile('/nonexistent.Brewfile')
    assert len(page._packages) == 0
    
    # Install / remove on empty parsed data
    page._on_install_all_clicked(None)
    page._on_remove_all_clicked(None)
