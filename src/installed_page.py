# installed_page.py - Installed packages page
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, GObject
from .backend import BrewBackend
from .package_tile import TavernPackageTile
from .updates_card import UpdatesCard
from .logging_util import get_logger

_log = get_logger('installed_page')


@Gtk.Template(resource_path='/dev/hanthor/Tavern/installed-page.ui')
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
    updates_card = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._backend = None

    def set_backend_and_manager(self, backend, task_manager):
        self._backend = backend
        self._task_manager = task_manager
        backend.connect('formulae-loaded', self._on_packages_loaded)
        backend.connect('casks-loaded', self._on_packages_loaded)
        backend.connect('outdated-changed', self._on_outdated_changed)
        
        # Configure UpdatesCard
        self.updates_card.set_backend(backend)
        self.updates_card.set_task_manager(task_manager)
        self.updates_card.connect('package-activated', self._on_updates_card_package_activated)

    def _on_outdated_changed(self, backend, outdated_data):
        count = len(outdated_data) if outdated_data else 0
        self.updates_card.set_visible(bool(count > 0))
        self.emit('outdated-count-changed', count)

    def _on_updates_card_package_activated(self, card, package):
        """Open package details for a package from the updates card."""
        self.emit('package-activated', package)

    def _on_packages_loaded(self, backend, packages):
        self.refresh(backend)

    def _load_tile_icon(self, tile, package):
        if not self._backend:
            return
        def on_icon_fetched(pkg, pixbuf):
            if pixbuf:
                tile.set_icon_pixbuf(pixbuf)
        self._backend.fetch_icon_async(package, on_icon_fetched)

    def refresh(self, backend=None):
        if backend:
            self._backend = backend
        if not self._backend:
            return

        installed = self._backend.get_installed_packages()
        _log.debug('Refreshing installed page: %d packages', len(installed))

        # Clear flow
        while child := self.installed_flow.get_first_child():
            self.installed_flow.remove(child)

        if not installed:
            self.installed_stack.set_visible_child_name('empty')
            return

        for pkg in installed:
            tile = TavernPackageTile(package=pkg)
            tile.connect('activated', self._on_tile_clicked)
            tile.connect('install-requested', self._on_tile_install_requested)
            tile.connect('remove-requested', self._on_tile_remove_requested)
            self._load_tile_icon(tile, pkg)
            self.installed_flow.append(tile)

        self.installed_stack.set_visible_child_name('content')

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
