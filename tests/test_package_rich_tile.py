# test_package_rich_tile.py
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from gi.repository import Gtk
from tavern.package_rich_tile import TavernRichPackageTile
from tavern.backend import Package

def test_rich_tile_formula():
    pkg = Package({
        'name': 'ripgrep',
        'desc': 'Fast search tool',
    }, 'formula')
    
    tile = TavernRichPackageTile(pkg)
    assert tile is not None
    assert tile.name_label.get_text() == 'ripgrep'
    assert tile.short_desc.get_text() == 'Fast search tool'
    assert tile.type_badge.get_text() == 'formula'
    assert tile.install_button.get_label() == 'Get'
    assert tile.install_button.get_visible() is True
    
    # Test clicked signals
    clicked_called = False
    install_req_called = False
    
    def on_clicked(t):
        nonlocal clicked_called
        clicked_called = True
        
    def on_install_req(t, p):
        nonlocal install_req_called
        install_req_called = True
        assert p == pkg
        
    tile.connect('clicked', on_clicked)
    tile.connect('install-requested', on_install_req)
    
    # Trigger install button click (not installed, should emit install-requested)
    tile.install_button.emit('clicked')
    assert install_req_called is True
    assert clicked_called is False
    
    # Trigger gesture release
    tile._gesture.emit('released', 1, 0, 0)
    assert clicked_called is True

def test_rich_tile_cask_installed():
    pkg = Package({
        'token': 'firefox',
        'name': ['Mozilla Firefox'],
        'desc': '',
    }, 'cask', installed_set={'firefox'})
    
    tile = TavernRichPackageTile(pkg)
    assert tile.name_label.get_text() == 'firefox'
    assert tile.short_desc.get_text() == 'GUI Application'
    assert tile.type_badge.get_text() == 'cask'
    assert tile.install_button.get_label() == 'Open'
    assert tile.install_button.get_visible() is True
    
    clicked_called = False
    tile.connect('clicked', lambda t: setattr(tile, '_clicked_fired', True))
    
    # Trigger install button click (installed, should emit clicked)
    tile.install_button.emit('clicked')
    assert getattr(tile, '_clicked_fired', False) is True

def test_rich_tile_formula_installed():
    pkg = Package({
        'name': 'git',
        'desc': None,
    }, 'formula', installed_set={'git'})
    
    tile = TavernRichPackageTile(pkg)
    assert tile.short_desc.get_text() == 'Command Line Utility'
    assert tile.install_button.get_label() == 'Open'
    # Formula installed should not show open button since it's CLI
    assert tile.install_button.get_visible() is False
    
    # Change state to not installed and update
    pkg.installed = False
    tile.update_package_state()
    assert tile.install_button.get_label() == 'Get'
    assert tile.install_button.get_visible() is True
