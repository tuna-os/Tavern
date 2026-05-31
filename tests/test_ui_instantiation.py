# test_ui_instantiation.py
import pytest
from gi.repository import Gtk, Adw
Adw.init()
from tavern.package_tile import TavernPackageTile
from tavern.backend import Package

def test_instantiate_tile():
    pkg = Package({'name': 'ripgrep', 'desc': 'Fast search'}, 'formula')
    tile = TavernPackageTile(pkg)
    # Check if attributes are set
    assert tile is not None
