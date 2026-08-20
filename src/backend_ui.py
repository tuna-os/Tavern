# backend_ui.py - Async loading/search + status/progress plumbing (mixin for BrewBackend)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Extracted from backend.py (tuna-os/Tavern#81): background loading threads,
# async search, and the loading_status/loading_progress UI updates. Follows the
# same mixin composition already used for TapsMixin/MediaMixin/CacheMixin —
# this class expects the usual BrewBackend instance state (`self.loading`,
# `self._formulae`, `self._casks`, `self._refresh_lock`, cache/state/remote
# methods) to exist on whatever it's mixed into, exactly as the original
# methods did as part of BrewBackend.

import threading

from gi.repository import GLib, Gio

from .logging_util import get_logger, log_timing
from .package import Package
from .backend_remote import FORMULA_API, CASK_API

_log = get_logger('backend_ui')


class UiMixin:
    """Async thread wrappers and loading/search plumbing mixed into BrewBackend."""

    def _update_status(self, msg):
        _log.info('Status update: %s', msg)
        GLib.idle_add(setattr, self, 'loading_status', msg)

    def _update_progress(self, val):
        GLib.idle_add(setattr, self, 'loading_progress', float(val))

    def load_all_async(self):
        """Load all package data asynchronously."""
        _log.info('load_all_async() starting')
        self.loading = True
        thread = threading.Thread(target=self._load_all_thread, daemon=True)
        thread.start()

    def _load_all_thread(self):
        _log.debug('_load_all_thread started')
        self._update_progress(0.0)
        self._update_status(_("Scanning installed packages…"))
        # Get installed packages first
        with log_timing('get installed packages', 'backend'):
            installed_f, installed_c = self._get_installed()
        self._installed_formulae = installed_f
        self._installed_casks = installed_c
        self._update_progress(0.05)

        # Emit installed signal
        installed_pkgs = []
        GLib.idle_add(self.emit, 'installed-loaded', installed_pkgs)

        # Load pinned formulae in the background — the result feeds back into
        # the next `outdated-changed` emission so pinned packages don't show
        # up in the Updates card.
        threading.Thread(target=self._load_pinned, daemon=True).start()

        # Load formulae from cache first
        self._update_status(_("Loading Homebrew formulae catalog…"))
        self._update_progress(0.08)
        has_cache_f = False
        data, is_stale = self._load_cached('formulae', max_age=43200)
        if data:
            has_cache_f = True
            with log_timing('parse formulae from cache', 'backend'):
                self._formulae = [
                    Package(d, 'formula', self._installed_formulae) for d in data
                ]
            _log.info('Loaded %d formulae from cache (stale=%s)', len(self._formulae), is_stale)
            GLib.idle_add(self.emit, 'formulae-loaded', self._formulae)
            self._update_progress(0.12)

        # Load casks from cache first
        self._update_status(_("Loading Homebrew casks catalog…"))
        self._update_progress(0.15)
        has_cache_c = False
        data_c, is_stale_c = self._load_cached('casks', max_age=43200)
        if data_c:
            has_cache_c = True
            data_c = self._filter_linux_casks(data_c)

            self._casks = [
                Package(d, 'cask', self._installed_casks) for d in data_c
            ]
            GLib.idle_add(self.emit, 'casks-loaded', self._casks)
            self._update_progress(0.2)

        # If cache is available, instantly enable interaction and scan taps
        if has_cache_f or has_cache_c:
            _log.debug('Cache loaded on launch, clearing spinner and scanning taps immediately')
            self._update_progress(0.9)
            self._load_tap_packages()
            self._update_progress(0.95)
            GLib.idle_add(self._set_loading_false)

        # Fetch formulae in background if missing or stale
        if not has_cache_f or is_stale:
            _log.debug('Formulae cache missing or stale, refreshing…')
            with self._refresh_lock:
                # Double check if cache is still missing or stale after acquiring the lock
                double_check_data, double_check_stale = self._load_cached('formulae', max_age=43200)
                if double_check_data and not double_check_stale:
                    _log.debug('Formulae cache was refreshed by another thread, loading from cache')
                    self._formulae = [
                        Package(d, 'formula', self._installed_formulae) for d in double_check_data
                    ]
                    GLib.idle_add(self.emit, 'formulae-loaded', self._formulae)
                    self._update_progress(0.6)
                else:
                    new_data = self._load_from_host_jws('formula')
                    if new_data:
                        _log.info('Loaded formulae from system Homebrew JWS cache (bypassed API download)')
                        self._update_progress(0.6)
                    else:
                        _log.debug('System Homebrew cache not available or invalid, fetching from API…')
                        new_data = self._fetch_json(FORMULA_API)
                    if new_data:
                        self._save_cache('formulae', new_data)
                        with log_timing('parse formulae from API', 'backend'):
                            self._formulae = [
                                Package(d, 'formula', self._installed_formulae) for d in new_data
                            ]
                        _log.info('Loaded %d formulae from cache/API', len(self._formulae))
                        GLib.idle_add(self.emit, 'formulae-loaded', self._formulae)
                        self._update_progress(0.6)

        # Fetch casks in background if missing or stale
        if not has_cache_c or is_stale_c:
            _log.debug('Casks cache missing or stale, refreshing…')
            with self._refresh_lock:
                # Double check if cache is still missing or stale after acquiring the lock
                double_check_data, double_check_stale = self._load_cached('casks', max_age=43200)
                if double_check_data and not double_check_stale:
                    _log.debug('Casks cache was refreshed by another thread, loading from cache')
                    
                    double_check_data = self._filter_linux_casks(double_check_data)

                    self._casks = [
                        Package(d, 'cask', self._installed_casks) for d in double_check_data
                    ]
                    GLib.idle_add(self.emit, 'casks-loaded', self._casks)
                    self._update_progress(0.9)
                else:
                    new_data = self._load_from_host_jws('cask')
                    if new_data:
                        _log.info('Loaded casks from system Homebrew JWS cache (bypassed API download)')
                        self._update_progress(0.9)
                    else:
                        _log.debug('System Homebrew cache not available or invalid, fetching from API…')
                        new_data = self._fetch_json(CASK_API)
                    if new_data:
                        self._save_cache('casks', new_data)
                        
                        new_data = self._filter_linux_casks(new_data)

                        self._casks = [
                            Package(d, 'cask', self._installed_casks) for d in new_data
                        ]
                        GLib.idle_add(self.emit, 'casks-loaded', self._casks)
                        self._update_progress(0.9)

        # If no cache was available on launch, tap scan and clear spinner now
        if not (has_cache_f or has_cache_c):
            self._update_progress(0.92)
            self._update_status(_("Scanning local taps…"))
            _log.debug('No cache was available on launch, scanning taps and clearing spinner now')
            self._load_tap_packages()
            self._update_progress(0.96)
            GLib.idle_add(self._set_loading_false)

        self._update_progress(0.98)
        self._update_status(_("Building search provider index…"))
        self._build_search_provider_cache()
        self._update_progress(1.0)

        # Check for outdated packages in the background now that all catalog loading is complete
        try:
            app = Gio.Application.get_default()
            app_id = app.get_application_id() if app else 'org.tunaos.tavern'
            settings = Gio.Settings.new(app_id)
            if settings.get_boolean('outdated-check-enabled'):
                self._check_outdated()
        except Exception as e:
            _log.debug('Could not read outdated-check-enabled setting: %s', e)

        _log.debug('_load_all_thread finished')

    def _set_loading_false(self):
        self.loading = False

    def refresh_installed_async(self):
        """Lightweight refresh of installed/pinned/outdated state.

        Used after install/remove tasks finish — avoids re-parsing the full
        catalog the way load_all_async() does.
        """
        threading.Thread(target=self._refresh_installed_thread, daemon=True).start()

    def _refresh_installed_thread(self):
        installed_f, installed_c = self._get_installed()
        self._installed_formulae = installed_f
        self._installed_casks = installed_c

        changes = []
        for pkg in self._formulae:
            inst = pkg.name in installed_f or pkg.full_name in installed_f
            if pkg.installed != inst:
                changes.append((pkg, inst))
        for pkg in self._casks:
            inst = pkg.name in installed_c or pkg.full_name in installed_c
            if pkg.installed != inst:
                changes.append((pkg, inst))
        GLib.idle_add(self._apply_installed_changes, changes)

        self._load_pinned()
        try:
            app = Gio.Application.get_default()
            app_id = app.get_application_id() if app else 'org.tunaos.tavern'
            settings = Gio.Settings.new(app_id)
            if settings.get_boolean('outdated-check-enabled'):
                self._check_outdated()
        except Exception as e:
            _log.debug('Skipping outdated check after refresh: %s', e)

    def search_async(self, query, pkg_type, callback):
        """Run search() on a worker thread and deliver results on the main loop.

        Only the newest query is delivered — stale in-flight searches are
        dropped, so fast typing never floods the UI (issue #49).
        """
        self._search_generation += 1
        gen = self._search_generation
        self._search_executor.submit(self._search_job, gen, query, pkg_type, callback)

    def _search_job(self, gen, query, pkg_type, callback):
        if gen != self._search_generation:
            return  # superseded before it even started
        try:
            results = self.search(query, pkg_type)
        except Exception as e:
            _log.error('search_async failed for %r: %s', query, e)
            results = []
        GLib.idle_add(self._deliver_search, gen, callback, query, results)

    def _deliver_search(self, gen, callback, query, results):
        if gen == self._search_generation:
            callback(query, results)

    def search(self, query, pkg_type=None):
        """Search packages by name/description. Returns list of Package."""
        query = query.lower().strip()
        if not query:
            return []

        _log.debug('search: query=%r  type=%s', query, pkg_type)
        results = []
        if pkg_type in (None, 'formula'):
            for pkg in self._formulae:
                if query in pkg.name.lower() or query in pkg.description.lower():
                    results.append(pkg)
        if pkg_type in (None, 'cask'):
            for pkg in self._casks:
                if query in pkg.name.lower() or query in pkg.display_name.lower() or query in pkg.description.lower():
                    results.append(pkg)

        # Sort: exact name matches first, then starts-with, then contains
        def sort_key(pkg):
            n = pkg.name.lower()
            if n == query:
                return (0, n)
            if n.startswith(query):
                return (1, n)
            return (2, n)

        results.sort(key=sort_key)
        return results
