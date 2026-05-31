# screenshot_lightbox.py - Clickable screenshot lightbox with zoom
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Gdk, GLib, GObject, Adw
from .logging_util import get_logger

_log = get_logger('screenshot_lightbox')

class TavernScreenshotLightbox(Adw.Window):
    __gtype_name__ = 'TavernScreenshotLightbox'

    def __init__(self, paintable, **kwargs):
        super().__init__(**kwargs)
        self.set_modal(True)
        self.set_hide_on_close(True)
        self.add_css_class('lightbox-overlay')

        self._paintable = paintable
        self._scale = 1.0
        self._min_scale = 0.5
        self._max_scale = 5.0
        self._is_fullscreen = False

        self._setup_ui()
        self._setup_gestures()

    def _setup_ui(self):
        overlay = Gtk.Overlay()
        self.set_content(overlay)

        # ScrolledWindow for panning
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_hexpand(True)
        self.scroll.set_vexpand(True)
        self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        overlay.set_child(self.scroll)

        # The image itself
        self.picture = Gtk.Picture.new_for_paintable(self._paintable)
        self.picture.set_can_shrink(True)
        self.picture.add_css_class('lightbox-image')
        self.picture.set_valign(Gtk.Align.CENTER)
        self.picture.set_halign(Gtk.Align.CENTER)
        self.scroll.set_child(self.picture)

        # Controls wrapper
        controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        controls_box.set_halign(Gtk.Align.END)
        controls_box.set_valign(Gtk.Align.START)
        controls_box.set_margin_top(12)
        controls_box.set_margin_end(12)
        overlay.add_overlay(controls_box)

        # Fullscreen toggle button
        self.fs_btn = Gtk.Button.new_from_icon_name('view-fullscreen-symbolic')
        self.fs_btn.add_css_class('lightbox-close-button') # Reusing style for consistency
        self.fs_btn.connect('clicked', self._on_fullscreen_toggled)
        controls_box.append(self.fs_btn)

        # Close button
        close_btn = Gtk.Button.new_from_icon_name('window-close-symbolic')
        close_btn.add_css_class('lightbox-close-button')
        close_btn.connect('clicked', lambda _: self.close())
        controls_box.append(close_btn)

        # Close on Escape
        controller = Gtk.EventControllerKey()
        controller.connect('key-pressed', self._on_key_pressed)
        self.add_controller(controller)

    def _setup_gestures(self):
        # Scroll to zoom
        scroll_controller = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll_controller.connect('scroll', self._on_scroll)
        self.picture.add_controller(scroll_controller)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            if self._is_fullscreen:
                self._on_fullscreen_toggled(None)
            else:
                self.close()
            return True
        return False

    def _on_fullscreen_toggled(self, button):
        self._is_fullscreen = not self._is_fullscreen
        if self._is_fullscreen:
            self.fullscreen()
            self.fs_btn.set_icon_name('view-restore-symbolic')
        else:
            self.unfullscreen()
            self.fs_btn.set_icon_name('view-fullscreen-symbolic')

    def _on_scroll(self, controller, dx, dy):
        zoom_factor = 1.1 if dy < 0 else 0.9
        new_scale = self._scale * zoom_factor
        
        if self._min_scale <= new_scale <= self._max_scale:
            self._scale = new_scale
            self._update_zoom()
        return True

    def _update_zoom(self):
        orig_width = self._paintable.get_intrinsic_width()
        orig_height = self._paintable.get_intrinsic_height()
        
        if orig_width > 0 and orig_height > 0:
            self.picture.set_size_request(
                int(orig_width * self._scale),
                int(orig_height * self._scale)
            )

    def present_with_animation(self, parent_root):
        # parent_root should be the window or a widget from which we can get size
        window = parent_root.get_root()
        if window:
            self.set_transient_for(window)
            w, h = window.get_default_size()
            # Set size to match parent window exactly
            self.set_default_size(w, h)
            # Remove decorations for the "overlay" look
            self.set_decorated(False)
        
        self.present()
        self.set_opacity(0.0)
        try:
            target = Adw.PropertyAnimationTarget.new(self, 'opacity')
            anim = Adw.TimedAnimation.new(self, 0.0, 1.0, 250, target)
            anim.play()
        except:
            self.set_opacity(1.0)
