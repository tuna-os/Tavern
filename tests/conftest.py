# conftest.py - Shared fixtures for Tavern tests
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import sys
import logging
import pytest

# ── Make ``src/`` importable as the ``tavern`` package ────────────────────────
# The installed Flatpak lays files out as ``<prefix>/tavern/*.py``, but during
# development the sources live under ``src/``.  We add the repo root to
# sys.path and alias ``src`` → ``tavern`` so that ``from tavern.backend import …``
# works in tests exactly the same way as ``from .backend import …`` does inside
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, 'src')

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# Alias the ``src`` directory as the ``tavern`` package
import importlib, types

# Prevent double import or loading from other directories: clear existing tavern modules
for mod_name in list(sys.modules.keys()):
    if mod_name == 'tavern' or mod_name.startswith('tavern.'):
        del sys.modules[mod_name]

spec = importlib.util.spec_from_file_location(
    'tavern', os.path.join(SRC_DIR, '__init__.py'),
    submodule_search_locations=[SRC_DIR],
)
tavern_pkg = importlib.util.module_from_spec(spec)
sys.modules['tavern'] = tavern_pkg
spec.loader.exec_module(tavern_pkg)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_logging_state():
    """Reset ``logging_util`` module state between tests so ``init_logging``
    can be exercised freshly each time."""
    import tavern.logging_util as lu
    original_init = lu._initialized
    original_prof = lu._profiling_enabled
    yield
    lu._initialized = original_init
    lu._profiling_enabled = original_prof
    # Remove any handlers that tests may have added
    root = logging.getLogger('Tavern')
    root.handlers.clear()
    root.setLevel(logging.WARNING)


@pytest.fixture()
def fresh_logging(monkeypatch):
    """Provide a clean logging_util with no prior init, returning the module."""
    import tavern.logging_util as lu
    lu._initialized = False
    lu._profiling_enabled = False
    root = logging.getLogger('Tavern')
    root.handlers.clear()
    root.setLevel(logging.WARNING)
    return lu


# ── GI bootstrap (needed before any GObject import) ─────────────────────────
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('GdkPixbuf', '2.0')

from gi.repository import Adw, Gio
Adw.init()


# ── Headless dialog/settings mocks ──────────────────────────────────────────
# Stub Gio.Settings so missing GSettings schemas don't crash test setup, and
# stub the `.present()` of every Adwaita dialog type so test runs never pop
# real windows on a developer's screen. Tests that need to assert presentation
# can monkeypatch a more specific replacement on top of this.

class _MockSettings:
    _defaults = {
        'window-width': 1024,
        'window-height': 768,
        'window-maximized': False,
    }

    def __init__(self, schema_id):
        self._store = dict(self._defaults)

    def get_int(self, name):
        return self._store.get(name, 0)

    def get_boolean(self, name):
        return self._store.get(name, False)

    def get_string(self, name):
        return self._store.get(name, '')

    def set_int(self, name, value):
        self._store[name] = value

    def set_boolean(self, name, value):
        self._store[name] = value

    def set_string(self, name, value):
        self._store[name] = value


@pytest.fixture(autouse=True)
def _headless_gtk(monkeypatch):
    monkeypatch.setattr(Gio, 'Settings', type('Settings', (), {'new': _MockSettings}))
    for cls_name in ('MessageDialog', 'AlertDialog', 'AboutDialog', 'Dialog'):
        cls = getattr(Adw, cls_name, None)
        if cls is None:
            continue
        # `.present()` signatures vary across dialog types — accept any args.
        monkeypatch.setattr(cls, 'present', lambda self, *a, **kw: None)
    yield

# Load compiled gresource if present so Gtk.Template imports don't fail
compiled_gresource = os.path.join(REPO_ROOT, '.flatpak-build', 'files', 'share', 'tavern', 'tavern.gresource')
if os.path.exists(compiled_gresource):
    from gi.repository import Gio
    try:
        resources = Gio.Resource.load(compiled_gresource)
        Gio.resources_register(resources)
    except Exception as e:
        pass


@pytest.fixture()
def sample_formula_data():
    """Return a dict matching the Homebrew formula JSON API shape."""
    return {
        'name': 'ripgrep',
        'full_name': 'ripgrep',
        'desc': 'Search tool like grep and The Silver Searcher',
        'homepage': 'https://github.com/BurntSushi/ripgrep',
        'versions': {'stable': '14.1.1'},
        'license': 'MIT',
        'urls': {'stable': {'url': 'https://github.com/BurntSushi/ripgrep/archive/14.1.1.tar.gz'}},
    }


@pytest.fixture()
def sample_cask_data():
    """Return a dict matching the Homebrew cask JSON API shape."""
    return {
        'token': 'firefox',
        'full_token': 'firefox',
        'name': ['Mozilla Firefox'],
        'desc': 'Web browser',
        'homepage': 'https://www.mozilla.org/firefox/',
        'version': '130.0',
        'url': 'https://download.mozilla.org/?product=firefox-130.0',
        'depends_on': {},
    }


@pytest.fixture()
def installed_set():
    return {'ripgrep', 'git', 'curl'}


@pytest.fixture()
def large_formula_list(sample_formula_data):
    """Generate a list of 500 fake formula dicts for benchmarking."""
    items = []
    for i in range(500):
        d = dict(sample_formula_data)
        d['name'] = f'pkg-{i:04d}'
        d['full_name'] = f'pkg-{i:04d}'
        d['desc'] = f'Test package number {i}'
        items.append(d)
    return items


@pytest.fixture()
def large_cask_list(sample_cask_data):
    """Generate a list of 500 fake cask dicts for benchmarking."""
    items = []
    for i in range(500):
        d = dict(sample_cask_data)
        d['token'] = f'cask-{i:04d}'
        d['full_token'] = f'cask-{i:04d}'
        d['name'] = [f'Cask App {i}']
        d['desc'] = f'Test cask number {i}'
        items.append(d)
    return items
