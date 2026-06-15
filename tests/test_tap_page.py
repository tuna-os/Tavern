# test_tap_page.py
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from gi.repository import Gtk, GLib, Adw
from tavern.tap_page import TavernTapPage, _fetch_avatar_pixbuf
from tavern.backend import Package, BrewBackend
from tavern.package_tile import TavernPackageTile

def test_avatar_fetch_handling(monkeypatch):
    # Mock urlopen to raise an exception to cover exception path
    import urllib.request
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *args, **kwargs: exec("raise ValueError('mock error')"))
    assert _fetch_avatar_pixbuf('testuser') is None

def test_tap_page_workflows(tmp_path, monkeypatch):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    # Mock Adw.AlertDialog.present to prevent crash in headless testing
    monkeypatch.setattr(Adw.AlertDialog, 'present', lambda *args: None)
    
    backend = BrewBackend()
    
    # Mock backend async methods
    monkeypatch.setattr(backend, 'fetch_icon_async', lambda pkg, cb: cb(pkg, None))
    monkeypatch.setattr(backend, 'fetch_popular_taps_async', lambda cb: cb([
        {'name': 'homebrew/cask-fonts', 'gh_user': 'homebrew', 'desc': 'Fonts!'},
        {'name': 'already/tapped', 'gh_user': 'already', 'desc': 'Already'}
    ]))
    monkeypatch.setattr(backend, 'check_tap_trust_async', lambda name, cb: cb(True))
    
    tapped_name = None
    untapped_name = None
    monkeypatch.setattr(backend, 'tap_async', lambda name, cb: setattr(backend, '_tap_cb', (name, cb)))
    monkeypatch.setattr(backend, 'untap_async', lambda name, cb: setattr(backend, '_untap_cb', (name, cb)))
    
    page = TavernTapPage()
    
    # Cover line 410: _load_tile_icon without backend
    pkg_rg = Package({'name': 'ripgrep', 'desc': 'rg'}, 'formula')
    page._load_tile_icon(TavernPackageTile(pkg_rg), pkg_rg)
    
    page.set_backend(backend)
    
    # Emit taps loaded (no taps path)
    backend.emit('taps-loaded', {})
    assert page.tap_page_stack.get_visible_child_name() == 'no-taps'
    
    # Emit taps loaded with 1 tap (populated path)
    pkg_rg = Package({'name': 'ripgrep', 'desc': 'rg'}, 'formula')
    taps_data = {
        'homebrew/cask-fonts': [pkg_rg],
        'already/tapped': []
    }
    backend.emit('taps-loaded', taps_data)
    assert page.tap_page_stack.get_visible_child_name() == 'content'
    
    # Verify rows
    rows = []
    row = page.tap_list.get_first_child()
    while row is not None:
        rows.append(row)
        row = row.get_next_sibling()
    assert len(rows) == 2
    
    # Trigger row selected
    page._on_tap_row_selected(page.tap_list, rows[0])
    assert page._selected_tap == 'already/tapped' # Sorted order
    assert page.remove_tap_button.get_sensitive() is True
    
    # Trigger row selected with None
    page._on_tap_row_selected(page.tap_list, None)
    assert page._selected_tap is None
    assert page.remove_tap_button.get_sensitive() is False
    
    # Select first row again
    page._on_tap_row_selected(page.tap_list, rows[0])
    
    # Test tile event signals
    activated_pkgs = []
    install_reqs = []
    remove_reqs = []
    page.connect('package-activated', lambda page, pkg: activated_pkgs.append(pkg))
    page.connect('install-requested', lambda page, pkg: install_reqs.append(pkg))
    page.connect('remove-requested',  lambda page, pkg: remove_reqs.append(pkg))
    
    # Re-select row 1 (which contains ripgrep)
    page._on_tap_row_selected(page.tap_list, rows[1])
    target_tile = page.packages_flow.get_first_child().get_child()
    
    page._on_tile_clicked(target_tile)
    assert len(activated_pkgs) == 1
    
    page._on_tile_install_requested(target_tile)
    assert len(install_reqs) == 1
    
    page._on_tile_remove_requested(target_tile)
    assert len(remove_reqs) == 1
    
    # Test add tap clicked to verify dialog creation
    page._on_add_tap_clicked(None)
    
    # Test add tap dialog response
    # 1. response is cancel (should do nothing)
    page._on_add_dialog_response(None, 'cancel', lambda: 'test/tap')
    # 2. response is add, invalid name
    invalid_called = False
    page.connect('tap-operation', lambda page, msg: setattr(page, '_last_op', msg))
    page._on_add_dialog_response(None, 'add', lambda: 'invalid_tap_name')
    assert 'Invalid' in page._last_op
    
    # 3. response is add, valid name
    page._on_add_dialog_response(None, 'add', lambda: 'test/tap')
    assert 'Adding tap test/tap' in page._last_op
    
    # Trigger tap_async callback
    assert backend._tap_cb is not None
    name, cb = backend._tap_cb
    assert name == 'test/tap'
    # Trigger successful cb
    cb(True, 'Success')
    assert 'Added tap test/tap' in page._last_op
    # Trigger failed cb
    cb(False, 'Failed output\nerror log')
    assert 'Failed to add tap: Failed output' in page._last_op
    
    # Test remove tap
    page._selected_tap = 'test/tap'
    page._on_remove_tap_clicked(None)
    
    # Trigger remove response
    page._on_remove_tap_response(None, 'cancel', 'test/tap')
    page._on_remove_tap_response(None, 'remove', 'test/tap')
    assert 'Removing tap test/tap' in page._last_op
    
    # Trigger untap_async callback
    assert backend._untap_cb is not None
    name, cb = backend._untap_cb
    assert name == 'test/tap'
    # Trigger successful cb
    cb(True, 'Success')
    assert 'Removed tap test/tap' in page._last_op
    # Trigger failed cb
    cb(False, 'Untap failed\nerror')
    assert 'Failed to remove tap: Untap failed' in page._last_op
