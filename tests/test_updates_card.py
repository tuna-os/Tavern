# test_updates_card.py
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from gi.repository import Gtk, GLib
from tavern.updates_card import UpdatesCard
from tavern.backend import Package, BrewBackend
from tavern.task_manager import TaskManager

def test_updates_card_rendering_and_signals(tmp_path, monkeypatch):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    backend = BrewBackend()
    task_manager = TaskManager(backend)
    
    card = UpdatesCard()
    card.set_backend(backend)
    card.set_task_manager(task_manager)
    
    # Pre-populate backend packages
    pkg_rg = Package({'name': 'ripgrep', 'desc': 'rg'}, 'formula')
    pkg_fox = Package({'token': 'firefox', 'name': ['Firefox']}, 'cask')
    backend._formulae = [pkg_rg]
    backend._casks = [pkg_fox]
    
    # Mock task manager install/remove methods
    installed_pkgs = []
    monkeypatch.setattr(task_manager, 'upgrade', lambda p: installed_pkgs.append(p))
    
    # Check initial text (0 updates)
    card.set_outdated_packages([])
    assert card._count_label.get_text() == 'No updates available'
    assert card._update_all_btn.get_sensitive() is False
    
    # Emit outdated changed (1 update)
    outdated_data_1 = {
        'ripgrep': {
            'pkg_type': 'formula',
            'installed': '13.0.0',
            'latest': '14.1.1'
        }
    }
    card._on_outdated_changed(backend, outdated_data_1)
    
    assert card._count_label.get_text() == '1 update available'
    assert card._update_all_btn.get_sensitive() is True
    
    # 2 updates + 1 non-existent package to cover line 170 warning path
    outdated_data_2 = {
        'ripgrep': {
            'pkg_type': 'formula',
            'installed': '13.0.0',
            'latest': '14.1.1'
        },
        'firefox': {
            'pkg_type': 'cask',
            'installed': '129.0',
            'latest': '130.0'
        },
        'nonexistent-cask': {
            'pkg_type': 'cask',
            'installed': '1.0',
            'latest': '2.0'
        },
        'nonexistent-formula': {
            'pkg_type': 'formula',
            'installed': '1.0',
            'latest': '2.0'
        },
        'unknown-type': {
            'pkg_type': 'other',
            'installed': '1.0',
            'latest': '2.0'
        }
    }
    backend.emit('outdated-changed', outdated_data_2)
    
    assert card._update_all_btn.get_sensitive() is True
    
    # Check rows
    rows = []
    row = card._updates_list.get_first_child()
    while row is not None:
        rows.append(row)
        row = row.get_next_sibling()
    assert len(rows) == 5
    
    # Test _on_update_all_clicked (should only find/upgrade ripgrep and firefox)
    card._on_update_all_clicked(None)
    assert len(installed_pkgs) == 2
    assert any(p.name == 'ripgrep' for p in installed_pkgs)
    assert any(p.name == 'firefox' for p in installed_pkgs)
    
    # Test _on_row_activated
    activated_pkgs = []
    card.connect('package-activated', lambda c, p: activated_pkgs.append(p))
    
    card._on_row_activated(card._updates_list, rows[0])
    assert len(activated_pkgs) == 1
    assert activated_pkgs[0] == pkg_rg
    
    # Trigger with a non-existent package
    row_nonexistent = Gtk.ListBoxRow()
    row_nonexistent._package_name = 'nonexistent'
    row_nonexistent._package_type = 'formula'
    card._on_row_activated(card._updates_list, row_nonexistent)
    # Should not raise exception or append anything
    assert len(activated_pkgs) == 1
    
    # Test line 175: find_package without backend
    card.set_backend(None)
    assert card._find_package('ripgrep', 'formula') is None
