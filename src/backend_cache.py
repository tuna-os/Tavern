# backend_cache.py - Local cache I/O + Brewfile parsing (mixin for BrewBackend)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Extracted from backend.py (tuna-os/Tavern#81): the one clearly
# self-contained concern in BrewBackend that touches only the filesystem
# and JSON, not GObject signals, threading, or subprocess. Follows the same
# mixin composition already used for TapsMixin/MediaMixin — this class
# expects `self._cache_dir` and (for the host-JWS path) `self._update_status`
# to exist on whatever it's mixed into, exactly as the original methods did
# as part of BrewBackend.

import gettext
import json
import os
import sys
import threading

from gi.repository import GLib

from .backend_remote import FORMULA_API, CASK_API
from .logging_util import get_logger, log_timing
from .package import Package

_ = gettext.gettext

_log = get_logger('backend_cache')


class CacheMixin:
    """Local JSON cache I/O, host Homebrew JWS cache reads, and Brewfile parsing."""

    def parse_brewfile(self, path):
        import re
        taps = []
        formulae = []
        casks = []
        flatpaks = []

        with log_timing(f'parse_brewfile {path}', 'brewfile'):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith('tap '):
                            m = re.match(r'tap\s+["\']([^"\']+)["\'](?:,\s*trusted:\s*(true|false))?', line)
                            if m:
                                taps.append({'name': m.group(1), 'trusted': m.group(2) == 'true'})
                        elif line.startswith('brew '):
                            m = re.match(r'brew\s+["\']([^"\']+)["\']', line)
                            if m: formulae.append(m.group(1))
                        elif line.startswith('cask '):
                            m = re.match(r'cask\s+["\']([^"\']+)["\']', line)
                            if m: casks.append(m.group(1))
                        elif line.startswith('flatpak '):
                            m = re.match(r'flatpak\s+["\']([^"\']+)["\']', line)
                            if m: flatpaks.append(m.group(1))
            except Exception as e:
                _log.error('Error parsing Brewfile: %s', e)

        _log.info('Parsed Brewfile: taps=%d, formulae=%d, casks=%d, flatpaks=%d',
                  len(taps), len(formulae), len(casks), len(flatpaks))
        return {'taps': taps, 'formulae': formulae, 'casks': casks, 'flatpaks': flatpaks}

    def _cache_path(self, name):
        return os.path.join(self._cache_dir, f'{name}.json')

    def _load_cached(self, name, max_age=3600):
        path = self._cache_path(name)
        if os.path.exists(path):
            try:
                age = GLib.get_real_time() / 1e6 - os.path.getmtime(path)
                stale = age > max_age
                with open(path) as f:
                    data = json.load(f)
                _log.debug('Cache hit: %s  age=%.0fs  stale=%s', name, age, stale)
                return data, stale
            except Exception as e:
                _log.warning('Cache read failed for %s: %s', name, e)
        else:
            _log.debug('Cache miss: %s', name)
        return None, True

    def _save_cache(self, name, data):
        try:
            with open(self._cache_path(name), 'w') as f:
                json.dump(data, f)
            _log.debug('Cache saved: %s', name)
        except Exception as e:
            _log.warning('Cache write failed for %s: %s', name, e)

    @staticmethod
    def _filter_linux_casks(data):
        """Drop casks that require macOS when running on Linux."""
        if not sys.platform.startswith('linux'):
            return data
        return [d for d in data if 'macos' not in (d.get('depends_on') or {})]

    def _get_host_brew_cache_paths(self):
        """Get the paths to the system Homebrew JWS cache files."""
        # Typically ~/.cache/Homebrew/api/formula.jws.json
        cache_dir = os.path.expanduser('~/.cache/Homebrew/api')
        return {
            'formula': os.path.join(cache_dir, 'formula.jws.json'),
            'cask': os.path.join(cache_dir, 'cask.jws.json')
        }

    def _load_from_host_jws(self, pkg_type):
        """
        Attempt to read and parse the host Homebrew's signed JWS cache files
        to avoid downloading large files over the network.
        """
        paths = self._get_host_brew_cache_paths()
        path = paths.get(pkg_type)
        if not path or not os.path.exists(path):
            _log.debug('System Homebrew cache not found at %s', path)
            return None
        try:
            display_name = "formulae" if pkg_type == "formula" else "casks"
            self._update_status(_(f"Reading system Homebrew {display_name} catalog…"))
            _log.info('Found system Homebrew cached JWS file for %s at %s', pkg_type, path)
            with open(path, 'r', encoding='utf-8') as f:
                jws_data = json.load(f)

            payload_str = jws_data.get('payload')
            if not payload_str:
                _log.warning('No payload key in JWS file at %s', path)
                return None

            if isinstance(payload_str, str):
                payload = json.loads(payload_str)
            else:
                payload = payload_str

            _log.info('Successfully parsed %d %s items from system Homebrew JWS cache!', len(payload), pkg_type)
            return payload
        except Exception as e:
            _log.warning('Failed to parse system Homebrew JWS cache at %s: %s', path, e)
            return None

    def refresh_cache_files(self):
        """Fetch/load and save fresh formulae and casks cache files, and rebuild search cache."""
        with self._refresh_lock:
            # Double check if cache is fresh before doing heavy work
            double_check_data, double_check_stale = self._load_cached('formulae', max_age=14400)
            if double_check_data and not double_check_stale:
                _log.debug('Cache is already fresh, skipping refresh_cache_files')
                return

            _log.info('refresh_cache_files starting')
            
            # 1. Formulae
            new_data_f = self._load_from_host_jws('formula')
            if not new_data_f:
                _log.debug('System Homebrew formula cache not available, downloading…')
                new_data_f = self._fetch_json(FORMULA_API)
            if new_data_f:
                self._save_cache('formulae', new_data_f)
                self._formulae = [
                    Package(d, 'formula', self._installed_formulae) for d in new_data_f
                ]
                # Homebrew 6.0.0+: analytics are no longer embedded — fetch separately
                analytics_thread = threading.Thread(
                    target=self._patch_analytics,
                    args=(self._formulae,),
                    daemon=True,
                )
                analytics_thread.start()
                
            # 2. Casks
            new_data_c = self._load_from_host_jws('cask')
            if not new_data_c:
                _log.debug('System Homebrew cask cache not available, downloading…')
                new_data_c = self._fetch_json(CASK_API)
            if new_data_c:
                self._save_cache('casks', new_data_c)
                new_data_c = self._filter_linux_casks(new_data_c)
                self._casks = [
                    Package(d, 'cask', self._installed_casks) for d in new_data_c
                ]
                
            self._build_search_provider_cache()
            _log.info('refresh_cache_files completed')

    def _build_search_provider_cache(self):
        """Build a lightweight cache of Linux-compatible packages for the search provider."""
        _log.info('Building search provider cache…')
        sp_cache_path = os.path.join(self._cache_dir, 'linux_packages.json')
        packages_data = []

        for pkg in self._formulae:
            packages_data.append({
                'name': pkg.name,
                'display_name': pkg.display_name,
                'description': pkg.description,
                'pkg_type': pkg.pkg_type,
            })

        for pkg in self._casks:
            packages_data.append({
                'name': pkg.name,
                'display_name': pkg.display_name,
                'description': pkg.description,
                'pkg_type': pkg.pkg_type,
            })

        try:
            with open(sp_cache_path, 'w', encoding='utf-8') as f:
                json.dump(packages_data, f)
            _log.info('Saved search provider cache to %s (%d packages)', sp_cache_path, len(packages_data))
        except Exception as e:
            _log.error('Failed to save search provider cache: %s', e)
