# backend.py - Homebrew backend using the formulae.brew.sh JSON API + local brew CLI
# SPDX-License-Identifier: GPL-3.0-or-later

import io
import json
import os
import struct
import subprocess
import threading
from urllib.request import urlopen, Request
from urllib.error import URLError

# Disable Homebrew's automatic update checks when we run brew commands.
# This prevents random hangs and bandwidth waste on slow/capped connections.
os.environ['HOMEBREW_NO_AUTO_UPDATE'] = '1'
os.environ['HOMEBREW_API_AUTO_UPDATE_SECS'] = '604800'
# Homebrew 6.0.0+ defaults to ask mode (confirmation prompt) — suppress it
# so Tavern's subprocess-driven install/remove/upgrade operations don't hang.
os.environ['HOMEBREW_NO_INSTALL_ASK'] = '1'

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
GITHUB_TAP_SEARCH_URL = (
    'https://api.github.com/search/repositories'
    '?q=homebrew-+in:name&sort=stars&order=desc&per_page=80'
)

# Core taps served by the public API — never need to appear in the "Add" list
_CORE_TAPS = frozenset({'homebrew/core', 'homebrew/cask'})


def _is_flatpak():
    """Detect if running inside a Flatpak sandbox."""
    result = os.path.exists('/.flatpak-info')
    _log.debug('Flatpak detection: %s', result)
    return result


def _find_brew():
    """Find the brew executable."""
    candidates = [
        '/home/linuxbrew/.linuxbrew/bin/brew',
        '/opt/homebrew/bin/brew',
        '/usr/local/bin/brew',
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            _log.info('Found brew at %s', c)
            return c
    # fallback: try PATH
    try:
        result = subprocess.run(['which', 'brew'], capture_output=True, text=True)
        if result.returncode == 0:
            path = result.stdout.strip()
            _log.info('Found brew via PATH at %s', path)
            return path
    except Exception:
        pass
    _log.warning('brew executable not found; falling back to bare "brew"')
    return 'brew'


IN_FLATPAK = _is_flatpak()
BREW_BIN = _find_brew()


from .backend_icons import ico_to_png as _ico_to_png  # noqa: E402  (re-exported)


def _brew_cmd(args):
    """Build a command list for running brew, using flatpak-spawn if sandboxed."""
    if IN_FLATPAK:
        # Use flatpak-spawn to run brew on the host with updates disabled
        return ['flatpak-spawn', '--host', 'bash', '-c',
                f'export HOMEBREW_NO_AUTO_UPDATE=1 && export HOMEBREW_API_AUTO_UPDATE_SECS=604800 && export HOMEBREW_NO_INSTALL_ASK=1 && '
                f'eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)" && brew {" ".join(args)}']
    else:
        return [BREW_BIN] + args


class Package(GObject.Object):
    """Represents a Homebrew formula or cask."""

    __gtype_name__ = 'TavernPackage'

    name = GObject.Property(type=str, default='')
    full_name = GObject.Property(type=str, default='')
    description = GObject.Property(type=str, default='')
    homepage = GObject.Property(type=str, default='')
    version = GObject.Property(type=str, default='')
    pkg_type = GObject.Property(type=str, default='formula')  # 'formula', 'cask', or 'flatpak'
    installed = GObject.Property(type=bool, default=False)
    display_name = GObject.Property(type=str, default='')
    icon_url = GObject.Property(type=str, default='')
    license_ = GObject.Property(type=str, default='')

    # Live task state (driven by TaskManager)
    task_active   = GObject.Property(type=bool,  default=False)
    task_progress = GObject.Property(type=float, default=0.0)
    task_label    = GObject.Property(type=str,   default='')

    def __init__(self, data=None, pkg_type='formula', installed_set=None, **kwargs):
        props = {}
        self._raw_analytics = {}
        self.source_url = ''
        self.dependencies = []  # list[str] — formula names this package depends on
        self.tap = ''           # e.g. 'homebrew/core' or 'foo/bar' for tapped pkgs
        self._installs_30d = None
        self._installs_90d = None
        self._installs_365d = None

        if data:
            props['pkg_type'] = pkg_type
            if pkg_type == 'formula':
                name = data.get('name', '')
                props['name'] = name
                props['full_name'] = data.get('full_name', name)
                props['display_name'] = name
                props['description'] = data.get('desc', '') or ''
                props['homepage'] = data.get('homepage', '') or ''
                versions = data.get('versions', {})
                props['version'] = versions.get('stable', '') or '' if isinstance(versions, dict) else ''
                props['license_'] = data.get('license', '') or ''
                # Stable source URL — often a github.com release tarball
                urls = data.get('urls', {})
                stable = urls.get('stable', {}) if isinstance(urls, dict) else {}
                self.source_url = stable.get('url', '') or '' if isinstance(stable, dict) else ''
                deps = data.get('dependencies', []) or []
                self.dependencies = [d for d in deps if isinstance(d, str)]
                self.tap = data.get('tap', '') or ''
            elif pkg_type == 'cask':
                name = data.get('token', '')
                props['name'] = name
                props['full_name'] = data.get('full_token', name)
                names = data.get('name', [])
                props['display_name'] = names[0] if names else name
                props['description'] = data.get('desc', '') or ''
                props['homepage'] = data.get('homepage', '') or ''
                props['version'] = data.get('version', '') or ''
                props['license_'] = ''
                # Cask download URL
                self.source_url = data.get('url', '') or ''
                self.tap = data.get('tap', '') or ''
            else:
                # Flatpak appstream object
                app_id = data.get('id', '')
                props['name'] = app_id
                props['full_name'] = app_id
                props['display_name'] = data.get('name', '') or app_id
                props['description'] = data.get('summary', '') or ''
                props['homepage'] = (data.get('urls', {}) or {}).get('homepage', '') if isinstance(data.get('urls', {}), dict) else ''
                releases = data.get('releases', []) or []
                if isinstance(releases, list) and releases:
                    props['version'] = (releases[0] or {}).get('version', '') or ''
                else:
                    props['version'] = ''
                self.source_url = props['homepage']
                props['icon_url'] = data.get('icon', '') or ''

            if installed_set:
                props['installed'] = name in installed_set or props.get('full_name', '') in installed_set

            self._raw_analytics = data.get('analytics', {})

        # Merge any caller-provided kwargs (takes precedence)
        for k, v in kwargs.items():
            props[k] = v

        super().__init__(**props)

    def _from_api(self, data, pkg_type, installed_set=None):
        self._raw_analytics = data.get('analytics', {})
        self._installs_30d = None
        self._installs_90d = None
        self._installs_365d = None

        if pkg_type == 'formula':
            name = data.get('name', '')
            self.name = name
            self.full_name = data.get('full_name', name)
            self.display_name = name
            self.description = data.get('desc', '') or ''
            self.homepage = data.get('homepage', '') or ''
            versions = data.get('versions', {})
            self.version = versions.get('stable', '') or '' if isinstance(versions, dict) else ''
            self.license_ = data.get('license', '') or ''
            # Stable source URL — often a github.com release tarball
            urls = data.get('urls', {})
            stable = urls.get('stable', {}) if isinstance(urls, dict) else {}
            self.source_url = stable.get('url', '') or '' if isinstance(stable, dict) else ''
            deps = data.get('dependencies', []) or []
            self.dependencies = [d for d in deps if isinstance(d, str)]
            self.tap = data.get('tap', '') or ''
        elif pkg_type == 'cask':
            name = data.get('token', '')
            self.name = name
            self.full_name = data.get('full_token', name)
            names = data.get('name', [])
            self.display_name = names[0] if names else name
            self.description = data.get('desc', '') or ''
            self.homepage = data.get('homepage', '') or ''
            self.version = data.get('version', '') or ''
            self.license_ = ''
            # Cask download URL
            self.source_url = data.get('url', '') or ''
            self.tap = data.get('tap', '') or ''
        else:
            app_id = data.get('id', '')
            self.name = app_id
            self.full_name = app_id
            self.display_name = data.get('name', '') or app_id
            self.description = data.get('summary', '') or ''
            self.homepage = (data.get('urls', {}) or {}).get('homepage', '') if isinstance(data.get('urls', {}), dict) else ''
            releases = data.get('releases', []) or []
            if isinstance(releases, list) and releases:
                self.version = (releases[0] or {}).get('version', '') or ''
            else:
                self.version = ''
            self.source_url = self.homepage
            self.icon_url = data.get('icon', '') or ''

        if installed_set:
            self.installed = name in installed_set or self.full_name in installed_set

    def _parse_analytics(self):
        if self._installs_30d is not None:
            return
        if not self._raw_analytics:
            self._installs_30d = 0
            self._installs_90d = 0
            self._installs_365d = 0
            return
        # _raw_analytics is now a flat dict: {'installs_30d': int, ...}
        # pre-populated from the separate analytics endpoints
        self._installs_30d = self._raw_analytics.get('installs_30d', 0) or 0
        self._installs_90d = self._raw_analytics.get('installs_90d', 0) or 0
        self._installs_365d = self._raw_analytics.get('installs_365d', 0) or 0

    @GObject.Property(type=int, default=0)
    def installs_30d(self):
        self._parse_analytics()
        return self._installs_30d

    @installs_30d.setter
    def installs_30d(self, value):
        self._installs_30d = value

    @GObject.Property(type=int, default=0)
    def installs_90d(self):
        self._parse_analytics()
        return self._installs_90d

    @installs_90d.setter
    def installs_90d(self, value):
        self._installs_90d = value

    @GObject.Property(type=int, default=0)
    def installs_365d(self):
        self._parse_analytics()
        return self._installs_365d

    @installs_365d.setter
    def installs_365d(self, value):
        self._installs_365d = value



class BrewBackend(GObject.Object):
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
        'operation-complete': (GObject.SignalFlags.RUN_LAST, None, (bool, str)),
        'operation-output': (GObject.SignalFlags.RUN_LAST, None, (str,)),
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
                    
                    url_basename = url.split('/')[-1]
                    is_formula = "formula" in url_basename
                    is_cask = "cask" in url_basename
                    display_name = "formulae" if is_formula else "casks"
                    
                    self._update_status(f"Downloading Homebrew {display_name} catalog...")
                    
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
                        
                        if content_length:
                            percent = int((downloaded / content_length) * 100)
                            downloaded_mb = downloaded / (1024 * 1024)
                            total_mb = content_length / (1024 * 1024)
                            self._update_status(f"Downloading Homebrew {display_name} catalog ({percent}%: {downloaded_mb:.1f} MB / {total_mb:.1f} MB)...")
                            
                            # Scale the progress bar fraction
                            fraction = downloaded / content_length
                            if is_formula:
                                self._update_progress(0.2 + fraction * 0.4)
                            elif is_cask:
                                self._update_progress(0.6 + fraction * 0.3)
                        else:
                            downloaded_mb = downloaded / (1024 * 1024)
                            self._update_status(f"Downloading Homebrew {display_name} catalog ({downloaded_mb:.1f} MB)...")
                            
                    content = buffer.getvalue()
                    
                    is_gzip = False
                    if hasattr(resp, 'info'):
                        headers = resp.info()
                        if headers and headers.get('Content-Encoding') == 'gzip':
                            is_gzip = True
                    if is_gzip:
                        self._update_status(f"Decompressing Homebrew {display_name} catalog...")
                        _log.debug('Decompressing gzip response for %s', url)
                        content = gzip.decompress(content)
                    
                    self._update_status(f"Parsing Homebrew {display_name} catalog...")
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
            self._update_status(f"Reading system Homebrew {display_name} catalog...")
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
                _log.debug('System Homebrew formula cache not available, downloading...')
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
                _log.debug('System Homebrew cask cache not available, downloading...')
                new_data_c = self._fetch_json(CASK_API)
            if new_data_c:
                self._save_cache('casks', new_data_c)
                import sys
                is_linux = sys.platform.startswith('linux')
                if is_linux:
                    filtered_data = []
                    for d in new_data_c:
                        depends_on = d.get('depends_on', {})
                        if 'macos' not in depends_on:
                            filtered_data.append(d)
                    new_data_c = filtered_data
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
        _log.debug('_check_outdated() starting')
        try:
            with log_timing('brew outdated --json', 'backend'):
                result = subprocess.run(
                    _brew_cmd(['outdated', '--json=v2']),
                    capture_output=True, text=True, timeout=60,
                )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                
                formulae = data.get('formulae', [])
                casks = data.get('casks', [])
                
                pinned = self.get_pinned()
                with self._outdated_lock:
                    self._outdated_formulae = {}
                    for f in formulae:
                        name = f.get('name', '')
                        if name and name not in pinned:
                            self._outdated_formulae[name] = {
                                'installed': f.get('installed_versions', [''])[0],
                                'latest': f.get('current_version', '')
                            }

                    self._outdated_casks = {}
                    for c in casks:
                        name = c.get('name', '')
                        if name:
                            self._outdated_casks[name] = {
                                'installed': c.get('installed_versions', [''])[0],
                                'latest': c.get('current_version', '')
                            }

                outdated_list = list(self._outdated_formulae.items()) + list(self._outdated_casks.items())
                _log.info('Found %d outdated packages (formulae=%d, casks=%d)',
                         len(outdated_list), len(self._outdated_formulae), len(self._outdated_casks))
                
                # Emit signal on main thread
                GLib.idle_add(self.emit, 'outdated-changed', outdated_list)
            else:
                _log.warning('brew outdated returned %d: %s', result.returncode, result.stderr)
        except json.JSONDecodeError as e:
            _log.error('Failed to parse brew outdated JSON: %s', e)
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
        self._update_status("Scanning installed packages...")
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
        self._update_status("Loading Homebrew formulae catalog...")
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
        self._update_status("Loading Homebrew casks catalog...")
        self._update_progress(0.15)
        has_cache_c = False
        data_c, is_stale_c = self._load_cached('casks', max_age=43200)
        if data_c:
            has_cache_c = True
            import sys
            is_linux = sys.platform.startswith('linux')
            
            if is_linux:
                filtered_data = []
                for d in data_c:
                    depends_on = d.get('depends_on', {})
                    if 'macos' not in depends_on:
                        filtered_data.append(d)
                data_c = filtered_data

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
            _log.debug('Formulae cache missing or stale, refreshing...')
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
                        _log.debug('System Homebrew cache not available or invalid, fetching from API...')
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
            _log.debug('Casks cache missing or stale, refreshing...')
            with BrewBackend._refresh_lock:
                # Double check if cache is still missing or stale after acquiring the lock
                double_check_data, double_check_stale = self._load_cached('casks', max_age=43200)
                if double_check_data and not double_check_stale:
                    _log.debug('Casks cache was refreshed by another thread, loading from cache')
                    
                    import sys
                    is_linux = sys.platform.startswith('linux')
                    if is_linux:
                        filtered_data = []
                        for d in double_check_data:
                            depends_on = d.get('depends_on', {})
                            if 'macos' not in depends_on:
                                filtered_data.append(d)
                        double_check_data = filtered_data

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
                        _log.debug('System Homebrew cache not available or invalid, fetching from API...')
                        new_data = self._fetch_json(CASK_API)
                    if new_data:
                        self._save_cache('casks', new_data)
                        
                        import sys
                        is_linux = sys.platform.startswith('linux')
                        
                        if is_linux:
                            filtered_data = []
                            for d in new_data:
                                depends_on = d.get('depends_on', {})
                                if 'macos' not in depends_on:
                                    filtered_data.append(d)
                            new_data = filtered_data

                        self._casks = [
                            Package(d, 'cask', self._installed_casks) for d in new_data
                        ]
                        GLib.idle_add(self.emit, 'casks-loaded', self._casks)
                        self._update_progress(0.9)

        # If no cache was available on launch, tap scan and clear spinner now
        if not (has_cache_f or has_cache_c):
            self._update_progress(0.92)
            self._update_status("Scanning local taps...")
            _log.debug('No cache was available on launch, scanning taps and clearing spinner now')
            self._load_tap_packages()
            self._update_progress(0.96)
            GLib.idle_add(self._set_loading_false)

        self._update_progress(0.98)
        self._update_status("Building search provider index...")
        self._build_search_provider_cache()
        self._update_progress(1.0)

        # Check for outdated packages in the background now that all catalog loading is complete
        try:
            settings = Gio.Settings.new('dev.hanthor.Tavern')
            if settings.get_boolean('outdated-check-enabled'):
                self._check_outdated()
        except Exception as e:
            _log.debug('Could not read outdated-check-enabled setting: %s', e)

        _log.debug('_load_all_thread finished')


    def _load_tap_packages(self):
        """
        Enumerate all installed taps directly from the filesystem (instantaneous)
        instead of running `brew tap-info` which takes 10+ seconds.
        Then load formulae and casks from the local tap directories.
        """
        brew_repo_candidates = [
            '/home/linuxbrew/.linuxbrew/Homebrew',
            '/var/home/linuxbrew/.linuxbrew/Homebrew',
            '/opt/homebrew',
            '/usr/local/Homebrew'
        ]
        taps_dir = None
        for cand in brew_repo_candidates:
            d = os.path.join(cand, 'Library', 'Taps')
            if os.path.isdir(d):
                taps_dir = d
                break

        if not taps_dir:
            _log.debug('No taps directory found')
            return

        _log.debug('Scanning taps directory: %s', taps_dir)
        tap_list = []
        try:
            for user in os.listdir(taps_dir):
                user_dir = os.path.join(taps_dir, user)
                if not os.path.isdir(user_dir): continue
                for repo in os.listdir(user_dir):
                    if not repo.startswith('homebrew-'): continue
                    repo_dir = os.path.join(user_dir, repo)
                    tap_name = f'{user}/{repo[9:]}'
                    tap_list.append({'name': tap_name, 'path': repo_dir})
        except Exception as e:
            _log.error('Failed to list taps directory: %s', e)
            return

        import sys
        is_linux = sys.platform.startswith('linux')

        # Core tap is already handled by the API — skip it
        CORE_TAPS = {'homebrew/core', 'homebrew/cask'}

        new_formulae = list(self._formulae)
        new_casks = list(self._casks)
        existing_formula_names = {p.name for p in self._formulae}
        existing_cask_names = {p.name for p in self._casks}
        formulae_changed = False
        casks_changed = False
        tap_packages = {}  # tap_name -> [Package]
        non_core_taps = []

        for tap in tap_list:
            tap_name = tap['name']
            if tap_name in CORE_TAPS:
                continue

            tap_path = tap['path']
            if not tap_path or not os.path.isdir(tap_path):
                continue

            non_core_taps.append(tap)
            tap_pkgs = []

            # ── Formulae ─────────────────────────────────────────────────────
            formula_dir = os.path.join(tap_path, 'Formula')
            if os.path.isdir(formula_dir):
                for fname in os.listdir(formula_dir):
                    if not fname.endswith('.rb'):
                        continue
                    pkg_name = fname[:-3]  # strip .rb
                    if pkg_name in existing_formula_names:
                        continue
                    data = self._minimal_formula_data_from_rb(
                        os.path.join(formula_dir, fname), tap_name, pkg_name
                    )
                    if data:
                        pkg = Package(data, 'formula', self._installed_formulae)
                        new_formulae.append(pkg)
                        existing_formula_names.add(pkg_name)
                        tap_pkgs.append(pkg)
                        formulae_changed = True

            # ── Casks ─────────────────────────────────────────────────────────
            for cask_dir_name in ('Casks', 'cask'):
                cask_dir = os.path.join(tap_path, cask_dir_name)
                if os.path.isdir(cask_dir):
                    for fname in os.listdir(cask_dir):
                        if not fname.endswith('.rb'):
                            continue
                        pkg_name = fname[:-3]
                        if pkg_name in existing_cask_names:
                            continue
                        data = self._minimal_cask_data_from_rb(
                            os.path.join(cask_dir, fname), tap_name, pkg_name
                        )
                        if data:
                            if is_linux and 'macos' in data.get('depends_on', {}):
                                continue
                            pkg = Package(data, 'cask', self._installed_casks)
                            new_casks.append(pkg)
                            existing_cask_names.add(pkg_name)
                            tap_pkgs.append(pkg)
                            casks_changed = True

            if tap_pkgs:
                tap_packages[tap_name] = tap_pkgs

        GLib.idle_add(
            self._apply_tap_scan_results,
            tap_packages,
            non_core_taps,
            new_formulae,
            new_casks,
            formulae_changed,
            casks_changed
        )

    def _apply_tap_scan_results(self, tap_packages, non_core_taps, new_formulae, new_casks, formulae_changed, casks_changed):
        self._tap_packages = tap_packages
        self._tap_list = non_core_taps
        _log.info('Tap scan complete: %d custom taps with packages', len(tap_packages))
        self.emit('taps-loaded', tap_packages)

        # Defer trust status loading so the UI populates immediately
        self._load_tap_trust_status()

        if formulae_changed:
            self._formulae = new_formulae
            _log.info('Tap scan added formulae, total now %d', len(new_formulae))
            self.emit('formulae-loaded', self._formulae)

        if casks_changed:
            self._casks = new_casks
            _log.info('Tap scan added casks, total now %d', len(new_casks))
            self.emit('casks-loaded', self._casks)

    def _minimal_formula_data_from_rb(self, rb_path, tap_name, pkg_name):
        """
        Extract minimal metadata from a .rb formula file using simple regex,
        fast enough to run for tens/hundreds of formulae without noticeable delay.
        Returns a dict compatible with Package._from_api or None on failure.
        """
        import re
        try:
            with open(rb_path, 'r', encoding='utf-8', errors='replace') as f:
                src = f.read(8192)  # Only need the header section
        except Exception:
            return None

        def extract(pattern, default=''):
            m = re.search(pattern, src, re.MULTILINE)
            return m.group(1).strip() if m else default

        desc = extract(r'^\s*desc\s+["\']([^"\']+)["\']')
        homepage = extract(r'^\s*homepage\s+["\']([^"\']+)["\']')
        version = extract(r'^\s*version\s+["\']([^"\']+)["\']') or \
                  extract(r'tag:\s+["\']v?([^"\']+)["\']')
        url = extract(r'^\s*url\s+["\']([^"\']+)["\']')
        license_ = extract(r'^\s*license\s+["\']([^"\']+)["\']')

        return {
            'name': pkg_name,
            'full_name': f'{tap_name}/{pkg_name}',
            'desc': desc,
            'homepage': homepage,
            'versions': {'stable': version},
            'license': license_,
            'urls': {'stable': {'url': url}},
        }

    def _minimal_cask_data_from_rb(self, rb_path, tap_name, pkg_name):
        """Same as _minimal_formula_data_from_rb but for cask .rb files."""
        import re
        try:
            with open(rb_path, 'r', encoding='utf-8', errors='replace') as f:
                src = f.read(8192)
        except Exception:
            return None

        def extract(pattern, default=''):
            m = re.search(pattern, src, re.MULTILINE)
            return m.group(1).strip() if m else default

        version = extract(r'^\s*version\s+["\']([^"\']+)["\']')
        name_extracted = extract(r'^\s*name\s+["\']([^"\']+)["\']')
        desc = extract(r'^\s*desc\s+["\']([^"\']+)["\']')
        homepage = extract(r'^\s*homepage\s+["\']([^"\']+)["\']')
        url = extract(r'^\s*url\s+["\']([^"\']+)["\']')

        # Detect macOS dependencies: only_if builds, requires_zap 'macos' etc.
        depends_on = {}
        if 'macos' in src.lower():
            ma = re.search(r'depends_on\s+macos:', src)
            if ma:
                depends_on['macos'] = True

        name_m = re.search(r'cask\s+["\']([^"\']+)["\']', src)
        token = name_m.group(1) if name_m else pkg_name

        cask_names = [name_extracted] if name_extracted else ([desc] if desc else [token])

        return {
            'token': token,
            'full_token': f'{tap_name}/{token}',
            'name': cask_names,
            'desc': desc,
            'homepage': homepage,
            'version': version,
            'url': url,
            'depends_on': depends_on,
        }



    def _set_loading_false(self):
        self.loading = False

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
        _log.info('Building search provider cache...')
        sp_cache_path = os.path.join(self._cache_dir, 'linux_packages.json')
        packages_data = []

        import sys
        is_linux = sys.platform.startswith('linux')

        for pkg in self._formulae:
            packages_data.append({
                'name': pkg.name,
                'display_name': pkg.display_name,
                'description': pkg.description,
                'pkg_type': pkg.pkg_type,
            })

        for pkg in self._casks:
            # Assume casks already filtered in load if on linux, but double check
            if is_linux:
                # To be completely safe and decoupled, we assume they are already filtered in the self._casks list
                pass
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

    def fetch_popular_taps_async(self, callback):
        """Fetch popular Homebrew taps from GitHub search, cached 24 h.
        callback([{name, gh_user, desc}, ...])"""
        thread = threading.Thread(
            target=self._fetch_popular_taps_thread,
            args=(callback,),
            daemon=True,
        )
        thread.start()

    def _fetch_popular_taps_thread(self, callback):
        cache_key = 'popular_taps'
        cached, is_stale = self._load_cached(cache_key, max_age=86400)  # 24 h
        if cached and not is_stale:
            _log.debug('Popular taps: cache hit (%d taps)', len(cached))
            GLib.idle_add(callback, cached)
            return

        taps = []
        try:
            req = Request(GITHUB_TAP_SEARCH_URL, headers={
                'User-Agent': 'Tavern/0.1',
                'Accept': 'application/vnd.github.v3+json',
            })
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))

            for item in data.get('items', []):
                full_name = item.get('full_name', '')
                parts = full_name.split('/', 1)
                if len(parts) != 2:
                    continue
                owner, repo = parts
                if not repo.startswith('homebrew-'):
                    continue
                tap_name = f'{owner}/{repo[9:]}'  # strip "homebrew-" prefix
                if tap_name in _CORE_TAPS:
                    continue
                desc = (item.get('description') or '').strip()
                taps.append({'name': tap_name, 'gh_user': owner, 'desc': desc})

            _log.info('Fetched %d popular taps from GitHub', len(taps))
            if taps:
                self._save_cache(cache_key, taps)
        except Exception as e:
            _log.error('Failed to fetch popular taps from GitHub: %s', e)

        # Fall back to stale cache if the network request failed
        if not taps and cached:
            _log.info('Using stale popular taps cache (%d taps)', len(cached))
            taps = cached

        GLib.idle_add(callback, taps)

    # ── Tap trust (Homebrew 6.0.0+) ──────────────────────────────────────────

    def check_tap_trust_async(self, tap_name, callback):
        """Check if a tap is trusted. callback(trusted: bool|None).

        Returns None if the trust command is unavailable (pre-6.0.0).
        """
        thread = threading.Thread(
            target=self._check_tap_trust_thread,
            args=(tap_name, callback),
            daemon=True,
        )
        thread.start()

    def _check_tap_trust_thread(self, tap_name, callback):
        """Check trust by parsing `brew trust --json=v1` output."""
        try:
            result = subprocess.run(
                _brew_cmd(['trust', '--json=v1']),
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    trusted = tap_name in data.get('taps', [])
                    _log.debug('check_tap_trust %s: %s', tap_name, trusted)
                    GLib.idle_add(callback, trusted)
                    return
            GLib.idle_add(callback, None)
        except (FileNotFoundError, subprocess.SubprocessError) as e:
            _log.debug('brew trust unavailable (pre-6.0.0?): %s', e)
            GLib.idle_add(callback, None)

    def trust_tap_async(self, tap_name, callback=None):
        """Trust a tap by its remote URL. callback(success, message)."""
        thread = threading.Thread(
            target=self._trust_tap_thread,
            args=(tap_name, callback),
            daemon=True,
        )
        thread.start()

    def _trust_tap_thread(self, tap_name, callback):
        try:
            result = subprocess.run(
                _brew_cmd(['trust', '--tap', tap_name]),
                capture_output=True, text=True, timeout=30,
            )
            success = result.returncode == 0
            msg = (result.stdout + result.stderr).strip()
            _log.info('brew trust --tap %s rc=%d', tap_name, result.returncode)
            if callback:
                GLib.idle_add(callback, success, msg)
        except Exception as e:
            _log.error('trust_tap_async %s failed: %s', tap_name, e)
            if callback:
                GLib.idle_add(callback, False, str(e))

    def untrust_tap_async(self, tap_name, callback=None):
        """Untrust a tap. callback(success, message)."""
        thread = threading.Thread(
            target=self._untrust_tap_thread,
            args=(tap_name, callback),
            daemon=True,
        )
        thread.start()

    def _untrust_tap_thread(self, tap_name, callback):
        try:
            result = subprocess.run(
                _brew_cmd(['untrust', '--tap', tap_name]),
                capture_output=True, text=True, timeout=30,
            )
            success = result.returncode == 0
            msg = (result.stdout + result.stderr).strip()
            _log.info('brew untrust --tap %s rc=%d', tap_name, result.returncode)
            if callback:
                GLib.idle_add(callback, success, msg)
        except Exception as e:
            _log.error('untrust_tap_async %s failed: %s', tap_name, e)
            if callback:
                GLib.idle_add(callback, False, str(e))

    def _load_tap_trust_status(self):
        """Fetch trust status for all installed taps and update _tap_list."""
        thread = threading.Thread(target=self._load_tap_trust_status_thread, daemon=True)
        thread.start()

    def _load_tap_trust_status_thread(self):
        _log.debug('Loading tap trust status for %d taps', len(self._tap_list))
        # Fetch the full trusted-taps list once
        trusted_taps = set()
        try:
            result = subprocess.run(
                _brew_cmd(['trust', '--json=v1']),
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    trusted_taps = set(data.get('taps', []))
        except Exception as e:
            _log.debug('brew trust --json=v1 failed: %s', e)

        for tap in self._tap_list:
            tap_name = tap.get('name', '')
            if not tap_name:
                continue
            # Prefer brew tap-info for installed taps (gives per-tap detail)
            try:
                result = subprocess.run(
                    _brew_cmd(['tap-info', '--json=v1', tap_name]),
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    if isinstance(data, list) and data:
                        tap['trusted'] = data[0].get('trusted')
                        continue
            except Exception:
                pass
            # Fallback: check against the trusted set
            tap['trusted'] = tap_name in trusted_taps if trusted_taps else None
            _log.debug('tap trust %s: %s', tap_name, tap.get('trusted'))

        # Emit taps-loaded again so UI can update trust icons
        GLib.idle_add(self.emit, 'taps-loaded', self._tap_packages)

    def tap_async(self, tap_name, callback=None):
        """Add a Homebrew tap asynchronously. callback(success, message)."""
        thread = threading.Thread(
            target=self._run_tap_operation,
            args=('tap', tap_name, callback),
            daemon=True,
        )
        thread.start()

    def untap_async(self, tap_name, callback=None):
        """Remove a Homebrew tap asynchronously. callback(success, message)."""
        thread = threading.Thread(
            target=self._run_tap_operation,
            args=('untap', tap_name, callback),
            daemon=True,
        )
        thread.start()

    def _run_tap_operation(self, operation, tap_name, callback=None):
        cmd = _brew_cmd([operation, tap_name])
        _log.info('_run_tap_operation: %s %s', operation, tap_name)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            success = result.returncode == 0
            msg = (result.stdout + result.stderr).strip()
            _log.info('brew %s %s  rc=%d', operation, tap_name, result.returncode)
            if success:
                # Reload tap packages so UI stays in sync
                tap_thread = threading.Thread(target=self._load_tap_packages, daemon=True)
                tap_thread.start()
            if callback:
                GLib.idle_add(callback, success, msg)
        except Exception as e:
            _log.error('_run_tap_operation exception: %s %s: %s', operation, tap_name, e)
            if callback:
                GLib.idle_add(callback, False, str(e))

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

    def get_tap_metadata(self, tap_name):
        """Return {remote_url, head_rev, last_commit_date} for an installed tap.

        Reads straight from the tap's git working tree, so this is fast and
        works without network access. Returns empty dict if the tap isn't
        installed or git inspection fails.
        """
        path = None
        for tap in self._tap_list:
            if tap.get('name') == tap_name:
                path = tap.get('path')
                break
        if not path or not os.path.isdir(os.path.join(path, '.git')):
            return {}
        meta = {}
        try:
            r = subprocess.run(
                ['git', '-C', path, 'config', '--get', 'remote.origin.url'],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                meta['remote_url'] = r.stdout.strip()
            r = subprocess.run(
                ['git', '-C', path, 'rev-parse', '--short', 'HEAD'],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                meta['head_rev'] = r.stdout.strip()
            r = subprocess.run(
                ['git', '-C', path, 'log', '-1', '--format=%cI', 'HEAD'],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                meta['last_commit_date'] = r.stdout.strip()
        except Exception as e:
            _log.debug('get_tap_metadata(%s) failed: %s', tap_name, e)
        return meta

    def update_tap_async(self, tap_name, callback=None):
        """Refresh a single tap by `git pull`-ing its working tree."""
        thread = threading.Thread(
            target=self._run_tap_update,
            args=(tap_name, callback),
            daemon=True,
        )
        thread.start()

    def _run_tap_update(self, tap_name, callback=None):
        path = None
        for tap in self._tap_list:
            if tap.get('name') == tap_name:
                path = tap.get('path')
                break
        if not path:
            if callback:
                GLib.idle_add(callback, False, f'Tap {tap_name} not installed')
            return
        try:
            r = subprocess.run(
                ['git', '-C', path, 'pull', '--ff-only'],
                capture_output=True, text=True, timeout=120,
            )
            success = r.returncode == 0
            msg = (r.stdout + r.stderr).strip()
            _log.info('git pull in %s rc=%d', tap_name, r.returncode)
            if success:
                threading.Thread(target=self._load_tap_packages, daemon=True).start()
            if callback:
                GLib.idle_add(callback, success, msg)
        except Exception as e:
            _log.error('update_tap %s failed: %s', tap_name, e)
            if callback:
                GLib.idle_add(callback, False, str(e))

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

    def install_async(self, package, callback=None):
        """Install a package asynchronously."""
        thread = threading.Thread(
            target=self._run_brew_operation,
            args=('install', package, callback),
            daemon=True,
        )
        thread.start()

    def remove_async(self, package, callback=None):
        """Remove a package asynchronously."""
        thread = threading.Thread(
            target=self._run_brew_operation,
            args=('uninstall', package, callback),
            daemon=True,
        )
        thread.start()

    def upgrade_async(self, package, callback=None):
        """Upgrade a package asynchronously."""
        thread = threading.Thread(
            target=self._run_brew_operation,
            args=('upgrade', package, callback),
            daemon=True,
        )
        thread.start()

    def _run_brew_operation(self, operation, package, callback=None):
        args = [operation]
        if package.pkg_type == 'cask':
            args.append('--cask')
        args.append(package.name)
        cmd = _brew_cmd(args)
        _log.info('_run_brew_operation: %s', ' '.join(cmd))

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            output_lines = []
            for line in process.stdout:
                line = line.rstrip('\n')
                output_lines.append(line)
                GLib.idle_add(self.emit, 'operation-output', line)

            process.wait()
            success = process.returncode == 0
            _log.info('brew %s %s  rc=%d  output_lines=%d',
                      operation, package.name, process.returncode, len(output_lines))

            if success:
                GLib.idle_add(self._update_package_installed_state, operation, package)

            msg = '\n'.join(output_lines)
            GLib.idle_add(self.emit, 'operation-complete', success, msg)
            if callback:
                GLib.idle_add(callback, success, msg)

        except Exception as e:
            _log.exception('_run_brew_operation exception: %s %s', operation, package.name)
            GLib.idle_add(self.emit, 'operation-complete', False, str(e))
            if callback:
                GLib.idle_add(callback, False, str(e))

    def _update_package_installed_state(self, operation, package):
        if operation == 'install':
            package.installed = True
            if package.pkg_type == 'formula':
                self._installed_formulae.add(package.name)
            else:
                self._installed_casks.add(package.name)
        elif operation == 'uninstall':
            package.installed = False
            if package.pkg_type == 'formula':
                self._installed_formulae.discard(package.name)
            else:
                self._installed_casks.discard(package.name)

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

    def fetch_icon_async(self, package, callback):
        """Try to fetch an icon for the package."""
        thread = threading.Thread(
            target=self._fetch_icon_thread,
            args=(package, callback),
            daemon=True,
        )
        thread.start()

    def _fetch_icon_thread(self, package, callback):
        """Try multiple icon sources for a package."""
        _log.debug('Fetching icon for %s', package.name)
        icon_path = os.path.join(self._cache_dir, f'icon_{package.name}.png')

        if os.path.exists(icon_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(icon_path, 64, 64, True)
                _log.debug('Loaded cached icon for %s: %dx%d', package.name, pixbuf.get_width(), pixbuf.get_height())
                GLib.idle_add(callback, package, pixbuf)
                return
            except Exception as e:
                _log.debug('Failed to load cached icon for %s: %s', package.name, e)

        icon_urls = []

        # 0. Explicit icon URL (used by flatpak appstream metadata)
        if getattr(package, 'icon_url', None):
            icon_urls.append(package.icon_url)

        is_github_repo = False
        github_owner = None
        
        # Check if homepage implies a GitHub repo
        if package.homepage and 'github.com' in package.homepage:
            import re
            m = re.search(r'github\.com/([^/\s"\']+)/([^/\s"\'#?.]+)', package.homepage)
            if m:
                is_github_repo = True
                github_owner = m.group(1)

        # 1. First image from source repo README (good for projects with logo images)
        # Prioritize images containing keywords like 'logo' or 'brand'
        readme_images = self._fetch_readme_images(package)
        if readme_images:
            logo_images = [img for img in readme_images if any(kw in img.lower() for kw in ('logo', 'brand'))]
            if logo_images:
                icon_urls.extend(logo_images)
            # Add at most one non-logo image as a fallback to avoid excessive slow network requests
            non_logo_images = [img for img in readme_images if img not in logo_images]
            if non_logo_images:
                icon_urls.append(non_logo_images[0])
            
        # 2. GitHub org/user avatar (if it's a GitHub repo)
        if is_github_repo and github_owner:
            icon_urls.append(f'https://github.com/{github_owner}.png?size=128')

        # 3. Scrape the homepage HTML for the best available favicon
        if package.homepage and not is_github_repo:
            domain = package.homepage.replace('https://', '').replace('http://', '').split('/')[0]
            if not domain.endswith('gitlab.com'):
                favicon_url = self._find_favicon_url(package.homepage)
                if favicon_url:
                    icon_urls.append(favicon_url)

        # 4. Google S2 favicon service
        if package.homepage and not is_github_repo:
            domain = package.homepage.replace('https://', '').replace('http://', '').split('/')[0]
            icon_urls.append(f'https://www.google.com/s2/favicons?domain={domain}&sz=128')

        # 5. DuckDuckGo favicon service
        if package.homepage and not is_github_repo:
            domain = package.homepage.replace('https://', '').replace('http://', '').split('/')[0]
            icon_urls.append(f'https://icons.duckduckgo.com/ip3/{domain}.ico')

        for url in icon_urls:
            try:
                req = Request(url, headers={'User-Agent': 'Mozilla/5.0 Tavern/0.1'})
                with urlopen(req, timeout=10) as resp:
                    data = resp.read()
                    if len(data) < 200:  # Filter out 1x1 pixel / blank responses
                        continue

                    # ICO files need conversion — GdkPixbuf may not support them
                    if (url.lower().endswith('.ico')
                            or resp.headers.get('Content-Type', '').startswith('image/x-icon')
                            or resp.headers.get('Content-Type', '').startswith('image/vnd.microsoft.icon')):
                        converted = _ico_to_png(data)
                        if converted:
                            data = converted
                        else:
                            continue  # Unusable ICO — skip to next source

                    loader = GdkPixbuf.PixbufLoader()
                    loader.write(data)
                    loader.close()
                    pixbuf = loader.get_pixbuf()
                    if pixbuf:
                        pixbuf = pixbuf.scale_simple(64, 64, GdkPixbuf.InterpType.BILINEAR)
                        with open(icon_path, 'wb') as f:
                            f.write(data)
                        _log.debug('Downloaded and loaded icon for %s from %s: %dx%d', package.name, url, pixbuf.get_width(), pixbuf.get_height())
                        GLib.idle_add(callback, package, pixbuf)
                        return
            except Exception as e:
                _log.debug('Icon source %s failed for %s: %s', url, package.name, e)
                continue

        _log.debug('No icon found for %s', package.name)
        GLib.idle_add(callback, package, None)

    def _find_favicon_url(self, homepage):
        """
        Fetch the homepage HTML and return the best favicon URL found, or None.

        Priority order:
          1. apple-touch-icon (usually 180×180 PNG — best quality)
          2. icon with PNG/ICO type
          3. shortcut icon
          4. /favicon.png directly
          5. /favicon.ico directly
        """
        import re
        try:
            req = Request(homepage, headers={'User-Agent': 'Mozilla/5.0 Tavern/0.1'})
            with urlopen(req, timeout=8) as resp:
                # Only read the <head> — stop after 32 KB to avoid downloading full pages
                chunk = resp.read(32768).decode('utf-8', errors='replace')
        except Exception:
            return None

        # Parse origin from the URL for resolving relative paths
        from urllib.parse import urljoin

        # Collect all <link> icon tags
        links = re.findall(
            r'<link\s[^>]*rel=["\']([^"\']*)["\'][^>]*href=["\']([^"\']+)["\']'
            r'|<link\s[^>]*href=["\']([^"\']+)["\'][^>]*rel=["\']([^"\']*)["\']',
            chunk, re.IGNORECASE
        )

        candidates = []
        for m in links:
            rel = (m[0] or m[3]).lower()
            href = m[1] or m[2]
            if not href or href.startswith('data:'):
                continue
            url = urljoin(homepage, href)
            if 'apple-touch-icon' in rel:
                candidates.append((0, url))  # Highest priority
            elif 'icon' in rel and href.lower().endswith('.png'):
                candidates.append((1, url))
            elif 'icon' in rel and href.lower().endswith('.ico'):
                candidates.append((2, url))
            elif 'icon' in rel:
                candidates.append((3, url))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            return candidates[0][1]

        # Fall back to root-relative well-known paths
        from urllib.parse import urlparse
        parsed = urlparse(homepage)
        base = f'{parsed.scheme}://{parsed.netloc}'
        for path in ('/favicon.png', '/favicon.ico'):
            url = base + path
            try:
                req = Request(url, headers={'User-Agent': 'Tavern/0.1'})
                with urlopen(req, timeout=5) as resp:
                    if resp.status == 200 and int(resp.headers.get('Content-Length', '9999')) > 200:
                        return url
            except Exception:
                continue

        return None



    def fetch_screenshot_async(self, package, callback):
        """Try to fetch a screenshot for the package."""
        thread = threading.Thread(
            target=self._fetch_screenshot_thread,
            args=(package, callback),
            daemon=True,
        )
        thread.start()

    def fetch_readme_async(self, package, callback):
        """Fetch the README text for a package from its GitHub source repo."""
        thread = threading.Thread(
            target=self._fetch_readme_thread,
            args=(package, callback),
            daemon=True,
        )
        thread.start()

    def _fetch_readme_thread(self, package, callback):
        import re
        GH_RE = re.compile(r'github\.com/([^/\s"\']+)/([^/\s"\'#?.]+)')

        owner, repo = None, None
        for candidate in (getattr(package, 'source_url', ''), package.homepage or ''):
            if not candidate:
                continue
            m = GH_RE.search(candidate)
            if m:
                o, r = m.group(1), m.group(2).rstrip('.git')
                if o.lower() not in ('releases', 'downloads', 'mirrors', 'raw', 'orgs', 'users'):
                    owner, repo = o, r
                    break

        if not owner:
            GLib.idle_add(callback, package, None)
            return

        text = None
        for readme_name in ('README.md', 'readme.md', 'Readme.md', 'README.rst', 'README'):
            raw_url = f'https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{readme_name}'
            try:
                req = Request(raw_url, headers={'User-Agent': 'Tavern/0.1'})
                with urlopen(req, timeout=15) as resp:
                    text = resp.read().decode('utf-8', errors='replace')
                break
            except Exception:
                continue

        GLib.idle_add(callback, package, text)



    def _fetch_screenshot_thread(self, package, callback):
        """Try to fetch a screenshot image for a package."""
        screenshot_path = os.path.join(self._cache_dir, f'screenshot_{package.name}.jpg')

        if os.path.exists(screenshot_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(screenshot_path, 800, 600, True)
                GLib.idle_add(callback, package, pixbuf)
                return
            except Exception:
                pass

        screenshot_urls = []

        # 1. tavern-metadata repo (curated)
        screenshot_urls.append(f'https://raw.githubusercontent.com/hanthor/tavern-metadata/main/screenshots/{package.name}.jpg')

        # 2. README images from source repo (skip the first one — that's the icon)
        readme_images = self._fetch_readme_images(package)
        if readme_images and len(readme_images) > 1:
            # Second image onwards are typically screenshots
            screenshot_urls.extend(readme_images[1:4])

        for url in screenshot_urls:
            try:
                req = Request(url, headers={'User-Agent': 'Tavern/0.1'})
                with urlopen(req, timeout=10) as resp:
                    data = resp.read()
                    if len(data) > 100:
                        with open(screenshot_path, 'wb') as f:
                            f.write(data)
                        loader = GdkPixbuf.PixbufLoader()
                        loader.write(data)
                        loader.close()
                        pixbuf = loader.get_pixbuf()
                        if pixbuf:
                            pixbuf = pixbuf.scale_simple(800, 600, GdkPixbuf.InterpType.BILINEAR)
                            GLib.idle_add(callback, package, pixbuf)
                            return
            except Exception:
                continue

        GLib.idle_add(callback, package, None)

    def _fetch_readme_images(self, package):
        """
        Extract absolute image URLs from the project's GitHub README.

        Returns a list of image URLs (may be empty). Results are cached
        on the Package object to avoid duplicate network hits when both
        the icon and screenshot threads run.
        """
        import re

        # Cache on the package object so icon + screenshot threads share the result
        cached = getattr(package, '_readme_images', None)
        if cached is not None:
            return cached

        package._readme_images = []  # mark as attempted

        GH_RE = re.compile(r'github\.com/([^/\s"\']+)/([^/\s"\'#?.]+)')

        owner, repo = None, None
        # source_url (stable tarball) is the most reliable source — check it first.
        # It's a direct GitHub archive/releases URL for the vast majority of formulae.
        for candidate in (getattr(package, 'source_url', ''), package.homepage or ''):
            if not candidate:
                continue
            m = GH_RE.search(candidate)
            if m:
                o = m.group(1)
                r = m.group(2).rstrip('.git')
                # Skip well-known non-project paths
                if o.lower() in ('releases', 'downloads', 'mirrors', 'raw', 'orgs', 'users'):
                    continue
                owner, repo = o, r
                break

        if not owner:
            return []

        # Try common README filenames in order
        text = None
        for readme_name in ('README.md', 'readme.md', 'Readme.md', 'README.rst'):
            raw_url = f'https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{readme_name}'
            try:
                req = Request(raw_url, headers={'User-Agent': 'Tavern/0.1'})
                with urlopen(req, timeout=10) as resp:
                    text = resp.read().decode('utf-8', errors='replace')
                break
            except Exception:
                continue

        if not text:
            return []

        # Extract markdown image syntax:  ![alt](url)
        # and HTML <img src="url"> tags
        md_images = re.findall(r'!\[.*?\]\(([^)]+)\)', text)
        html_images = re.findall(r"""<img\s[^>]*src=["']([^"']+)["']""", text, re.IGNORECASE)
        all_images = md_images + html_images

        # Resolve relative URLs to absolute GitHub raw URLs
        base_raw = f'https://raw.githubusercontent.com/{owner}/{repo}/HEAD/'

        absolute = []
        for img in all_images:
            img = img.strip()
            if not img:
                continue
            if img.startswith('http://') or img.startswith('https://'):
                url = img
            elif img.startswith('./'):
                url = base_raw + img[2:]
            elif img.startswith('/'):
                url = base_raw + img[1:]
            else:
                url = base_raw + img

            # Skip badge/shield images — not useful as icons or screenshots
            low = url.lower()
            if any(skip in low for skip in ('shields.io', 'badge', 'travis-ci', 'codecov',
                                             'appveyor', 'circleci', 'github/workflow',
                                             'actions/workflows', 'buymeacoffee',
                                             'ko-fi', 'opencollective', 'appimage',
                                             'flathub', 'snapcraft')):
                continue
            # Keep SVG if GdkPixbuf has SVG support; skip otherwise
            if low.endswith('.svg'):
                svg_ok = any(f.get_name() == 'svg' for f in GdkPixbuf.Pixbuf.get_formats())
                if not svg_ok:
                    continue

            absolute.append(url)

        package._readme_images = absolute
        return absolute

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



