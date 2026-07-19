# backend.py - Homebrew backend using the formulae.brew.sh JSON API + local brew CLI
# SPDX-License-Identifier: GPL-3.0-or-later

import io
import json
import os
import struct
import sys
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.request import urlopen, Request
from urllib.error import URLError

import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gio, GLib, GObject, GdkPixbuf

from .logging_util import get_logger, profile, log_timing

_log = get_logger('backend')


# Homebrew API endpoints
FORMULA_API = 'https://formulae.brew.sh/api/formula.json'
CASK_API = 'https://formulae.brew.sh/api/cask.json'
FORMULA_DETAIL_API = 'https://formulae.brew.sh/api/formula/{}.json'
CASK_DETAIL_API = 'https://formulae.brew.sh/api/cask/{}.json'
ANALYTICS_ON_REQUEST_API = 'https://formulae.brew.sh/api/analytics/install-on-request/{}.json'
FLATHUB_APPSTREAM_API = 'https://flathub.org/api/v2/appstream/{}'


from .backend_icons import ico_to_png as _ico_to_png  # noqa: F401  (re-exported)
from .brew_env import (  # noqa: F401  (re-exported for compat)
    IN_FLATPAK, BREW_BIN, _is_flatpak, _find_brew,
)


def _brew_cmd(args):
    """Build a command list for running brew, using flatpak-spawn if sandboxed.

    Lives in this module (reading module globals) so tests and callers can
    monkeypatch tavern.backend.IN_FLATPAK / BREW_BIN.
    """
    if IN_FLATPAK:
        # Use flatpak-spawn to run brew on the host with updates disabled
        return ['flatpak-spawn', '--host', 'bash', '-c',
                f'export HOMEBREW_NO_AUTO_UPDATE=1 && export HOMEBREW_API_AUTO_UPDATE_SECS=604800 && export HOMEBREW_NO_INSTALL_ASK=1 && '
                f'eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)" && brew {" ".join(args)}']
    else:
        return [BREW_BIN] + args
from .package import Package  # noqa: F401  (re-exported)
from .taps import TapsMixin
from .media import MediaMixin


class BrewBackend(TapsMixin, MediaMixin, GObject.Object):
    """Backend that communicates with both the Homebrew JSON API and local brew CLI."""

    __gtype_name__ = 'TavernBrewBackend'

    loading = GObject.Property(type=bool, default=False)
    loading_status = GObject.Property(type=str, default='Loading Homebrew Content…')
    loading_progress = GObject.Property(type=float, default=0.0)
    _refresh_lock = threading.Lock()

    def _update_status(self, msg):
        _log.info('Status update: %s', msg)
        GLib.idle_add(setattr, self, 'loading_status', msg)

    def _update_progress(self, val):
        GLib.idle_add(setattr, self, 'loading_progress', float(val))

    __gsignals__ = {
        'formulae-loaded': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'casks-loaded': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'installed-loaded': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'taps-loaded': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'outdated-changed': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'pinned-changed': (GObject.SignalFlags.RUN_LAST, None, (object,)),
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._formulae = []
        self._casks = []
        self._installed_formulae = set()
        self._installed_casks = set()
        self._tap_packages = {}  # tap_name -> [Package, ...]
        self._tap_list = []  # [{name, path}, ...] for non-core taps
        self._outdated_formulae = {}  # {name: {installed, latest}}
        self._outdated_casks = {}  # {name: {installed, latest}}
        self._outdated_lock = threading.Lock()
        self._pinned = set()  # formula names pinned via `brew pin`
        self._pinned_lock = threading.Lock()
        self._search_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='tavern-search')
        self._search_generation = 0
        self._icon_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix='tavern-icon')
        self._icon_inflight = {}  # package name -> [(package, callback), ...]
        self._icon_lock = threading.Lock()
        self._cache_dir = os.path.join(GLib.get_user_cache_dir(), 'tavern')
        os.makedirs(self._cache_dir, exist_ok=True)
        _log.debug('BrewBackend init  cache_dir=%s', self._cache_dir)

    def parse_brewfile(self, path):
        import re
        from .logging_util import log_timing
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


    @property
    def formulae(self):
        return self._formulae

    @property
    def casks(self):
        return self._casks

    @property
    def taps(self):
        return self._tap_list

    def get_packages_for_tap(self, tap_name):
        return self._tap_packages.get(tap_name, [])

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
                        self._update_status(f"Downloading Homebrew {display_name} catalog…")
                    
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
                            self._update_status(f"Downloading Homebrew {display_name} catalog ({percent}%: {downloaded_mb:.1f} MB / {total_mb:.1f} MB)…")

                            # Scale the progress bar fraction
                            fraction = downloaded / content_length
                            if is_formula:
                                self._update_progress(0.2 + fraction * 0.4)
                            else:
                                self._update_progress(0.6 + fraction * 0.3)
                        else:
                            downloaded_mb = downloaded / (1024 * 1024)
                            self._update_status(f"Downloading Homebrew {display_name} catalog ({downloaded_mb:.1f} MB)…")
                            
                    content = buffer.getvalue()
                    
                    is_gzip = False
                    if hasattr(resp, 'info'):
                        headers = resp.info()
                        if headers and headers.get('Content-Encoding') == 'gzip':
                            is_gzip = True
                    if is_gzip:
                        if is_catalog:
                            self._update_status(f"Decompressing Homebrew {display_name} catalog…")
                        _log.debug('Decompressing gzip response for %s', url)
                        content = gzip.decompress(content)
                    
                    if is_catalog:
                        self._update_status(f"Parsing Homebrew {display_name} catalog…")
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
            self._update_status(f"Reading system Homebrew {display_name} catalog…")
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

    def refresh_cache_files(self):
        """Fetch/load and save fresh formulae and casks cache files, and rebuild search cache."""
        with BrewBackend._refresh_lock:
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

    def _get_installed(self):
        """Get sets of installed formula and cask names."""
        formulae = set()
        casks = set()
        try:
            with log_timing('brew list --formula', 'backend'):
                result = subprocess.run(
                    _brew_cmd(['list', '--formula', '-1']),
                    capture_output=True, text=True, timeout=30,
                )
            if result.returncode == 0:
                formulae = set(result.stdout.strip().split('\n')) - {''}
                _log.info('Installed formulae: %d', len(formulae))
        except Exception as e:
            _log.error('Failed to list installed formulae: %s', e)

        try:
            with log_timing('brew list --cask', 'backend'):
                result = subprocess.run(
                    _brew_cmd(['list', '--cask', '-1']),
                    capture_output=True, text=True, timeout=30,
                )
            if result.returncode == 0:
                casks = set(result.stdout.strip().split('\n')) - {''}
                _log.info('Installed casks: %d', len(casks))
        except Exception as e:
            _log.error('Failed to list installed casks: %s', e)

        return formulae, casks

    def _check_outdated(self):
        """Check for outdated formulae and casks using brew outdated."""
        _log.info('Checking for outdated packages')
        try:
            with log_timing('brew outdated', 'backend'):
                result = subprocess.run(
                    _brew_cmd(['outdated', '--json=v2']),
                    capture_output=True, text=True, timeout=30,
                )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                outdated_f = {}
                outdated_c = {}

                pinned = self.get_pinned()
                # Parse formulae
                for item in data.get('formulae', []):
                    name = item.get('name', '')
                    if name and name not in pinned:
                        outdated_f[name] = {
                            'pkg_type': 'formula',
                            'installed': item.get('installed_versions', [''])[0] if item.get('installed_versions') else '',
                            'latest': item.get('current_version', ''),
                        }

                # Parse casks
                for item in data.get('casks', []):
                    name = item.get('name', '')
                    if name:
                        outdated_c[name] = {
                            'pkg_type': 'cask',
                            'installed': item.get('installed_versions', [''])[0] if item.get('installed_versions') else '',
                            'latest': item.get('current_version', ''),
                        }

                with self._outdated_lock:
                    self._outdated_formulae = outdated_f
                    self._outdated_casks = outdated_c

                total = len(outdated_f) + len(outdated_c)
                _log.info('Found %d outdated packages (formulae=%d, casks=%d)', 
                         total, len(outdated_f), len(outdated_c))
                
                # Emit signal with combined list
                outdated_list = list(outdated_f.items()) + list(outdated_c.items())
                GLib.idle_add(self.emit, 'outdated-changed', outdated_list)
            else:
                _log.warning('brew outdated failed with return code %d', result.returncode)
        except subprocess.TimeoutExpired:
            _log.warning('brew outdated timed out after 30s')
        except json.JSONDecodeError as e:
            _log.error('Failed to parse brew outdated output: %s', e)
        except Exception as e:
            _log.error('Failed to check outdated packages: %s', e)

    def load_all_async(self):
        """Load all package data asynchronously."""
        _log.info('load_all_async() starting')
        self.loading = True
        thread = threading.Thread(target=self._load_all_thread, daemon=True)
        thread.start()

    def _load_all_thread(self):
        _log.debug('_load_all_thread started')
        self._update_progress(0.0)
        self._update_status("Scanning installed packages…")
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
        self._update_status("Loading Homebrew formulae catalog…")
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
        self._update_status("Loading Homebrew casks catalog…")
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
            with BrewBackend._refresh_lock:
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
            with BrewBackend._refresh_lock:
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
            self._update_status("Scanning local taps…")
            _log.debug('No cache was available on launch, scanning taps and clearing spinner now')
            self._load_tap_packages()
            self._update_progress(0.96)
            GLib.idle_add(self._set_loading_false)

        self._update_progress(0.98)
        self._update_status("Building search provider index…")
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

    def _apply_installed_changes(self, changes):
        for pkg, inst in changes:
            pkg.installed = inst
        self.emit('installed-loaded', [])

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

    def get_installed_packages(self):
        """Return list of installed Package objects."""
        installed = []
        for pkg in self._formulae:
            if pkg.installed:
                installed.append(pkg)
        for pkg in self._casks:
            if pkg.installed:
                installed.append(pkg)
        return installed

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

    def is_pinned(self, name):
        with self._pinned_lock:
            return name in self._pinned

    def get_pinned(self):
        with self._pinned_lock:
            return set(self._pinned)

    def _load_pinned(self):
        """Refresh the pinned-formula set by listing the pinned-symlinks dir."""
        try:
            with log_timing('brew list --pinned', 'backend'):
                result = subprocess.run(
                    _brew_cmd(['list', '--pinned']),
                    capture_output=True, text=True, timeout=15,
                )
            pinned = set()
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    name = line.strip()
                    if name:
                        pinned.add(name)
            else:
                _log.debug('brew list --pinned rc=%d: %s', result.returncode, result.stderr.strip())
            with self._pinned_lock:
                self._pinned = pinned
            _log.info('Pinned formulae: %d', len(pinned))
            # Strip pinned packages from the outdated emission so the
            # Updates card doesn't keep nagging.
            with self._outdated_lock:
                for name in list(self._outdated_formulae.keys()):
                    if name in pinned:
                        del self._outdated_formulae[name]
                outdated_list = (
                    list(self._outdated_formulae.items())
                    + list(self._outdated_casks.items())
                )
            GLib.idle_add(self.emit, 'pinned-changed', set(pinned))
            GLib.idle_add(self.emit, 'outdated-changed', outdated_list)
        except Exception as e:
            _log.error('Failed to load pinned set: %s', e)

    def pin_async(self, package, callback=None):
        """Pin a formula so `brew upgrade` skips it."""
        thread = threading.Thread(
            target=self._run_pin_operation,
            args=('pin', package, callback),
            daemon=True,
        )
        thread.start()

    def unpin_async(self, package, callback=None):
        """Unpin a formula."""
        thread = threading.Thread(
            target=self._run_pin_operation,
            args=('unpin', package, callback),
            daemon=True,
        )
        thread.start()

    def _run_pin_operation(self, operation, package, callback=None):
        # Homebrew 6.0.0+ supports pinning both formulae and casks.
        if package.pkg_type not in ('formula', 'cask'):
            _log.warning('Cannot %s %s: pinning only works on formulae and casks', operation, package.name)
            if callback:
                GLib.idle_add(callback, False, 'Pinning only applies to formulae and casks')
            return
        cmd = _brew_cmd([operation, package.name])
        _log.info('_run_pin_operation: %s', ' '.join(cmd))
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            success = result.returncode == 0
            msg = (result.stdout + result.stderr).strip()
            if success:
                self._load_pinned()
            if callback:
                GLib.idle_add(callback, success, msg)
        except Exception as e:
            _log.error('_run_pin_operation exception: %s %s: %s', operation, package.name, e)
            if callback:
                GLib.idle_add(callback, False, str(e))

    def get_package_info_async(self, package, callback):
        """Get detailed info for a package asynchronously."""
        thread = threading.Thread(
            target=self._get_package_info_thread,
            args=(package, callback),
            daemon=True,
        )
        thread.start()

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

    def _get_package_info_thread(self, package, callback):
        _log.debug('Fetching detail info for %s (%s)', package.name, package.pkg_type)
        if package.pkg_type == 'formula':
            url = FORMULA_DETAIL_API.format(package.name)
        else:
            url = CASK_DETAIL_API.format(package.name)

        data = self._fetch_json(url)
        GLib.idle_add(callback, package, data)
