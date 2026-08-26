# backend_remote.py - Remote catalog/detail/analytics fetching (mixin for BrewBackend)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Extracted from backend.py (tuna-os/Tavern#81): JSON catalog/detail/analytics
# fetches, analytics patching, version history, and related-package lookups.
# Follows the same mixin composition already used for TapsMixin/MediaMixin/
# CacheMixin — this class expects the usual BrewBackend instance state
# (`self._formulae`, `self._casks`, the cache methods, and
# `_update_status`/`_update_progress`) to exist on whatever it's mixed into,
# exactly as the original methods did as part of BrewBackend. `urlopen` and
# `_brew_cmd` resolve through the backend module so test monkeypatches of
# tavern.backend.* keep working (see taps.py).

import gettext
import gzip
import io
import json
import subprocess
import threading
from urllib.request import Request
from urllib.error import URLError

from gi.repository import GLib

from .logging_util import get_logger, log_timing

_ = gettext.gettext

_log = get_logger('backend_remote')


# Homebrew API endpoints
FORMULA_API = 'https://formulae.brew.sh/api/formula.json'
CASK_API = 'https://formulae.brew.sh/api/cask.json'
FORMULA_DETAIL_API = 'https://formulae.brew.sh/api/formula/{}.json'
CASK_DETAIL_API = 'https://formulae.brew.sh/api/cask/{}.json'
ANALYTICS_ON_REQUEST_API = 'https://formulae.brew.sh/api/analytics/install-on-request/{}.json'
FLATHUB_APPSTREAM_API = 'https://flathub.org/api/v2/appstream/{}'
CURATION_API = 'https://raw.githubusercontent.com/tuna-os/Tavern/main/data/curation.json'


def urlopen(req, timeout=None):
    """Resolve through the backend module so test monkeypatches of
    tavern.backend.urlopen keep working for remote fetches."""
    from . import backend
    return backend.urlopen(req, timeout=timeout)


def _brew_cmd(args):
    """Resolve through the backend module so test monkeypatches of
    tavern.backend._brew_cmd keep working (see taps.py)."""
    from . import backend
    return backend._brew_cmd(args)


class RemoteMixin:
    """Remote catalog/detail/analytics fetching mixed into BrewBackend."""

    def get_curation(self):
        """Return validated, cached curation with an offline-safe fallback."""
        from .catalog_policy import DEFAULT_CURATION, validate_curation

        cached, is_stale = self._load_cached('curation', max_age=21600)
        candidates = []
        if cached and not is_stale:
            candidates.append(cached)
        else:
            remote = self._fetch_json(CURATION_API)
            if remote:
                candidates.append(remote)
            if cached:
                candidates.append(cached)
        candidates.append(DEFAULT_CURATION)
        for candidate in candidates:
            try:
                curation = validate_curation(candidate)
                if candidate is not DEFAULT_CURATION:
                    self._save_cache('curation', curation)
                return curation
            except ValueError as error:
                _log.warning('Rejected invalid curation metadata: %s', error)
        return validate_curation(DEFAULT_CURATION)

    def get_curation_async(self, callback):
        def worker():
            curation = self.get_curation()
            GLib.idle_add(callback, curation)
        threading.Thread(target=worker, daemon=True, name='tavern-curation').start()

    def get_flatpak_info(self, app_id):
        """Fetch Flatpak appstream metadata from Flathub."""
        from .logging_util import log_timing
        with log_timing(f'fetch flatpak appstream {app_id}', 'brewfile'):
            return self._fetch_json(FLATHUB_APPSTREAM_API.format(app_id))

    def get_version_history(self, package_name, pkg_type='formula'):
        """Fetch version history and changelogs from the package's git repository.
        
        Supports multiple git forges: GitHub, GitLab, Codeberg, etc.
        
        Args:
            package_name: Name of the package (formula or cask)
            pkg_type: Type of package ('formula' or 'cask')
        
        Returns:
            List of dicts: [{version, date, changelog}, ...]
        """
        from .git_forge import get_forge_for_url
        
        _log.debug('Getting version history for %s (%s)', package_name, pkg_type)
        
        # Find the package to get its source URL
        package = None
        if pkg_type == 'formula':
            package = next((p for p in self._formulae if p.name == package_name), None)
        elif pkg_type == 'cask':
            package = next((p for p in self._casks if p.name == package_name), None)
        
        if not package or not package.source_url:
            _log.warning('Could not find package or source URL: %s (%s)', package_name, pkg_type)
            return []
        
        # Get the appropriate forge handler
        forge, owner, repo = get_forge_for_url(package.source_url)
        if not forge or not owner or not repo:
            _log.warning('Could not detect git forge for URL: %s', package.source_url)
            return []
        
        _log.info('Detected forge for %s: %s/%s', package_name, owner, repo)
        
        # Check cache first (24h TTL)
        cache_key = f'version-history-{pkg_type}-{package_name}'
        cached_data, is_stale = self._load_cached(cache_key)
        if cached_data and not is_stale:
            _log.debug('Version history cache hit for %s', package_name)
            return cached_data
        
        # Fetch from git forge
        try:
            history = forge.get_releases(owner, repo)
            if history:
                self._save_cache(cache_key, history)
            return history
        except Exception as e:
            _log.error('Failed to fetch version history: %s', e)
            return []

    def _fetch_json(self, url):
        """Fetch JSON from URL with a timeout and detailed error reporting."""
        _log.debug('Fetching JSON: %s', url)
        import gzip
        req = Request(url, headers={
            'User-Agent': 'Tavern/0.1',
            'Accept-Encoding': 'gzip'
        })
        try:
            with log_timing(f'fetch_json {url}', 'backend'):
                with urlopen(req, timeout=120) as resp:
                    content_length = None
                    if hasattr(resp, 'info'):
                        headers = resp.info()
                        content_length_str = headers.get('Content-Length')
                        if content_length_str:
                            try:
                                content_length = int(content_length_str)
                            except ValueError:
                                pass
                    
                    buffer = io.BytesIO()
                    downloaded = 0
                    chunk_size = 65536 # 64KB chunks
                    
                    # Only the two catalog downloads drive the loading
                    # screen; analytics/detail fetches must not touch it.
                    is_formula = url == FORMULA_API
                    is_cask = url == CASK_API
                    is_catalog = is_formula or is_cask
                    display_name = "formulae" if is_formula else "casks"

                    if is_catalog:
                        self._update_status(_(f"Downloading Homebrew {display_name} catalog…"))
                    
                    read_all = False
                    while True:
                        if read_all:
                            break
                        try:
                            chunk = resp.read(chunk_size)
                        except TypeError:
                            chunk = resp.read()
                            read_all = True
                        
                        if not chunk:
                            break
                        buffer.write(chunk)
                        downloaded += len(chunk)
                        
                        if not is_catalog:
                            continue
                        if content_length:
                            percent = int((downloaded / content_length) * 100)
                            downloaded_mb = downloaded / (1024 * 1024)
                            total_mb = content_length / (1024 * 1024)
                            self._update_status(_(f"Downloading Homebrew {display_name} catalog ({percent}%: {downloaded_mb:.1f} MB / {total_mb:.1f} MB)…"))

                            # Scale the progress bar fraction
                            fraction = downloaded / content_length
                            if is_formula:
                                self._update_progress(0.2 + fraction * 0.4)
                            else:
                                self._update_progress(0.6 + fraction * 0.3)
                        else:
                            downloaded_mb = downloaded / (1024 * 1024)
                            self._update_status(_(f"Downloading Homebrew {display_name} catalog ({downloaded_mb:.1f} MB)…"))
                            
                    content = buffer.getvalue()
                    
                    is_gzip = False
                    if hasattr(resp, 'info'):
                        headers = resp.info()
                        if headers and headers.get('Content-Encoding') == 'gzip':
                            is_gzip = True
                    if is_gzip:
                        if is_catalog:
                            self._update_status(_(f"Decompressing Homebrew {display_name} catalog…"))
                        _log.debug('Decompressing gzip response for %s', url)
                        content = gzip.decompress(content)
                    
                    if is_catalog:
                        self._update_status(_(f"Parsing Homebrew {display_name} catalog…"))
                    data = json.loads(content.decode('utf-8'))
            _log.debug('Fetched JSON OK: %s  (items=%s)',
                       url, len(data) if isinstance(data, list) else '?')
            return data
        except json.JSONDecodeError as e:
            _log.error('JSON decode error from %s: %s', url, e)
            return None
        except URLError as e:
            # Network/DNS/connection error
            _log.error('Failed to fetch %s (network error): %s', url, e)
            return None
        except Exception as e:
            # Timeout or other errors
            _log.error('Failed to fetch %s: %s', url, type(e).__name__)
            return None

    def _fetch_analytics_data(self):
        """Fetch install-on-request analytics for 30d/90d/365d from the
        separate analytics endpoints (Homebrew 6.0.0+ no longer embeds
        analytics in formula.json).

        Returns dict of {formula_name: {'installs_30d': int, ...}}.
        """
        cache_key = 'analytics'
        cached, is_stale = self._load_cached(cache_key, max_age=86400)  # 24 h
        if cached and not is_stale:
            _log.debug('Analytics cache hit (%d entries)', len(cached))
            return cached

        analytics = {}
        periods = ('30d', '90d', '365d')
        for period in periods:
            try:
                url = ANALYTICS_ON_REQUEST_API.format(period)
                data = self._fetch_json(url)
                if data and isinstance(data, dict):
                    items = data.get('items', [])
                    for item in items:
                        name = item.get('formula', '')
                        if not name:
                            continue
                        count_str = item.get('count', '0')
                        try:
                            count = int(count_str.replace(',', ''))
                        except (ValueError, AttributeError):
                            count = 0
                        entry = analytics.setdefault(name, {})
                        entry[f'installs_{period}'] = count
                    _log.info('Fetched %d analytics entries for %s', len(items), period)
            except Exception as e:
                _log.warning('Failed to fetch analytics for %s: %s', period, e)

        if analytics:
            self._save_cache(cache_key, analytics)
        return analytics

    def _patch_analytics(self, formulae):
        """Fetch analytics and patch install counts onto formula Package objects."""
        analytics = self._fetch_analytics_data()
        if not analytics:
            return
        patched = 0
        for pkg in formulae:
            counts = analytics.get(pkg.name)
            if counts:
                pkg._raw_analytics = counts
                patched += 1
        _log.info('Patched analytics for %d/%d formulae', patched, len(formulae))
        # Trigger UI update for popularity badges
        GLib.idle_add(self.emit, 'formulae-loaded', self._formulae)

    def get_related_packages(self, package, limit=6):
        """Return packages related to `package` for the details-page carousel.

        Combines three signals, in priority order:
          1. Direct runtime dependencies (formulae listed in `dependencies`)
          2. Same-tap siblings (other packages from the same non-core tap)
          3. Name-prefix matches (fallback for the @-versioned variant case)

        Deduplicates against `package` itself and caps the result at `limit`.
        Variants (e.g. `python@3.10`, `python@3.11`) are returned separately
        via `get_variants()` so they can be displayed in their own row.
        """
        by_name = {p.name: p for p in self._formulae}
        by_name.update({p.name: p for p in self._casks})

        related = []
        seen = {package.name, package.full_name}

        # 1. Direct deps
        for dep_name in getattr(package, 'dependencies', []) or []:
            if dep_name in seen:
                continue
            p = by_name.get(dep_name)
            if p:
                related.append(p)
                seen.add(p.name)
                if len(related) >= limit:
                    return related

        # 2. Same-tap siblings (skip core taps — too noisy)
        tap = getattr(package, 'tap', '') or ''
        if tap and tap not in ('homebrew/core', 'homebrew/cask'):
            for p in self._formulae + self._casks:
                if p.name in seen:
                    continue
                if getattr(p, 'tap', '') == tap:
                    related.append(p)
                    seen.add(p.name)
                    if len(related) >= limit:
                        return related

        # 3. Name-prefix fallback (preserves prior behavior)
        base = package.name.split('@')[0]
        if base:
            for p in self._formulae + self._casks:
                if p.name in seen:
                    continue
                if p.name.startswith(base) and p.name.split('@')[0] != base:
                    # Skip; that's a variant, handled by get_variants
                    continue
                if p.name.startswith(base) or base in p.name:
                    related.append(p)
                    seen.add(p.name)
                    if len(related) >= limit:
                        break

        return related

    def get_variants(self, package, limit=6):
        """Return versioned siblings like `python@3.10` for `python`."""
        base = package.name.split('@')[0]
        if not base:
            return []
        out = []
        for p in self._formulae + self._casks:
            if p.name == package.name or p.full_name == package.full_name:
                continue
            if p.name.split('@')[0] == base:
                out.append(p)
                if len(out) >= limit:
                    break
        return out

    def get_package_info(self, name, pkg_type='formula'):
        """Get package info synchronously (for brewfile loading)."""
        try:
            # First try the API
            if pkg_type == 'formula':
                url = FORMULA_DETAIL_API.format(name)
            else:
                url = CASK_DETAIL_API.format(name)
            
            data = self._fetch_json(url)
            if data:
                return data
        except Exception as e:
            _log.debug('API fetch failed for %s, trying brew command: %s', name, e)
        
        # Fallback to brew info command (for custom taps)
        try:
            _log.info('Using brew info for %s', name)
            cmd_type = '--formula' if pkg_type == 'formula' else '--cask'
            result = subprocess.run(
                _brew_cmd(['info', '--json=v2', cmd_type, name]),
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                # Extract the package from the json response
                key = 'formulae' if pkg_type == 'formula' else 'casks'
                if key in data and len(data[key]) > 0:
                    pkg_data = data[key][0]
                    _log.debug('Got package info from brew command: %s', pkg_data.get('name'))
                    return pkg_data
            else:
                _log.warning('brew info failed for %s: %s', name, result.stderr)
        except Exception as e:
            _log.error('brew info command failed for %s: %s', name, e)
        
        return None

    def get_package_info_async(self, package, callback):
        """Get detailed info for a package asynchronously."""
        thread = threading.Thread(
            target=self._get_package_info_thread,
            args=(package, callback),
            daemon=True,
        )
        thread.start()

    def _get_package_info_thread(self, package, callback):
        _log.debug('Fetching detail info for %s (%s)', package.name, package.pkg_type)
        if package.pkg_type == 'formula':
            url = FORMULA_DETAIL_API.format(package.name)
        else:
            url = CASK_DETAIL_API.format(package.name)

        data = self._fetch_json(url)
        GLib.idle_add(callback, package, data)
