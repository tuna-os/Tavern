# test_brewfile_dialog.py
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from gi.repository import Gtk, GLib
from tavern.brewfile_dialog import TavernBrewfileDialog
from tavern.backend import Package, BrewBackend
from tavern.task_manager import TaskManager

class MockWindow:
    def __init__(self, backend, task_manager):
        self.backend = backend
        self.task_manager = task_manager

def test_brewfile_dialog_load_and_populate(tmp_path, monkeypatch):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    backend = BrewBackend()
    # Mock parse_brewfile
    def mock_parse(path):
        return {
            'taps': ['homebrew/cask-fonts'],
            'formulae': ['ripgrep', 'wget'],
            'casks': ['firefox', 'iterm2'],
            'flatpaks': []
        }
    monkeypatch.setattr(backend, 'parse_brewfile', mock_parse)
    
    # Pre-populate some formula and cask in backend to hit existing pkg path
    pkg_rg = Package({'name': 'ripgrep', 'desc': 'rg'}, 'formula', installed_set={'ripgrep'})
    pkg_fox = Package({'token': 'firefox', 'name': ['Firefox']}, 'cask', installed_set={'firefox'})
    backend._formulae = [pkg_rg]
    backend._casks = [pkg_fox]
    
    task_manager = TaskManager(backend)
    # Mock task manager install/remove methods
    installed_pkgs = []
    removed_pkgs = []
    monkeypatch.setattr(task_manager, 'install', lambda p: installed_pkgs.append(p))
    monkeypatch.setattr(task_manager, 'remove', lambda p: removed_pkgs.append(p))
    
    window = MockWindow(backend, task_manager)
    dialog = TavernBrewfileDialog(window)
    
    assert dialog is not None
    dialog.load_brewfile('/path/to/my.Brewfile')
    
    assert dialog.get_title() == 'Brewfile: my.Brewfile'
    # There should be 5 rows: 1 tap + 2 formulae + 2 casks
    # Let's count them
    rows = []
    row = dialog.list_box.get_first_child()
    while row is not None:
        rows.append(row)
        row = row.get_next_sibling()
    
    assert len(rows) == 5
    
    # Assert _packages list got filled (ripgrep, wget, firefox, iterm2)
    assert len(dialog._packages) == 4
    
    # Test _on_install_all_clicked (should only install not-installed: wget, iterm2)
    dialog._on_install_all_clicked(None)
    assert len(installed_pkgs) == 2
    assert any(p.name == 'wget' for p in installed_pkgs)
    assert any(p.name == 'iterm2' for p in installed_pkgs)
    
    # Re-instantiate to test remove all
    dialog2 = TavernBrewfileDialog(window)
    dialog2.load_brewfile('/path/to/my.Brewfile')
    
    # Test _on_remove_all_clicked (should only remove installed: ripgrep, firefox)
    dialog2._on_remove_all_clicked(None)
    assert len(removed_pkgs) == 2
    assert any(p.name == 'ripgrep' for p in removed_pkgs)
    assert any(p.name == 'firefox' for p in removed_pkgs)
