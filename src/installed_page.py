# installed_page.py - Installed packages page
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, GObject
from .backend import BrewBackend
from .package_tile import TavernPackageTile
# Keep this import for compatibility with older compiled templates
# that still reference TavernUpdatesCard.
from .updates_card import UpdatesCard  # noqa: F401
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

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._backend = None
        self._task_manager = None
        self._outdated_data = {}

        # Optional children are looked up dynamically to support both old and
        # new compiled templates during development/testing.
        self.updates_section = self.get_template_child(TavernInstalledPage, 'updates_section')
        self.updates_flow = self.get_template_child(TavernInstalledPage, 'updates_flow')
        self.updates_count_label = self.get_template_child(TavernInstalledPage, 'updates_count_label')
        self.update_all_button = self.get_template_child(TavernInstalledPage, 'update_all_button')
        self.updates_card = self.get_template_child(TavernInstalledPage, 'updates_card')

        if self.update_all_button:
            self.update_all_button.connect('clicked', self._on_update_all_clicked)

    def set_backend_and_manager(self, backend, task_manager):
        self._backend = backend
        self._task_manager = task_manager
        backend.connect('formulae-loaded', self._on_packages_loaded)
        backend.connect('casks-loaded', self._on_packages_loaded)
        backend.connect('outdated-changed', self._on_outdated_changed)
        if self.updates_card:
            self.updates_card.set_backend(backend)
            self.updates_card.set_task_manager(task_manager)
            self.updates_card.connect('package-activated', self._on_updates_card_package_activated)

    def _on_updates_card_package_activated(self, card, package):
        self.emit('package-activated', package)

    def _on_outdated_changed(self, backend, outdated_data):
        self._outdated_data = dict(outdated_data) if outdated_data else {}
        count = len(outdated_data) if outdated_data else 0
        if self.updates_section:
            self.updates_section.set_visible(bool(count > 0))
        if self.updates_count_label:
            if count == 1:
                self.updates_count_label.set_text('1 update available')
            else:
                self.updates_count_label.set_text(f'{count} updates available')
        if self.update_all_button:
            self.update_all_button.set_sensitive(bool(count > 0))
        if self.updates_card:
            self.updates_card.set_visible(bool(count > 0))
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

        # Clear flows
        if self.updates_flow:
            while child := self.updates_flow.get_first_child():
                self.updates_flow.remove(child)
        while child := self.installed_flow.get_first_child():
            self.installed_flow.remove(child)

        if not installed:
            self.installed_stack.set_visible_child_name('empty')
            return

        updates = [pkg for pkg in installed if self._is_outdated(pkg)]
        normal = [pkg for pkg in installed if not self._is_outdated(pkg)]

        if self.updates_flow:
            for pkg in updates:
                self._append_tile(self.updates_flow, pkg)

            for pkg in normal:
                self._append_tile(self.installed_flow, pkg)
        else:
            for pkg in installed:
                self._append_tile(self.installed_flow, pkg)

        if self.updates_section:
            self.updates_section.set_visible(bool(updates))
        if self.updates_count_label:
            if updates:
                if len(updates) == 1:
                    self.updates_count_label.set_text('1 update available')
                else:
                    self.updates_count_label.set_text(f'{len(updates)} updates available')
            else:
                self.updates_count_label.set_text('No updates available')
        if self.update_all_button:
            self.update_all_button.set_sensitive(bool(updates))

        self.installed_stack.set_visible_child_name('content')

    def _on_update_all_clicked(self, button):
        if not self._task_manager:
            return

        updates = [pkg for pkg in self._backend.get_installed_packages() if self._is_outdated(pkg)]
        _log.info('Update All clicked: %d packages', len(updates))
        for pkg in updates:
            self._task_manager.install(pkg)

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
