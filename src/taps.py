# taps.py - Tap scanning, trust, and tap operations (mixin for BrewBackend)
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import subprocess
import sys
import threading
from urllib.request import Request

from gi.repository import GLib

from .logging_util import get_logger, log_timing
from .package import Package

_log = get_logger('taps')

GITHUB_TAP_SEARCH_URL = (
    'https://api.github.com/search/repositories'
    '?q=homebrew-+in:name&sort=stars&order=desc&per_page=80'
)

# Core taps served by the public API — never need to appear in the "Add" list
_CORE_TAPS = frozenset({'homebrew/core', 'homebrew/cask'})



def _brew_cmd(args):
    """Resolve through the backend module so test monkeypatches of
    tavern.backend._brew_cmd keep working for tap operations."""
    from . import backend
    return backend._brew_cmd(args)


def urlopen(req, timeout=None):
    """Resolve through the backend module (see _brew_cmd)."""
    from . import backend
    return backend.urlopen(req, timeout=timeout)


class TapsMixin:
    """Tap-related behavior mixed into BrewBackend."""

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

