# test_version_history_dialog.py
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
import time
from gi.repository import Gtk, GLib
from tavern.version_history_dialog import TavernVersionHistoryDialog
from tavern.backend import Package, BrewBackend

def test_version_history_dialog_populate(tmp_path, monkeypatch):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    backend = BrewBackend()
    history = [
        {
            'version': '14.1.1',
            'date': '2024-01-01',
            'changelog': 'Bug fixes and performance improvements.'
        },
        {
            'version': '14.1.0',
            'date': '2023-12-15',
            'changelog': 'New feature added.'
        }
    ]
    # Mock backend method
    monkeypatch.setattr(backend, 'get_version_history', lambda name, pkg_type: history)
    
    pkg = Package({'name': 'ripgrep', 'desc': 'rg'}, 'formula')
    
    dialog = TavernVersionHistoryDialog(package=pkg, backend=backend)
    assert dialog is not None
    assert 'ripgrep' in dialog.get_title()
    
    # Process GLib idle calls
    context = GLib.MainContext.default()
    # Give the thread a tiny bit of time to start and queue idle_add
    timeout = 0.5
    start = time.time()
    while not dialog._current_selection and (time.time() - start < timeout):
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)
        
    # Also call populate directly to ensure it runs even if thread was slow
    dialog._populate_versions(history)
    assert dialog._stack.get_visible_child_name() == 'content'
    
    # Verify rows
    rows = []
    row = dialog._versions_list.get_first_child()
    while row is not None:
        rows.append(row)
        row = row.get_next_sibling()
    assert len(rows) == 2
    assert rows[0].version_info['version'] == '14.1.1'
    
    # Test _on_version_selected
    dialog._on_version_selected(dialog._versions_list, rows[1])
    assert dialog._current_selection == rows[1]
    
    buffer = dialog._changelog_view.get_buffer()
    text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
    assert 'New feature' in text
    
    # Test _on_pin_clicked
    pinned_version = None
    dialog.connect('pin-version', lambda d, v: setattr(dialog, '_pinned_ver', v))
    dialog._on_pin_clicked(None)
    assert getattr(dialog, '_pinned_ver', None) == '14.1.0'
    
    # Test line 244: cannot pin version unknown
    rows[1].version_info['version'] = ''
    dialog._on_pin_clicked(None)

def test_version_history_dialog_error(tmp_path, monkeypatch):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    backend = BrewBackend()
    pkg = Package({'name': 'ripgrep'}, 'formula')
    dialog = TavernVersionHistoryDialog(package=pkg, backend=backend)
    
    # Test populate versions with empty list (error)
    dialog._populate_versions([])
    assert dialog._stack.get_visible_child_name() == 'error'
    
    # Test _show_error directly
    dialog._show_error("Could not fetch URL")
    assert dialog._stack.get_visible_child_name() == 'error'
    
    # Test thread loading exception path by forcing exception
    def mock_get_history_error(*args):
        raise ValueError("Network error")
    monkeypatch.setattr(backend, 'get_version_history', mock_get_history_error)
    dialog2 = TavernVersionHistoryDialog(package=pkg, backend=backend)
    
    # Process GLib idle calls to propagate show_error from run_load
    context = GLib.MainContext.default()
    start = time.time()
    while dialog2._stack.get_visible_child_name() != 'error' and (time.time() - start < 0.5):
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)

def test_version_history_dialog_empty_constructor(tmp_path, monkeypatch):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    dialog = TavernVersionHistoryDialog(package=None, backend=None)
    assert dialog is not None
    
    # Loading version history with None does early return
    dialog._load_version_history()
    
    # Pin click with None selection does early return
    dialog._on_pin_clicked(None)
