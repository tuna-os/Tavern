# test_screenshot_lightbox.py
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from gi.repository import Gtk, Gdk, Adw, GdkPixbuf, GObject
from tavern.screenshot_lightbox import TavernScreenshotLightbox

@pytest.fixture
def paintable():
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 800, 600)
    return Gdk.Texture.new_for_pixbuf(pixbuf)

def test_lightbox_initialization(paintable):
    lightbox = TavernScreenshotLightbox(paintable)
    assert lightbox is not None
    assert lightbox._paintable == paintable

def test_lightbox_fullscreen_toggle(paintable):
    lightbox = TavernScreenshotLightbox(paintable)
    # Mock fullscreen and unfullscreen
    lightbox.fullscreen = lambda: setattr(lightbox, '_fs_called', True)
    lightbox.unfullscreen = lambda: setattr(lightbox, '_unfs_called', True)
    
    assert lightbox._is_fullscreen is False
    lightbox._on_fullscreen_toggled(None)
    assert lightbox._is_fullscreen is True
    assert getattr(lightbox, '_fs_called', False) is True
    
    lightbox._on_fullscreen_toggled(None)
    assert lightbox._is_fullscreen is False
    assert getattr(lightbox, '_unfs_called', False) is True

def test_lightbox_key_press(paintable):
    lightbox = TavernScreenshotLightbox(paintable)
    
    # Mock window methods
    lightbox.close = lambda: setattr(lightbox, '_closed', True)
    lightbox.fullscreen = lambda: setattr(lightbox, '_fs_called', True)
    lightbox.unfullscreen = lambda: setattr(lightbox, '_unfs_called', True)
    
    # Escape key when not fullscreen should close the window
    assert lightbox._on_key_pressed(None, Gdk.KEY_Escape, 0, 0) is True
    assert getattr(lightbox, '_closed', False) is True
    
    # Reset closed and set fullscreen
    lightbox._is_fullscreen = True
    assert lightbox._on_key_pressed(None, Gdk.KEY_Escape, 0, 0) is True
    assert lightbox._is_fullscreen is False
    assert getattr(lightbox, '_unfs_called', False) is True
    
    # Test non-Escape key (should return False)
    assert lightbox._on_key_pressed(None, Gdk.KEY_a, 0, 0) is False

def test_lightbox_zoom(paintable):
    lightbox = TavernScreenshotLightbox(paintable)
    
    # Test zoom in (dy < 0)
    lightbox._on_scroll(None, 0.0, -1.0)
    assert lightbox._scale > 1.0
    
    # Test zoom out (dy > 0)
    current_scale = lightbox._scale
    lightbox._on_scroll(None, 0.0, 1.0)
    assert lightbox._scale < current_scale

def test_lightbox_present_animation(paintable, monkeypatch):
    lightbox = TavernScreenshotLightbox(paintable)
    
    # Create parent mock
    class MockParent:
        def get_root(self):
            w = Gtk.Window()
            # Mock get_default_size
            w.get_default_size = lambda: (1024, 768)
            return w
            
    # Mock present and transient setters to avoid rendering/display server calls
    lightbox.present = lambda: setattr(lightbox, '_presented', True)
    lightbox.set_transient_for = lambda w: setattr(lightbox, '_transient', w)
    lightbox.set_default_size = lambda w, h: setattr(lightbox, '_size', (w, h))
    lightbox.set_decorated = lambda d: setattr(lightbox, '_decorated', d)
    
    lightbox.present_with_animation(MockParent())
    assert getattr(lightbox, '_presented', False) is True
    assert getattr(lightbox, '_size', None) == (1024, 768)
    assert getattr(lightbox, '_decorated', None) is False
    
    # Test exception fallback inside present_with_animation
    # Temporarily force Adw.PropertyAnimationTarget.new to raise an exception
    monkeypatch.setattr(Adw.PropertyAnimationTarget, 'new', lambda *args: exec("raise Exception('mocked')"))
    lightbox.set_opacity(0.5)
    lightbox.present_with_animation(MockParent())
    assert lightbox.get_opacity() == 1.0
