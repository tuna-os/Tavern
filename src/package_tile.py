# package_tile.py - Package tile widget
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, GObject
from .backend import Package


def clear_flow(container):
    """Remove all children from a FlowBox/Box, unbinding any package tiles.

    Tiles subscribe to notify:: signals on long-lived Package objects, so
    they must be unbound when discarded or the handlers (and the tiles they
    capture) accumulate on the Package for the lifetime of the app.
    """
    while child := container.get_first_child():
        tile = child.get_child() if isinstance(child, Gtk.FlowBoxChild) else child
        if isinstance(tile, TavernPackageTile):
            tile.unbind()
        container.remove(child)


@Gtk.Template(resource_path='/org.tunaos.tavern/package-tile.ui')
class TavernPackageTile(Adw.Bin):
    __gtype_name__ = 'TavernPackageTile'

    __gsignals__ = {
        # Emitted when the tile background (not a button) is clicked
        'activated':         (GObject.SignalFlags.RUN_LAST, None, ()),
        'install-requested': (GObject.SignalFlags.RUN_LAST, None, ()),
        'remove-requested':  (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    package_icon      = Gtk.Template.Child()
    name_label        = Gtk.Template.Child()
    desc_label        = Gtk.Template.Child()
    type_badge        = Gtk.Template.Child()
    installed_row     = Gtk.Template.Child()
    progress_revealer = Gtk.Template.Child()
    task_progress_bar = Gtk.Template.Child()
    task_status_label = Gtk.Template.Child()
    action_stack      = Gtk.Template.Child()
    install_button    = Gtk.Template.Child()
    remove_button     = Gtk.Template.Child()
    active_button     = Gtk.Template.Child()
    task_spinner      = Gtk.Template.Child()
    task_action_label = Gtk.Template.Child()

    def __init__(self, package=None, **kwargs):
        super().__init__(**kwargs)
        self._package = None
        self._pkg_handlers = []

        self.install_button.connect('clicked', self._on_install_clicked)
        self.remove_button.connect('clicked', self._on_remove_clicked)

        # Tile background click — fires only when inner buttons haven't claimed the gesture
        tile_gesture = Gtk.GestureClick()
        tile_gesture.connect('released', self._on_tile_released)
        self.add_controller(tile_gesture)

        # Visual feedback: add/remove :active style on press/release
        press_gesture = Gtk.GestureClick()
        press_gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        press_gesture.connect('pressed',  lambda *_: self.add_css_class('activating'))
        press_gesture.connect('released', lambda *_: self.remove_css_class('activating'))
        press_gesture.connect('cancel',   lambda *_: self.remove_css_class('activating'))
        self.add_controller(press_gesture)

        self.set_focusable(True)
        self.set_cursor_from_name('pointer')

        if package:
            self.set_package(package)

    def unbind(self):
        """Disconnect from the current package's signals."""
        if self._package:
            for hid in self._pkg_handlers:
                self._package.disconnect(hid)
        self._pkg_handlers = []

    def set_package(self, package):
        self.unbind()
        self._package = package
        self.name_label.set_label(package.display_name or package.name)
        self.desc_label.set_label(package.description or '')

        if package.pkg_type == 'cask':
            self.type_badge.set_label('cask')
            self.type_badge.remove_css_class('formula-badge')
            self.type_badge.add_css_class('cask-badge')
        elif package.pkg_type == 'flatpak':
            self.type_badge.set_label('flatpak')
            self.type_badge.remove_css_class('cask-badge')
            self.type_badge.remove_css_class('formula-badge')
            self.type_badge.add_css_class('flatpak-badge')
        else:
            self.type_badge.set_label('formula')
            self.type_badge.remove_css_class('cask-badge')
            self.type_badge.add_css_class('formula-badge')

        self._sync_state()

        self._pkg_handlers = [
            package.connect('notify::installed',     self._on_pkg_prop_changed),
            package.connect('notify::display-name',  self._on_display_name_changed),
            package.connect('notify::description',   self._on_description_changed),
            package.connect('notify::task-active',   self._on_pkg_prop_changed),
            package.connect('notify::task-progress', self._on_task_progress_changed),
            package.connect('notify::task-label',    self._on_task_label_changed),
        ]

    def get_package(self):
        return self._package

    # ── Property listeners ──────────────────────────────────────────────────

    def _on_pkg_prop_changed(self, pkg, pspec):
        self._sync_state()

    def _on_display_name_changed(self, pkg, pspec):
        self.name_label.set_label(pkg.display_name or pkg.name)

    def _on_description_changed(self, pkg, pspec):
        self.desc_label.set_label(pkg.description or '')

    def _on_task_progress_changed(self, pkg, pspec):
        self.task_progress_bar.set_fraction(pkg.task_progress)

    def _on_task_label_changed(self, pkg, pspec):
        self.task_status_label.set_label(pkg.task_label)
        if pkg.task_label:
            self.task_action_label.set_label(pkg.task_label)

    # ── State synchronisation ───────────────────────────────────────────────

    def _sync_state(self):
        if not self._package:
            return
        pkg = self._package

        if pkg.pkg_type == 'flatpak':
            self.installed_row.set_visible(False)
            self.action_stack.set_visible(False)
            self.progress_revealer.set_reveal_child(False)
            return

        self.action_stack.set_visible(True)
        active = pkg.task_active

        if active:
            self.action_stack.set_visible_child_name('active')
            self.progress_revealer.set_reveal_child(True)
            self.task_progress_bar.set_fraction(pkg.task_progress)
            self.task_status_label.set_label(pkg.task_label)
            if pkg.task_label:
                self.task_action_label.set_label(pkg.task_label)
            self.installed_row.set_visible(False)
        else:
            self.progress_revealer.set_reveal_child(False)
            installed = pkg.installed
            self.installed_row.set_visible(installed)
            self.action_stack.set_visible_child_name(
                'installed' if installed else 'install'
            )

    # ── Gesture handlers ────────────────────────────────────────────────────

    def _on_tile_released(self, gesture, n_press, x, y):
        self.emit('activated')

    # ── Button handlers ─────────────────────────────────────────────────────

    def _on_install_clicked(self, button):
        self.emit('install-requested')

    def _on_remove_clicked(self, button):
        self.emit('remove-requested')

    def set_icon_pixbuf(self, pixbuf):
        if pixbuf is None:
            return
        try:
            from gi.repository import Gdk
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            self.package_icon.set_from_paintable(texture)
        except Exception:
            pass
