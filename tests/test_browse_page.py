# test_browse_page.py
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from gi.repository import Gtk, GLib
from tavern.browse_page import TavernBrowsePage
from tavern.backend import Package, BrewBackend
from tavern.package_tile import TavernPackageTile

def test_browse_page_populating_and_actions(tmp_path, monkeypatch):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    backend = BrewBackend()
    
    # Mock backend.fetch_icon_async to trigger icon callback immediately
    mock_pixbuf = object()
    def mock_fetch_icon_async(package, callback):
        callback(package, mock_pixbuf)
    monkeypatch.setattr(backend, 'fetch_icon_async', mock_fetch_icon_async)
    
    page = TavernBrowsePage()
    
    # Cover line 70: _load_tile_icon without backend
    tile_test = TavernPackageTile(Package({'name': 'test'}, 'formula'))
    page._load_tile_icon(tile_test, tile_test.get_package())
    
    page.set_backend(backend)
    
    # Test set_loading
    page.set_loading()
    assert page.browse_stack.get_visible_child_name() == 'loading'
    
    # Populate casks and formulae
    packages_f = [
        Package({'name': 'git', 'desc': 'git'}, 'formula'),
        Package({'name': 'ripgrep', 'desc': 'rg'}, 'formula'),
        Package({'name': 'otherpkg', 'desc': 'other'}, 'formula'),
    ]
    packages_c = [
        Package({'token': 'firefox', 'name': ['Firefox']}, 'cask'),
        Package({'token': 'zoom', 'name': ['Zoom']}, 'cask'),
    ]
    
    page.populate_casks(packages_c)
    assert page.browse_stack.get_visible_child_name() == 'content'
    
    page.populate_formulae(packages_f)
    assert page.browse_stack.get_visible_child_name() == 'content'
    
    # Verify popular flow layout children
    formula_tiles = []
    child = page.popular_flow.get_first_child()
    while child is not None:
        formula_tiles.append(child)
        child = child.get_next_sibling()
    assert len(formula_tiles) == 3
    
    # Verify recent flow layout children
    recent_tiles = []
    child = page.recent_flow.get_first_child()
    while child is not None:
        recent_tiles.append(child)
        child = child.get_next_sibling()
    assert len(recent_tiles) == 3
    
    # Test line 79 & 106: Populate again to trigger clearing loops
    page.populate_casks(packages_c)
    page.populate_formulae(packages_f)
    
    # Test tile event signals
    activated_pkgs = []
    install_reqs = []
    remove_reqs = []
    
    page.connect('package-activated', lambda page, pkg: activated_pkgs.append(pkg))
    page.connect('install-requested', lambda page, pkg: install_reqs.append(pkg))
    page.connect('remove-requested',  lambda page, pkg: remove_reqs.append(pkg))
    
    # FlowBox wraps the TavernPackageTile inside a FlowBoxChild, so we unwrap it
    target_tile = page.popular_flow.get_first_child().get_child()
    assert isinstance(target_tile, TavernPackageTile)
    
    # Trigger clicked/activated
    page._on_tile_clicked(target_tile)
    assert len(activated_pkgs) == 1
    assert activated_pkgs[0] == target_tile.get_package()
    
    # Trigger install requested
    page._on_tile_install_requested(target_tile)
    assert len(install_reqs) == 1
    assert install_reqs[0] == target_tile.get_package()
    
    # Trigger remove requested
    page._on_tile_remove_requested(target_tile)
    assert len(remove_reqs) == 1
    assert remove_reqs[0] == target_tile.get_package()

def test_browse_page_empty_recent(tmp_path, monkeypatch):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    page = TavernBrowsePage()
    
    # Populating recent with empty list should return early and not crash
    page._fill_recent([])
    assert page.recent_flow.get_first_child() is None
