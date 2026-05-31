# test_search_page.py
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from gi.repository import Gtk, GLib
from tavern.search_page import TavernSearchPage
from tavern.backend import Package, BrewBackend
from tavern.package_tile import TavernPackageTile

def test_search_page_workflows(tmp_path, monkeypatch):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    backend = BrewBackend()
    
    # Mock backend methods
    pkg_rg = Package({'name': 'ripgrep', 'desc': 'rg'}, 'formula')
    pkg_fox = Package({'token': 'firefox', 'name': ['Firefox']}, 'cask')
    
    def mock_search(query, pkg_type=None):
        if query == 'empty':
            return []
        if pkg_type == 'formula':
            return [pkg_rg]
        if pkg_type == 'cask':
            return [pkg_fox]
        return [pkg_rg, pkg_fox]
        
    monkeypatch.setattr(backend, 'search', mock_search)
    
    # Simulate a valid mock pixbuf to cover tile.set_icon_pixbuf callback
    mock_pixbuf = object()
    monkeypatch.setattr(backend, 'fetch_icon_async', lambda pkg, cb: cb(pkg, mock_pixbuf))
    
    page = TavernSearchPage()
    
    # Test line 86 early-return without backend in _do_search
    page._do_search('rip')
    
    # Test line 77 early-return without backend in _load_tile_icon
    page._load_tile_icon(TavernPackageTile(pkg_rg), pkg_rg)
    
    page.set_backend(backend)
    
    # Test setting packages runs search if query exists
    page.search_entry.set_text('rip')
    page.set_packages([], [])
    
    # Test clear button
    page.clear_button.emit('clicked')
    assert page.search_entry.get_text() == ''
    assert page.search_stack.get_visible_child_name() == 'empty'
    
    # Test typing query triggers debounce timeout
    page.search_entry.set_text('rip')
    assert page.clear_button.get_visible() is True
    assert page._search_timeout is not None
    
    # Cancel previous timeout to prevent execution of standard source
    if page._search_timeout:
        GLib.source_remove(page._search_timeout)
        page._search_timeout = None
        
    # Trigger callback manually to cover _search_timeout_cb
    assert page._search_timeout_cb('rip') is False
    
    # Verify results
    assert page.search_stack.get_visible_child_name() == 'results'
    tiles = []
    child = page.results_flow.get_first_child()
    while child is not None:
        tiles.append(child)
        child = child.get_next_sibling()
    assert len(tiles) == 2
    
    # Test empty query path in _on_search_changed
    page.search_entry.set_text('')
    assert page.search_stack.get_visible_child_name() == 'empty'
    
    # Test search with no results
    page._do_search('empty')
    assert page.search_stack.get_visible_child_name() == 'no-results'
    
    # Test filters
    # Set text so filter trigger does search
    page.search_entry.set_text('rip')
    
    # Toggle to Formula
    monkeypatch.setattr(page.filter_formula, 'get_active', lambda: True)
    page._on_filter_changed(page.filter_formula)
    assert page._current_filter == 'formula'
    
    # Toggle to Cask
    monkeypatch.setattr(page.filter_cask, 'get_active', lambda: True)
    page._on_filter_changed(page.filter_cask)
    assert page._current_filter == 'cask'
    
    # Toggle to All
    monkeypatch.setattr(page.filter_all, 'get_active', lambda: True)
    page._on_filter_changed(page.filter_all)
    assert page._current_filter is None
    
    # Inactive button trigger path
    monkeypatch.setattr(page.filter_formula, 'get_active', lambda: False)
    page._on_filter_changed(page.filter_formula) # Should do nothing
    
    # Test tile event signals
    activated_pkgs = []
    install_reqs = []
    remove_reqs = []
    
    page.connect('package-activated', lambda page, pkg: activated_pkgs.append(pkg))
    page.connect('install-requested', lambda page, pkg: install_reqs.append(pkg))
    page.connect('remove-requested',  lambda page, pkg: remove_reqs.append(pkg))
    
    # Populate once more to get fresh tiles
    page._do_search('rip')
    target_tile = page.results_flow.get_first_child().get_child()
    
    page._on_tile_clicked(target_tile)
    assert len(activated_pkgs) == 1
    
    page._on_tile_install_requested(target_tile)
    assert len(install_reqs) == 1
    
    page._on_tile_remove_requested(target_tile)
    assert len(remove_reqs) == 1
