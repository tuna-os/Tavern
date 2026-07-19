# installed_page.py - Installed packages page
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, GObject
from .backend import BrewBackend
from .package_tile import TavernPackageTile, clear_flow
from .logging_util import get_logger

_log = get_logger('installed_page')


@Gtk.Template(resource_path='/org.tunaos.tavern/installed-page.ui')
class TavernInstalledPage(Adw.Bin):
    __gtype_name__ = 'TavernInstalledPage'

    __gsignals__ = {
        'package-activated': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'install-requested': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'remove-requested':  (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'outdated-count-changed': (GObject.SignalFlags.RUN_LAST, None, (int,)),
    }

    installed_stack = Gtk.Template.Child()
    installed_flow = Gtk.Template.Child()
    updates_section = Gtk.Template.Child()
    updates_flow = Gtk.Template.Child()
    updates_count_label = Gtk.Template.Child()
    update_all_button = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._backend = None
        self._task_manager = None
        self._outdated_data = {}

        self.update_all_button.connect('clicked', self._on_update_all_clicked)

    def set_backend_and_manager(self, backend, task_manager):
        self._backend = backend
        self._task_manager = task_manager
        backend.connect('formulae-loaded', self._on_packages_loaded)
        backend.connect('casks-loaded', self._on_packages_loaded)
        backend.connect('outdated-changed', self._on_outdated_changed)

    def _on_outdated_changed(self, backend, outdated_data):
        self._outdated_data = dict(outdated_data) if outdated_data else {}
        count = len(outdated_data) if outdated_data else 0
        self.updates_section.set_visible(count > 0)
        if count == 1:
            self.updates_count_label.set_text('1 update available')
        else:
            self.updates_count_label.set_text(f'{count} updates available')
        self.update_all_button.set_sensitive(count > 0)
        self.emit('outdated-count-changed', count)
        self.refresh(backend)

    def _on_packages_loaded(self, backend, packages):
        self.refresh(backend)

    def _load_tile_icon(self, tile, package):
        if not self._backend:
            return
        def on_icon_fetched(pkg, pixbuf):
            if pixbuf:
                tile.set_icon_pixbuf(pixbuf)
        self._backend.fetch_icon_async(package, on_icon_fetched)

    def _is_outdated(self, pkg):
        if not self._outdated_data:
            return False
        return pkg.name in self._outdated_data or pkg.full_name in self._outdated_data

    def _append_tile(self, flow, pkg):
        tile = TavernPackageTile(package=pkg)
        tile.connect('activated', self._on_tile_clicked)
        tile.connect('install-requested', self._on_tile_install_requested)
        tile.connect('remove-requested', self._on_tile_remove_requested)
        self._load_tile_icon(tile, pkg)
        flow.append(tile)

    def refresh(self, backend=None):
        if backend:
            self._backend = backend
        if not self._backend:
            return

        installed = self._backend.get_installed_packages()
        _log.debug('Refreshing installed page: %d packages', len(installed))

        clear_flow(self.updates_flow)
        clear_flow(self.installed_flow)

        if not installed:
            self.installed_stack.set_visible_child_name('empty')
            return

        updates = [pkg for pkg in installed if self._is_outdated(pkg)]
        normal = [pkg for pkg in installed if not self._is_outdated(pkg)]

        for pkg in updates:
            self._append_tile(self.updates_flow, pkg)
        for pkg in normal:
            self._append_tile(self.installed_flow, pkg)

        self.updates_section.set_visible(bool(updates))
        if len(updates) == 1:
            self.updates_count_label.set_text('1 update available')
        elif updates:
            self.updates_count_label.set_text(f'{len(updates)} updates available')
        else:
            self.updates_count_label.set_text('No updates available')
        self.update_all_button.set_sensitive(bool(updates))

        self.installed_stack.set_visible_child_name('content')

    def _on_update_all_clicked(self, button):
        if not self._task_manager:
            return

        updates = [pkg for pkg in self._backend.get_installed_packages() if self._is_outdated(pkg)]
        _log.info('Update All clicked: %d packages', len(updates))
        for pkg in updates:
            self._task_manager.upgrade(pkg)

    def _on_tile_clicked(self, tile):
        pkg = tile.get_package()
        if pkg:
            self.emit('package-activated', pkg)

    def _on_tile_install_requested(self, tile):
        pkg = tile.get_package()
        if pkg:
            self.emit('install-requested', pkg)

    def _on_tile_remove_requested(self, tile):
        pkg = tile.get_package()
        if pkg:
            self.emit('remove-requested', pkg)
