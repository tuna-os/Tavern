# test_installed_page.py
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from gi.repository import Gtk, GLib
from tavern.installed_page import TavernInstalledPage
from tavern.backend import Package, BrewBackend
from tavern.task_manager import TaskManager
from tavern.package_tile import TavernPackageTile

def test_installed_page_refresh_and_actions(tmp_path, monkeypatch):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    backend = BrewBackend()
    task_manager = TaskManager(backend)
    
    # Mock fetch_icon_async
    mock_pixbuf = object()
    monkeypatch.setattr(backend, 'fetch_icon_async', lambda package, callback: callback(package, mock_pixbuf))
    
    page = TavernInstalledPage()
    
    # Test refresh with no backend
    page.refresh(None)
    
    # Cover line 62: _load_tile_icon without backend
    pkg_rg = Package({'name': 'ripgrep', 'desc': 'rg'}, 'formula', installed_set={'ripgrep'})
    tile_test = TavernPackageTile(pkg_rg)
    page._load_tile_icon(tile_test, pkg_rg)
    
    page.set_backend_and_manager(backend, task_manager)
    
    # Test _on_outdated_changed
    outdated_count = None
    page.connect('outdated-count-changed', lambda page, count: setattr(page, '_outdated_count', count))
    page._on_outdated_changed(backend, {'ripgrep': {}})
    assert getattr(page, '_outdated_count', None) == 1
    assert page.updates_card.get_visible() is True
    
    # Test refresh with no installed packages
    page.refresh(backend)
    assert page.installed_stack.get_visible_child_name() == 'empty'
    
    # Pre-populate installed packages in backend
    backend._formulae = [pkg_rg]
    
    # Test refresh with installed packages
    page.refresh(backend)
    assert page.installed_stack.get_visible_child_name() == 'content'
    
    # Verify flow box children
    tiles = []
    child = page.installed_flow.get_first_child()
    while child is not None:
        tiles.append(child)
        child = child.get_next_sibling()
    assert len(tiles) == 1
    
    # Test double refresh to trigger clearing flow
    page.refresh(backend)
    
    # Test tile event signals
    activated_pkgs = []
    install_reqs = []
    remove_reqs = []
    
    page.connect('package-activated', lambda page, pkg: activated_pkgs.append(pkg))
    page.connect('install-requested', lambda page, pkg: install_reqs.append(pkg))
    page.connect('remove-requested',  lambda page, pkg: remove_reqs.append(pkg))
    
    target_tile = page.installed_flow.get_first_child().get_child()
    assert isinstance(target_tile, TavernPackageTile)
    
    # Trigger clicked/activated
    page._on_tile_clicked(target_tile)
    assert len(activated_pkgs) == 1
    assert activated_pkgs[0] == pkg_rg
    
    # Trigger install requested
    page._on_tile_install_requested(target_tile)
    assert len(install_reqs) == 1
    assert install_reqs[0] == pkg_rg
    
    # Trigger remove requested
    page._on_tile_remove_requested(target_tile)
    assert len(remove_reqs) == 1
    assert remove_reqs[0] == pkg_rg
    
    # Test _on_updates_card_package_activated
    page._on_updates_card_package_activated(None, pkg_rg)
    assert len(activated_pkgs) == 2
    
    # Test _on_packages_loaded callback
    backend.emit('formulae-loaded', [])
