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
FLATHUB_APPSTREAM_API = 'https://flathub.org/api/v2/appstream/{}'


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


def _ico_to_png(ico_data):
    """
    Extract the best image from an ICO file and return PNG bytes,
    or None if conversion fails.

    ICO files are containers holding multiple images.  Each entry is
    either an embedded PNG or a raw 32-bit BGRA BMP DIB.  We pick the
    largest one and, if it's already PNG, return it directly; otherwise
    we decode the BGRA pixel data and build a PNG with zlib.
    """
    import zlib

    try:
        if len(ico_data) < 6:
            return None

        # ICO header: reserved(2) + type(2) + count(2)
        _reserved, ico_type, count = struct.unpack_from('<HHH', ico_data, 0)
        if ico_type not in (1, 2) or count == 0 or count > 256:
            return None

        # Parse directory entries (16 bytes each, starting at offset 6)
        best_entry = None
        best_size = 0
        for i in range(count):
            offset = 6 + i * 16
            if offset + 16 > len(ico_data):
                break
            w = ico_data[offset] or 256
            h = ico_data[offset + 1] or 256
            data_size = struct.unpack_from('<I', ico_data, offset + 8)[0]
            data_offset = struct.unpack_from('<I', ico_data, offset + 12)[0]
            pixels = w * h
            if pixels >= best_size and data_offset + data_size <= len(ico_data):
                best_size = pixels
                best_entry = (w, h, data_size, data_offset)

        if not best_entry:
            return None

        w, h, data_size, data_offset = best_entry
        image_data = ico_data[data_offset:data_offset + data_size]

        # Check if the embedded image is already PNG
        if image_data[:8] == b'\x89PNG\r\n\x1a\n':
            return image_data

        # --- BMP DIB → PNG (pure Python) ---
        dib_header_size = struct.unpack_from('<I', image_data, 0)[0]
        bpp = struct.unpack_from('<H', image_data, 14)[0]
        if bpp != 32:
            return None  # Only handle 32-bit BGRA

        # Pixel data starts right after the DIB header
        pixel_start = dib_header_size
        row_bytes = w * 4  # 32-bit = 4 bytes per pixel
        # BMP rows are bottom-up; also there may be an AND mask after the XOR data
        # The XOR (colour) bitmap is w*h*4 bytes
        xor_size = w * h * 4

        if pixel_start + xor_size > len(image_data):
            return None

        # Build RGBA rows (top-to-bottom) for PNG
        raw_rows = bytearray()
        for y in range(h - 1, -1, -1):  # BMP is bottom-up
            row_off = pixel_start + y * row_bytes
            raw_rows.append(0)  # PNG filter byte: None
            for x in range(w):
                px = row_off + x * 4
                b = image_data[px]
                g = image_data[px + 1]
                r = image_data[px + 2]
                a = image_data[px + 3]
                raw_rows.extend((r, g, b, a))

        # Construct minimal PNG file
        def _png_chunk(chunk_type, data):
            chunk = chunk_type + data
            crc = struct.pack('>I', zlib.crc32(chunk) & 0xFFFFFFFF)
            return struct.pack('>I', len(data)) + chunk + crc

        signature = b'\x89PNG\r\n\x1a\n'
        ihdr_data = struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)  # 8-bit RGBA
        ihdr = _png_chunk(b'IHDR', ihdr_data)
        idat = _png_chunk(b'IDAT', zlib.compress(bytes(raw_rows), 9))
        iend = _png_chunk(b'IEND', b'')

        return signature + ihdr + idat + iend

    except Exception:
        return None


def _brew_cmd(args):
    """Build a command list for running brew, using flatpak-spawn if sandboxed."""
    if IN_FLATPAK:
        # Use flatpak-spawn to run brew on the host
        return ['flatpak-spawn', '--host', 'bash', '-c',
                f'eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)" && brew {" ".join(args)}']
    else:
        return [BREW_BIN] + args


class Package(GObject.Object):
    """Represents a Homebrew formula or cask."""

    __gtype_name__ = 'PasarPackage'

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

    # Analytics
    installs_30d = GObject.Property(type=int, default=0)
    installs_90d = GObject.Property(type=int, default=0)
    installs_365d = GObject.Property(type=int, default=0)

    def __init__(self, data=None, pkg_type='formula', installed_set=None, **kwargs):
        super().__init__(**kwargs)
        self._raw_analytics = {}
        if data:
            self._from_api(data, pkg_type, installed_set)

    def _from_api(self, data, pkg_type, installed_set=None):
        self.pkg_type = pkg_type
        if pkg_type == 'formula':
            self.name = data.get('name', '')
            self.full_name = data.get('full_name', self.name)
            self.display_name = self.name
            self.description = data.get('desc', '') or ''
            self.homepage = data.get('homepage', '') or ''
            versions = data.get('versions', {})
            self.version = versions.get('stable', '') or '' if isinstance(versions, dict) else ''
            self.license_ = data.get('license', '') or ''
            # Stable source URL — often a github.com release tarball, very reliable for
            # finding the upstream repo even when homepage is a custom domain.
            urls = data.get('urls', {})
            stable = urls.get('stable', {}) if isinstance(urls, dict) else {}
            self.source_url = stable.get('url', '') or '' if isinstance(stable, dict) else ''
        elif pkg_type == 'cask':
            self.name = data.get('token', '')
            self.full_name = data.get('full_token', self.name)
            names = data.get('name', [])
            self.display_name = names[0] if names else self.name
            self.description = data.get('desc', '') or ''
            self.homepage = data.get('homepage', '') or ''
            self.version = data.get('version', '') or ''
            # Cask download URL — often a github.com release asset
            self.source_url = data.get('url', '') or ''
        else:
            # Flatpak appstream object
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
            self.installed = self.name in installed_set or self.full_name in installed_set

        # Parse analytics if present
        analytics = data.get('analytics', {})
        self._raw_analytics = analytics
        if analytics:
            # Prefer 'install_on_request' for formulae, fall back to 'install' for casks
            metrics = analytics.get('install_on_request', {})
            if not metrics:
                metrics = analytics.get('install', {})
            
            def _sum_period(period_data):
                if not isinstance(period_data, dict):
                    return 0
                return sum(val for val in period_data.values() if isinstance(val, int))
            
            self.installs_30d = _sum_period(metrics.get('30d', {}))
            self.installs_90d = _sum_period(metrics.get('90d', {}))
            self.installs_365d = _sum_period(metrics.get('365d', {}))



class BrewBackend(GObject.Object):
    """Backend that communicates with both the Homebrew JSON API and local brew CLI."""

    __gtype_name__ = 'PasarBrewBackend'

    loading = GObject.Property(type=bool, default=False)

    __gsignals__ = {
        'formulae-loaded': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'casks-loaded': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'installed-loaded': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'outdated-changed': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'operation-complete': (GObject.SignalFlags.RUN_LAST, None, (bool, str)),
        'operation-output': (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._formulae = []
        self._casks = []
        self._installed_formulae = set()
        self._installed_casks = set()
        self._outdated_formulae = {}  # {name: {installed, latest}}
        self._outdated_casks = {}  # {name: {installed, latest}}
        self._outdated_lock = threading.Lock()
        self._cache_dir = os.path.join(GLib.get_user_cache_dir(), 'pasar')
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
                            m = re.match(r'tap\s+["\']([^"\']+)["\']', line)
                            if m: taps.append(m.group(1))
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

    def _fetch_json(self, url):
        """Fetch JSON from URL with a timeout and detailed error reporting."""
        _log.debug('Fetching JSON: %s', url)
        req = Request(url, headers={'User-Agent': 'Pasar/0.1'})
        try:
            with log_timing(f'fetch_json {url}', 'backend'):
                with urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
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

    def _cache_path(self, name):
        return os.path.join(self._cache_dir, f'{name}.json')

    def _load_cached(self, name):
        path = self._cache_path(name)
        if os.path.exists(path):
            try:
                age = GLib.get_real_time() / 1e6 - os.path.getmtime(path)
                stale = age > 3600
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
                
                with self._outdated_lock:
                    self._outdated_formulae = {}
                    for f in formulae:
                        name = f.get('name', '')
                        if name:
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
        # Core API fetch thread
        thread = threading.Thread(target=self._load_all_thread, daemon=True)
        thread.start()
        # Tap packages are all on disk — start loading immediately in parallel
        tap_thread = threading.Thread(target=self._load_tap_packages, daemon=True)
        tap_thread.start()

    def _load_all_thread(self):
        _log.debug('_load_all_thread started')
        # Get installed packages first
        with log_timing('get installed packages', 'backend'):
            installed_f, installed_c = self._get_installed()
        self._installed_formulae = installed_f
        self._installed_casks = installed_c

        # Emit installed signal
        installed_pkgs = []
        GLib.idle_add(self.emit, 'installed-loaded', installed_pkgs)

        # Check for outdated packages if setting is enabled
        try:
            settings = Gio.Settings.new('dev.hanthor.Pasar')
            if settings.get_boolean('outdated-check-enabled'):
                self._check_outdated()
        except Exception as e:
            _log.debug('Could not read outdated-check-enabled setting: %s', e)

        # Load formulae from cache first
        data, is_stale = self._load_cached('formulae')
        if data:
            with log_timing('parse formulae from cache', 'backend'):
                self._formulae = [
                    Package(d, 'formula', self._installed_formulae) for d in data
                ]
            _log.info('Loaded %d formulae from cache (stale=%s)', len(self._formulae), is_stale)
            GLib.idle_add(self.emit, 'formulae-loaded', self._formulae)

        # Fetch in background if missing or stale
        if not data or is_stale:
            new_data = self._fetch_json(FORMULA_API)
            if new_data:
                self._save_cache('formulae', new_data)
                with log_timing('parse formulae from API', 'backend'):
                    self._formulae = [
                        Package(d, 'formula', self._installed_formulae) for d in new_data
                    ]
                _log.info('Loaded %d formulae from API', len(self._formulae))
                GLib.idle_add(self.emit, 'formulae-loaded', self._formulae)

        # Load casks from cache first
        data, is_stale = self._load_cached('casks')
        if data:
            import sys
            is_linux = sys.platform.startswith('linux')
            
            if is_linux:
                filtered_data = []
                for d in data:
                    depends_on = d.get('depends_on', {})
                    if 'macos' not in depends_on:
                        filtered_data.append(d)
                data = filtered_data

            self._casks = [
                Package(d, 'cask', self._installed_casks) for d in data
            ]
            GLib.idle_add(self.emit, 'casks-loaded', self._casks)

        # Fetch in background if missing or stale
        if not data or is_stale:
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

        GLib.idle_add(self._set_loading_false)
        _log.debug('_load_all_thread finished')
        # build the search provider cache
        self._build_search_provider_cache()


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

        for tap in tap_list:
            tap_name = tap['name']
            if tap_name in CORE_TAPS:
                continue

            tap_path = tap['path']
            if not tap_path or not os.path.isdir(tap_path):
                continue


            # ── Formulae ─────────────────────────────────────────────────────
            formula_dir = os.path.join(tap_path, 'Formula')
            if os.path.isdir(formula_dir):
                for fname in os.listdir(formula_dir):
                    if not fname.endswith('.rb'):
                        continue
                    pkg_name = fname[:-3]  # strip .rb
                    if pkg_name in existing_formula_names:
                        continue
                    # Build a minimal data dict from what we can extract cheaply
                    # (avoid running `brew info` per-formula — too slow at scale)
                    data = self._minimal_formula_data_from_rb(
                        os.path.join(formula_dir, fname), tap_name, pkg_name
                    )
                    if data:
                        pkg = Package(data, 'formula', self._installed_formulae)
                        new_formulae.append(pkg)
                        existing_formula_names.add(pkg_name)
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
                            # Filter macOS-only casks on Linux
                            if is_linux and 'macos' in data.get('depends_on', {}):
                                continue
                            pkg = Package(data, 'cask', self._installed_casks)
                            new_casks.append(pkg)
                            existing_cask_names.add(pkg_name)
                            casks_changed = True

        if formulae_changed:
            self._formulae = new_formulae
            _log.info('Tap scan added %d formulae', len(new_formulae) - len(existing_formula_names) + (len(new_formulae) - len(self._formulae) if False else 0))
            GLib.idle_add(self.emit, 'formulae-loaded', self._formulae)

        if casks_changed:
            self._casks = new_casks
            _log.info('Tap scan added casks, total now %d', len(new_casks))
            GLib.idle_add(self.emit, 'casks-loaded', self._casks)

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

            msg = '\n'.join(output_lines)
            GLib.idle_add(self.emit, 'operation-complete', success, msg)
            if callback:
                GLib.idle_add(callback, success, msg)

        except Exception as e:
            _log.exception('_run_brew_operation exception: %s %s', operation, package.name)
            GLib.idle_add(self.emit, 'operation-complete', False, str(e))
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
        readme_images = self._fetch_readme_images(package)
        if readme_images:
            icon_urls.append(readme_images[0])
            
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
                req = Request(url, headers={'User-Agent': 'Mozilla/5.0 Pasar/0.1'})
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
            req = Request(homepage, headers={'User-Agent': 'Mozilla/5.0 Pasar/0.1'})
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
                req = Request(url, headers={'User-Agent': 'Pasar/0.1'})
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
                req = Request(raw_url, headers={'User-Agent': 'Pasar/0.1'})
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

        # 1. pasar-metadata repo (curated)
        screenshot_urls.append(f'https://raw.githubusercontent.com/hanthor/pasar-metadata/main/screenshots/{package.name}.jpg')

        # 2. README images from source repo (skip the first one — that's the icon)
        readme_images = self._fetch_readme_images(package)
        if readme_images and len(readme_images) > 1:
            # Second image onwards are typically screenshots
            screenshot_urls.extend(readme_images[1:4])

        for url in screenshot_urls:
            try:
                req = Request(url, headers={'User-Agent': 'Pasar/0.1'})
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
                req = Request(raw_url, headers={'User-Agent': 'Pasar/0.1'})
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
                                             'ko-fi', 'opencollective')):
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

                # Parse formulae
                for item in data.get('formulae', []):
                    name = item.get('name', '')
                    if name:
                        outdated_f[name] = {
                            'installed': item.get('installed_versions', [''])[0] if item.get('installed_versions') else '',
                            'latest': item.get('current_version', ''),
                        }

                # Parse casks
                for item in data.get('casks', []):
                    name = item.get('name', '')
                    if name:
                        outdated_c[name] = {
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

    def get_version_history(self, name, pkg_type):
        """
        Fetch version history and GitHub changelogs for a package.
        Returns list of {version, date, changelog} dicts sorted newest-first.
        """
        from datetime import datetime, timedelta
        
        if pkg_type == 'formula':
            package_list = self._formulae
        elif pkg_type == 'cask':
            package_list = self._casks
        else:
            return []

        # Find the package
        pkg = None
        for p in package_list:
            if p.name == name or p.full_name == name:
                pkg = p
                break

        if not pkg:
            _log.warning('Package not found: %s (%s)', name, pkg_type)
            return []

        # Extract GitHub repo from source_url
        source_url = pkg.source_url or ''
        github_match = None
        if 'github.com' in source_url:
            import re
            m = re.search(r'github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/|$)', source_url)
            if m:
                github_match = (m.group(1), m.group(2))

        if not github_match:
            _log.debug('No GitHub repo found for %s', name)
            return []

        owner, repo = github_match
        cache_dir = os.path.join(self._cache_dir, 'version-history')
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, f'{name}-{pkg_type}.json')

        # Check cache age
        use_cache = False
        if os.path.exists(cache_file):
            age = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(cache_file))).total_seconds()
            if age < 86400:  # 24 hours
                use_cache = True
                _log.debug('Using cached version history for %s (age=%.0fs)', name, age)

        if use_cache:
            try:
                with open(cache_file) as f:
                    return json.load(f)
            except Exception as e:
                _log.warning('Failed to load version history cache for %s: %s', name, e)

        # Fetch from GitHub API
        _log.debug('Fetching release history from GitHub: %s/%s', owner, repo)
        versions = []
        try:
            url = f'https://api.github.com/repos/{owner}/{repo}/releases?per_page=50'
            req = Request(url, headers={
                'User-Agent': 'Pasar/0.1',
                'Accept': 'application/vnd.github.v3+json',
            })
            with urlopen(req, timeout=10) as resp:
                releases = json.loads(resp.read().decode('utf-8'))

            for release in releases:
                if not isinstance(release, dict):
                    continue

                version = release.get('tag_name', '').lstrip('v')
                published = release.get('published_at', '')
                body = release.get('body', '') or ''

                if version:
                    versions.append({
                        'version': version,
                        'date': published[:10] if published else 'unknown',
                        'changelog': body.strip() or '(No description)',
                    })

            # Sort newest first
            versions.sort(key=lambda x: x['date'], reverse=True)

            # Cache the results
            try:
                with open(cache_file, 'w') as f:
                    json.dump(versions, f)
                _log.debug('Cached version history for %s: %d versions', name, len(versions))
            except Exception as e:
                _log.warning('Failed to cache version history for %s: %s', name, e)

            return versions

        except Exception as e:
            _log.error('Failed to fetch GitHub releases for %s/%s: %s', owner, repo, e)
            return []

