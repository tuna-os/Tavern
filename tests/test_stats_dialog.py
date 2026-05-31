# test_stats_dialog.py
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from gi.repository import Gtk, Adw
from tavern.stats_dialog import TavernStatsDialog
from tavern.backend import Package

def test_stats_dialog_formatting_and_population():
    pkg = Package({
        'name': 'ripgrep',
        'desc': 'Fast search',
        'analytics': {
            'install': {
                '30d': {'ripgrep': 1500000},
                '90d': {'ripgrep': 2500},
                '365d': {'ripgrep': 500}
            }
        }
    }, 'formula')
    
    dialog = TavernStatsDialog(pkg)
    assert dialog is not None
    
    # Assert values formatted correctly
    assert dialog._format_count(1500000) == "1.50M"
    assert dialog._format_count(2500) == "2.50K"
    assert dialog._format_count(500) == "500"
    assert dialog._format_count(0) == "0"
    
    # Assert labels loaded correct values
    assert dialog.count_30d.get_label() == "1.50M"
    assert dialog.count_90d.get_label() == "2.50K"
    assert dialog.count_365d.get_label() == "500"

def test_stats_dialog_zero_values():
    # Empty package has 0 installs
    pkg = Package({'name': 'empty'}, 'formula')
    dialog = TavernStatsDialog(pkg)
    
    assert dialog.total_installs_label.get_label() == "---"
    assert dialog.bar_30d.get_fraction() == 0.0
    assert dialog.bar_90d.get_fraction() == 0.0
    assert dialog.bar_365d.get_fraction() == 0.0

def test_stats_dialog_none_package():
    # Test initialization with None package
    dialog = TavernStatsDialog(None)
    assert dialog is not None
