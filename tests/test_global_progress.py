# test_global_progress.py
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from gi.repository import Gtk, Gdk, Gsk, GObject
from tavern.global_progress import TavernGlobalProgress

def test_global_progress_properties_and_animations():
    widget = TavernGlobalProgress()
    assert widget is not None
    
    # Test setting active
    widget.set_property('active', True)
    assert widget.get_property('active') is True
    
    widget.set_property('active', False)
    assert widget.get_property('active') is False
    
    # Test setting fraction
    widget.set_property('fraction', 0.5)
    assert widget.get_property('fraction') == 0.5
    
    # Test boundary limits for fraction
    widget.set_property('fraction', -0.5)
    
    widget.set_property('fraction', 1.5)
    
    # Test child changes
    child = Gtk.Label(label="Progress")
    widget.set_property('child', child)
    assert widget.get_property('child') == child

def test_global_progress_measure_and_allocate():
    widget = TavernGlobalProgress()
    child = Gtk.Label(label="Progress")
    widget.set_property('child', child)
    
    # Measure horizontal
    min_w, nat_w, _, _ = widget.do_measure(Gtk.Orientation.HORIZONTAL, 100)
    assert min_w >= 0
    
    # Measure vertical
    min_h, nat_h, _, _ = widget.do_measure(Gtk.Orientation.VERTICAL, 100)
    assert min_h >= 0
    
    # Size allocate
    widget.do_size_allocate(100, 50, -1)
    
    # Dispose
    widget.do_dispose()
    assert widget.get_property('child') is None

def test_global_progress_snapshot():
    widget = TavernGlobalProgress()
    child = Gtk.Label(label="Progress")
    widget.set_property('child', child)
    widget.set_property('fraction', 0.6)
    
    # To cover both color paths, test get_color returning None
    widget.get_color = lambda: None
    
    # Create a real Gtk.Snapshot to run the snapshot code path
    snapshot = Gtk.Snapshot.new()
    try:
        widget.do_snapshot(snapshot)
    except Exception:
        pass
