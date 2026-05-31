# test_package_tile.py
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from gi.repository import Gtk, GdkPixbuf
from tavern.package_tile import TavernPackageTile
from tavern.backend import Package

def test_package_tile_types():
    # 0. None Package / Empty constructor
    tile_empty = TavernPackageTile(None)
    assert tile_empty.get_package() is None
    tile_empty._sync_state() # Should return early

    # 1. Formula
    pkg_formula = Package({'name': 'ripgrep', 'desc': 'Fast search'}, 'formula')
    tile = TavernPackageTile(pkg_formula)
    assert tile.get_package() == pkg_formula
    assert tile.name_label.get_label() == 'ripgrep'
    assert tile.desc_label.get_label() == 'Fast search'
    assert tile.type_badge.get_label() == 'formula'
    
    # 2. Cask
    pkg_cask = Package({'token': 'firefox', 'name': ['Firefox']}, 'cask')
    tile.set_package(pkg_cask)
    assert tile.get_package() == pkg_cask
    assert tile.name_label.get_label() == 'Firefox'
    assert tile.type_badge.get_label() == 'cask'
    
    # 3. Flatpak
    pkg_flatpak = Package({'id': 'org.gimp.GIMP', 'name': 'GIMP'}, 'flatpak')
    tile.set_package(pkg_flatpak)
    assert tile.name_label.get_label() == 'GIMP'
    assert tile.type_badge.get_label() == 'flatpak'

def test_package_tile_signals_and_gestures():
    pkg = Package({'name': 'ripgrep', 'desc': 'Fast search'}, 'formula')
    tile = TavernPackageTile(pkg)
    
    install_req = False
    remove_req = False
    activated = False
    
    tile.connect('install-requested', lambda *_: setattr(tile, '_install_req', True))
    tile.connect('remove-requested', lambda *_: setattr(tile, '_remove_req', True))
    tile.connect('activated', lambda *_: setattr(tile, '_activated', True))
    
    # Click install
    tile.install_button.emit('clicked')
    assert getattr(tile, '_install_req', False) is True
    
    # Click remove
    tile.remove_button.emit('clicked')
    assert getattr(tile, '_remove_req', False) is True
    
    # Simulate activation gesture using a mock gesture
    class MockGesture:
        def get_current_sequence(self):
            return 1
        def get_sequence_state(self, seq):
            return Gtk.EventSequenceState.NONE
            
    tile._on_tile_released(MockGesture(), 1, 0, 0)
    assert getattr(tile, '_activated', False) is True

def test_package_tile_property_listeners():
    pkg = Package({'name': 'ripgrep', 'desc': 'Fast search'}, 'formula')
    tile = TavernPackageTile(pkg)
    
    # notify::installed
    pkg.installed = True
    assert tile.installed_row.get_visible() is True
    
    # notify::display-name
    pkg.display_name = 'Ripgrep Tool'
    assert tile.name_label.get_label() == 'Ripgrep Tool'
    
    # notify::description
    pkg.description = 'Extremely fast search tool'
    assert tile.desc_label.get_label() == 'Extremely fast search tool'
    
    # notify::task-active & progress
    pkg.task_active = True
    pkg.task_progress = 0.5
    pkg.task_label = 'Downloading'
    
    assert tile.progress_revealer.get_reveal_child() is True
    assert tile.task_progress_bar.get_fraction() == 0.5
    assert tile.task_status_label.get_label() == 'Downloading'
    assert tile.task_action_label.get_label() == 'Downloading'

def test_package_tile_icon_pixbuf():
    pkg = Package({'name': 'ripgrep'}, 'formula')
    tile = TavernPackageTile(pkg)
    
    # Call with None
    tile.set_icon_pixbuf(None)
    
    # Call with a valid pixbuf
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 32, 32)
    tile.set_icon_pixbuf(pixbuf)
    # Shouldn't raise any exception
