# backend_state.py - Installed/outdated/pinned state (mixin for BrewBackend)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Extracted from backend.py (tuna-os/Tavern#81): installed formula/cask
# discovery, outdated checks, and pinning. Follows the same mixin composition
# already used for TapsMixin/MediaMixin/CacheMixin — this class expects the
# usual BrewBackend instance state (`self._outdated_formulae`,
# `self._outdated_casks`, `self._pinned`, and the lock attributes) to exist on
# whatever it's mixed into, exactly as the original methods did as part of
# BrewBackend. `_brew_cmd` resolves through the backend module so test
# monkeypatches of tavern.backend._brew_cmd keep working (see taps.py).

import json
import subprocess
import threading

from gi.repository import GLib

from .logging_util import get_logger, log_timing

_log = get_logger('backend_state')


def _brew_cmd(args):
    """Resolve through the backend module (see taps.py)."""
    from . import backend
    return backend._brew_cmd(args)


class StateMixin:
    """Installed/outdated/pinned package state mixed into BrewBackend."""

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

    def _apply_installed_changes(self, changes):
        for pkg, inst in changes:
            pkg.installed = inst
        self.emit('installed-loaded', [])

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
