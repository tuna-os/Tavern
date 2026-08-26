# search_page.py - Search page widget
# SPDX-License-Identifier: GPL-3.0-or-later

import gettext

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, Gdk, GLib, GObject
from .backend import BrewBackend
from .catalog_policy import CatalogFilters, filter_packages, sort_packages
from .package_tile import TavernPackageTile, clear_flow
from .logging_util import get_logger

_log = get_logger('search_page')
_ = gettext.gettext


@Gtk.Template(resource_path='/org.tunaos.tavern/search-page.ui')
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
    no_results_page = Gtk.Template.Child()
    filter_all = Gtk.Template.Child()
    filter_formula = Gtk.Template.Child()
    filter_cask = Gtk.Template.Child()
    filter_box = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._backend = None
        self._search_timeout = None
        self._current_filter = None  # None=all, 'formula', 'cask'
        self._result_filters = Gtk.MenuButton(
            icon_name='view-filter-symbolic', tooltip_text=_('Filter results'))
        popover = Gtk.Popover()
        filters_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8,
            margin_top=12, margin_bottom=12, margin_start=12, margin_end=12,
        )
        self._installed_only = Gtk.CheckButton(label=_('Installed'))
        self._outdated_only = Gtk.CheckButton(label=_('Updates available'))
        self._vulnerable_only = Gtk.CheckButton(label=_('Security advisories'))
        self._compatible_only = Gtk.CheckButton(label=_('Compatible with this system'))
        self._pinned_only = Gtk.CheckButton(label=_('Pinned'))
        for control in (
            self._installed_only, self._outdated_only,
            self._vulnerable_only, self._compatible_only, self._pinned_only,
        ):
            control.connect('toggled', self._on_filter_changed)
            filters_box.append(control)
        self._tap_filter = Gtk.Entry(placeholder_text=_('Tap, for example homebrew/core'))
        self._tap_filter.connect('changed', self._on_filter_changed)
        filters_box.append(self._tap_filter)
        reset_button = Gtk.Button(label=_('Reset Filters'))
        reset_button.connect('clicked', self._on_reset_filters)
        filters_box.append(reset_button)
        popover.set_child(filters_box)
        self._result_filters.set_popover(popover)
        self.filter_box.append(self._result_filters)

        self.search_entry.connect('changed', self._on_search_changed)
        self.clear_button.connect('clicked', self._on_clear)
        self.filter_all.connect('toggled', self._on_filter_changed)
        self.filter_formula.connect('toggled', self._on_filter_changed)
        self.filter_cask.connect('toggled', self._on_filter_changed)
        key_controller = Gtk.EventControllerKey()
        key_controller.connect('key-pressed', self._on_search_key_pressed)
        self.search_entry.add_controller(key_controller)

    def set_backend(self, backend):
        self._backend = backend

    def focus_search(self):
        self.search_entry.grab_focus()

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
        if hasattr(self._backend, 'search_async'):
            # Off-main-thread search; the backend drops superseded queries
            self._backend.search_async(query, pkg_type, self._on_search_results)
        else:
            self._on_search_results(query, self._backend.search(query, pkg_type))

    def _on_search_results(self, query, results):
        # Ignore late results for text the user has since changed
        if query != self.search_entry.get_text().strip():
            return
        outdated = set()
        pinned = set()
        if self._backend:
            outdated.update(getattr(self._backend, '_outdated_formulae', {}))
            outdated.update(getattr(self._backend, '_outdated_casks', {}))
            pinned = self._backend.get_pinned()
        filters = CatalogFilters(
            installed_only=self._installed_only.get_active(),
            outdated_only=self._outdated_only.get_active(),
            pinned_only=self._pinned_only.get_active(),
            vulnerable_only=self._vulnerable_only.get_active(),
            compatible_only=self._compatible_only.get_active(),
            tap=self._tap_filter.get_text().strip(),
        )
        results = filter_packages(results, filters, outdated=outdated, pinned=pinned)
        results = sort_packages(results, 'updates', outdated=outdated, pinned=pinned)
        _log.debug('Search returned %d filtered results', len(results))

        clear_flow(self.results_flow)

        if not results:
            self.no_results_page.set_description(
                _('No packages match the active filters')
                if self._active_result_filter_count()
                else _('Try a different search term')
            )
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

    def _active_result_filter_count(self):
        return sum(control.get_active() for control in (
            self._installed_only, self._outdated_only, self._pinned_only,
            self._vulnerable_only, self._compatible_only,
        )) + bool(self._tap_filter.get_text().strip())

    def _sync_filter_accessibility(self):
        count = self._active_result_filter_count()
        label = _('Filter results') if not count else _(
            'Filter results, {count} active').format(count=count)
        self._result_filters.set_tooltip_text(label)
        self._result_filters.update_property(
            [Gtk.AccessibleProperty.LABEL], [label])

    def _on_filter_changed(self, button):
        result_controls = (
            self._installed_only, self._outdated_only,
            self._vulnerable_only, self._compatible_only, self._pinned_only,
            self._tap_filter,
        )
        if button in result_controls:
            self._sync_filter_accessibility()
            query = self.search_entry.get_text().strip()
            if query:
                self._do_search(query)
            return
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

    def _on_reset_filters(self, _button):
        for control in (
            self._installed_only, self._outdated_only, self._pinned_only,
            self._vulnerable_only, self._compatible_only,
        ):
            control.set_active(False)
        self._tap_filter.set_text('')
        self._sync_filter_accessibility()

    def _on_search_key_pressed(self, _controller, keyval, _keycode, _state):
        if keyval not in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            return False
        child = self.results_flow.get_first_child()
        tile = child.get_child() if child else None
        if tile:
            self._on_tile_clicked(tile)
            return True
        return False

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
