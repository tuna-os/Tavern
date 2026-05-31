# search_page.py - Search page widget
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, GLib, GObject
from .backend import BrewBackend
from .package_tile import TavernPackageTile
from .logging_util import get_logger

_log = get_logger('search_page')


@Gtk.Template(resource_path='/dev/hanthor/Tavern/search-page.ui')
class TavernSearchPage(Adw.Bin):
    __gtype_name__ = 'TavernSearchPage'

    __gsignals__ = {
        'package-activated': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'install-requested': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'remove-requested':  (GObject.SignalFlags.RUN_LAST, None, (object,)),
    }

    search_entry = Gtk.Template.Child()
    search_spinner = Gtk.Template.Child()
    clear_button = Gtk.Template.Child()
    search_stack = Gtk.Template.Child()
    results_flow = Gtk.Template.Child()
    filter_all = Gtk.Template.Child()
    filter_formula = Gtk.Template.Child()
    filter_cask = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._backend = None
        self._search_timeout = None
        self._current_filter = None  # None=all, 'formula', 'cask'

        self.search_entry.connect('changed', self._on_search_changed)
        self.clear_button.connect('clicked', self._on_clear)
        self.filter_all.connect('toggled', self._on_filter_changed)
        self.filter_formula.connect('toggled', self._on_filter_changed)
        self.filter_cask.connect('toggled', self._on_filter_changed)

    def set_backend(self, backend):
        self._backend = backend

    def set_packages(self, formulae, casks):
        # Re-run current search with new data
        query = self.search_entry.get_text().strip()
        if query:
            self._do_search(query)

    def _on_search_changed(self, entry):
        text = entry.get_text().strip()
        self.clear_button.set_visible(bool(text))

        if self._search_timeout:
            GLib.source_remove(self._search_timeout)
            self._search_timeout = None

        if not text:
            self.search_stack.set_visible_child_name('empty')
            return

        self._search_timeout = GLib.timeout_add(300, self._search_timeout_cb, text)

    def _search_timeout_cb(self, query):
        self._search_timeout = None
        self._do_search(query)
        return False

    def _load_tile_icon(self, tile, package):
        """Ask the backend to fetch an icon and push it into the tile when ready."""
        if not self._backend:
            return
        def on_icon_fetched(pkg, pixbuf):
            if pixbuf:
                tile.set_icon_pixbuf(pixbuf)
        self._backend.fetch_icon_async(package, on_icon_fetched)

    def _do_search(self, query):
        if not self._backend:
            return
        _log.debug('Searching: %r  filter=%s', query, self._current_filter)
        self.search_spinner.set_visible(True)

        pkg_type = self._current_filter
        results = self._backend.search(query, pkg_type)
        _log.debug('Search returned %d results', len(results))

        # Clear old results
        while child := self.results_flow.get_first_child():
            self.results_flow.remove(child)

        if not results:
            self.search_stack.set_visible_child_name('no-results')
        else:
            self.search_stack.set_visible_child_name('results')
            for pkg in results[:120]:  # cap display at 120
                tile = TavernPackageTile(package=pkg)
                tile.connect('activated', self._on_tile_clicked)
                tile.connect('install-requested', self._on_tile_install_requested)
                tile.connect('remove-requested', self._on_tile_remove_requested)
                self._load_tile_icon(tile, pkg)
                self.results_flow.append(tile)

        self.search_spinner.set_visible(False)

    def _on_filter_changed(self, button):
        if not button.get_active():
            return
        if button == self.filter_formula:
            self._current_filter = 'formula'
        elif button == self.filter_cask:
            self._current_filter = 'cask'
        else:
            self._current_filter = None

        query = self.search_entry.get_text().strip()
        if query:
            self._do_search(query)

    def _on_clear(self, button):
        self.search_entry.set_text('')
        self.search_stack.set_visible_child_name('empty')

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
