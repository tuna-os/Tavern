# test_backend.py - Unit tests for the Homebrew backend
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import textwrap

import pytest

from gi.repository import GLib, GObject
from tavern.backend import Package, BrewBackend, _brew_cmd, _is_flatpak, _find_brew, _ico_to_png


class MockCompletedProcess:
    def __init__(self, returncode, stdout, stderr=''):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ─── Package model ───────────────────────────────────────────────────────────

class TestPackageFormula:
    def test_basic_fields(self, sample_formula_data):
        pkg = Package(sample_formula_data, 'formula')
        assert pkg.name == 'ripgrep'
        assert pkg.full_name == 'ripgrep'
        assert pkg.description == 'Search tool like grep and The Silver Searcher'
        assert pkg.homepage == 'https://github.com/BurntSushi/ripgrep'
        assert pkg.version == '14.1.1'
        assert pkg.pkg_type == 'formula'
        assert pkg.license_ == 'MIT'

    def test_installed_flag_from_set(self, sample_formula_data, installed_set):
        pkg = Package(sample_formula_data, 'formula', installed_set)
        assert pkg.installed is True

    def test_not_installed_when_absent(self, sample_formula_data):
        pkg = Package(sample_formula_data, 'formula', {'wget'})
        assert pkg.installed is False

    def test_empty_data_defaults(self):
        pkg = Package({}, 'formula')
        assert pkg.name == ''
        assert pkg.version == ''
        assert pkg.description == ''

    def test_source_url_extracted(self, sample_formula_data):
        pkg = Package(sample_formula_data, 'formula')
        assert 'ripgrep' in pkg.source_url

    def test_missing_versions_key(self):
        data = {'name': 'test', 'versions': 'not-a-dict'}
        pkg = Package(data, 'formula')
        assert pkg.version == ''


class TestPackageCask:
    def test_basic_fields(self, sample_cask_data):
        pkg = Package(sample_cask_data, 'cask')
        assert pkg.name == 'firefox'
        assert pkg.display_name == 'Mozilla Firefox'
        assert pkg.description == 'Web browser'
        assert pkg.version == '130.0'
        assert pkg.pkg_type == 'cask'

    def test_installed_flag(self, sample_cask_data):
        pkg = Package(sample_cask_data, 'cask', {'firefox'})
        assert pkg.installed is True

    def test_display_name_fallback(self):
        data = {'token': 'myapp', 'name': [], 'desc': '', 'homepage': '', 'version': '1.0'}
        pkg = Package(data, 'cask')
        assert pkg.display_name == 'myapp'

    def test_cask_source_url(self, sample_cask_data):
        pkg = Package(sample_cask_data, 'cask')
        assert 'mozilla' in pkg.source_url


# ─── Package Analytics ───────────────────────────────────────────────────────

class TestPackageAnalytics:
    def test_formula_analytics_parsed(self):
        data = {
            'analytics': {
                'install_on_request': {
                    '30d': {'wget': 27768, 'wget --HEAD': 42},
                    '90d': {'wget': 82993, 'wget --HEAD': 121},
                    '365d': {'wget': 504399, 'wget --HEAD': 926}
                }
            }
        }
        pkg = Package(data, 'formula')
        assert pkg.installs_30d == 27810
        assert pkg.installs_90d == 83114
        assert pkg.installs_365d == 505325

    def test_cask_analytics_fallback(self):
        data = {
            'analytics': {
                'install': {
                    '30d': {'firefox': 100},
                    '90d': {'firefox': 200},
                    '365d': {'firefox': 300}
                }
            }
        }
        pkg = Package(data, 'cask')
        assert pkg.installs_30d == 100
        assert pkg.installs_90d == 200
        assert pkg.installs_365d == 300

    def test_missing_analytics_defaults_zero(self):
        pkg = Package({}, 'formula')
        assert pkg.installs_30d == 0
        assert pkg.installs_90d == 0
        assert pkg.installs_365d == 0


# ─── BrewBackend ─────────────────────────────────────────────────────────────

class TestBrewBackend:
    def test_init_creates_cache_dir(self, tmp_path, monkeypatch):
        cache_dir = str(tmp_path / 'cache')
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        expected = os.path.join(str(tmp_path), 'tavern')
        assert os.path.isdir(expected)

    def test_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        test_data = [{'name': 'a'}, {'name': 'b'}]
        backend._save_cache('test_data', test_data)
        loaded, stale = backend._load_cached('test_data')
        assert loaded == test_data
        # Just saved → not stale (age < 3600)
        assert stale is False

    def test_cache_miss_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        loaded, stale = backend._load_cached('nonexistent')
        assert loaded is None
        assert stale is True

    def test_search_empty_query(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        assert backend.search('') == []

    def test_search_by_name(self, tmp_path, monkeypatch, sample_formula_data):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        backend._formulae = [Package(sample_formula_data, 'formula')]
        results = backend.search('ripgrep')
        assert len(results) == 1
        assert results[0].name == 'ripgrep'

    def test_search_by_description(self, tmp_path, monkeypatch, sample_formula_data):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        backend._formulae = [Package(sample_formula_data, 'formula')]
        results = backend.search('Silver Searcher')
        assert len(results) == 1

    def test_search_filter_formula_only(self, tmp_path, monkeypatch,
                                         sample_formula_data, sample_cask_data):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        backend._formulae = [Package(sample_formula_data, 'formula')]
        backend._casks = [Package(sample_cask_data, 'cask')]
        results = backend.search('e', pkg_type='formula')
        # Only formulae should appear
        for r in results:
            assert r.pkg_type == 'formula'

    def test_search_filter_cask_only(self, tmp_path, monkeypatch,
                                      sample_formula_data, sample_cask_data):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        backend._formulae = [Package(sample_formula_data, 'formula')]
        backend._casks = [Package(sample_cask_data, 'cask')]
        results = backend.search('fire', pkg_type='cask')
        assert all(r.pkg_type == 'cask' for r in results)

    def test_search_sort_order(self, tmp_path, monkeypatch):
        """Exact match → starts-with → contains."""
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        backend._formulae = [
            Package({'name': 'libgit', 'desc': '', 'versions': {}, 'urls': {}}, 'formula'),
            Package({'name': 'git', 'desc': '', 'versions': {}, 'urls': {}}, 'formula'),
            Package({'name': 'gitui', 'desc': '', 'versions': {}, 'urls': {}}, 'formula'),
        ]
        results = backend.search('git')
        names = [r.name for r in results]
        assert names[0] == 'git'       # exact match
        assert names[1] == 'gitui'     # starts-with
        assert names[2] == 'libgit'    # contains

    def test_get_installed_packages(self, tmp_path, monkeypatch, sample_formula_data):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        pkg_installed = Package(sample_formula_data, 'formula', {'ripgrep'})
        pkg_not = Package({'name': 'wget', 'desc': '', 'versions': {}, 'urls': {}}, 'formula')
        backend._formulae = [pkg_installed, pkg_not]
        installed = backend.get_installed_packages()
        assert len(installed) == 1
        assert installed[0].name == 'ripgrep'

    def test_check_outdated_preserves_pkg_type(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()

        outdated_json = {
            'formulae': [
                {
                    'name': 'ripgrep',
                    'installed_versions': ['13.0.0'],
                    'current_version': '14.1.1',
                }
            ],
            'casks': [
                {
                    'name': 'codex',
                    'installed_versions': ['1.0.0'],
                    'current_version': '1.1.0',
                }
            ],
        }

        monkeypatch.setattr(
            'tavern.backend.subprocess.run',
            lambda *args, **kwargs: MockCompletedProcess(0, json.dumps(outdated_json))
        )
        monkeypatch.setattr('tavern.backend.GLib.idle_add', lambda func, *args: func(*args))

        emitted = []
        backend.connect('outdated-changed', lambda _backend, data: emitted.append(data))

        backend._check_outdated()

        assert backend._outdated_formulae['ripgrep']['pkg_type'] == 'formula'
        assert backend._outdated_casks['codex']['pkg_type'] == 'cask'
        assert emitted
        emitted_map = dict(emitted[-1])
        assert emitted_map['codex']['pkg_type'] == 'cask'


# ─── Brewfile parsing ────────────────────────────────────────────────────────

class TestBrewfileParsing:
    def test_parse_brewfile(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        bf = tmp_path / 'test.Brewfile'
        bf.write_text(textwrap.dedent("""\
            tap "homebrew/cask"
            brew "git"
            brew "curl"
            cask "firefox"
        """))
        result = backend.parse_brewfile(str(bf))
        assert result['taps'] == [{'name': 'homebrew/cask', 'trusted': False}]
        assert result['formulae'] == ['git', 'curl']
        assert result['casks'] == ['firefox']

    def test_parse_brewfile_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        bf = tmp_path / 'empty.Brewfile'
        bf.write_text('')
        result = backend.parse_brewfile(str(bf))
        assert result == {'taps': [], 'formulae': [], 'casks': [], 'flatpaks': []}

    def test_parse_brewfile_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        result = backend.parse_brewfile('/nonexistent/path.Brewfile')
        assert result == {'taps': [], 'formulae': [], 'casks': [], 'flatpaks': []}


# ─── _brew_cmd helper ────────────────────────────────────────────────────────

class TestBrewCmd:
    def test_non_flatpak_uses_brew_directly(self, monkeypatch):
        import tavern.backend as bmod
        monkeypatch.setattr(bmod, 'IN_FLATPAK', False)
        monkeypatch.setattr(bmod, 'BREW_BIN', '/usr/local/bin/brew')
        cmd = _brew_cmd(['install', 'git'])
        assert cmd == ['/usr/local/bin/brew', 'install', 'git']

    def test_flatpak_uses_flatpak_spawn(self, monkeypatch):
        import tavern.backend as bmod
        monkeypatch.setattr(bmod, 'IN_FLATPAK', True)
        cmd = _brew_cmd(['install', 'git'])
        assert cmd[0] == 'flatpak-spawn'
        assert '--host' in cmd
        assert 'brew install git' in ' '.join(cmd)


# ─── Minimal .rb parsing ────────────────────────────────────────────────────

class TestMinimalRbParsing:
    def test_formula_rb_extraction(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        rb = tmp_path / 'myformula.rb'
        rb.write_text(textwrap.dedent('''\
            class Myformula < Formula
              desc "A test formula"
              homepage "https://example.com"
              version "1.2.3"
              license "MIT"
              url "https://example.com/myformula-1.2.3.tar.gz"
            end
        '''))
        data = backend._minimal_formula_data_from_rb(str(rb), 'mytap/tap', 'myformula')
        assert data is not None
        assert data['desc'] == 'A test formula'
        assert data['homepage'] == 'https://example.com'
        assert data['versions']['stable'] == '1.2.3'
        assert data['license'] == 'MIT'

    def test_cask_rb_extraction(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        rb = tmp_path / 'myapp.rb'
        rb.write_text(textwrap.dedent('''\
            cask "myapp" do
              name "My Application"
              desc "An awesome app"
              homepage "https://myapp.dev"
              version "2.0.0"
              url "https://myapp.dev/download/myapp-2.0.0.dmg"
            end
        '''))
        data = backend._minimal_cask_data_from_rb(str(rb), 'mytap/tap', 'myapp')
        assert data is not None
        assert data['name'] == ['My Application']
        assert data['desc'] == 'An awesome app'
        assert data['version'] == '2.0.0'

    def test_formula_rb_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        result = backend._minimal_formula_data_from_rb('/no/such/file.rb', 'tap', 'pkg')
        assert result is None


# ─── ICO → PNG conversion ────────────────────────────────────────────────────

class TestIcoToPng:
    """Tests for the pure-Python ICO to PNG converter."""

    def _make_ico(self, entries):
        """Build a minimal ICO file from a list of (w, h, image_bytes) tuples.

        *image_bytes* is either raw PNG or 32-bit BGRA pixel data.
        """
        import struct as s
        count = len(entries)
        header = s.pack('<HHH', 0, 1, count)

        dir_size = count * 16
        data_offset_base = 6 + dir_size

        directory = b''
        image_data = b''
        current_offset = data_offset_base

        for w, h, img_bytes in entries:
            is_png = img_bytes[:8] == b'\x89PNG\r\n\x1a\n'
            if is_png:
                data = img_bytes
            else:
                # Wrap raw pixels in a BITMAPINFOHEADER (40 bytes)
                dib_header = s.pack('<IiiHHIIiiII',
                    40, w, h * 2, 1, 32, 0, len(img_bytes), 0, 0, 0, 0,
                )
                data = dib_header + img_bytes

            entry_w = 0 if w == 256 else w
            entry_h = 0 if h == 256 else h
            directory += s.pack('<BBBBHHII',
                entry_w, entry_h, 0, 0, 1, 32, len(data), current_offset,
            )
            image_data += data
            current_offset += len(data)

        return header + directory + image_data

    def test_returns_none_for_garbage(self):
        assert _ico_to_png(b'not an ico') is None

    def test_returns_none_for_empty(self):
        assert _ico_to_png(b'') is None

    def test_returns_none_for_short(self):
        assert _ico_to_png(b'\x00\x00') is None

    def test_embedded_png_passthrough(self):
        """If the ICO wraps a PNG, we should get that PNG back verbatim."""
        import struct as s, zlib
        def _make_png(w, h):
            def chunk(ctype, data):
                c = ctype + data
                crc = s.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)
                return s.pack('>I', len(data)) + c + crc
            sig = b'\x89PNG\r\n\x1a\n'
            ihdr = chunk(b'IHDR', s.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
            raw = b''
            for _ in range(h):
                raw += b'\x00' + b'\xff\x00\x00\xff' * w
            idat = chunk(b'IDAT', zlib.compress(raw))
            iend = chunk(b'IEND', b'')
            return sig + ihdr + idat + iend

        png_data = _make_png(32, 32)
        ico = self._make_ico([(32, 32, png_data)])
        result = _ico_to_png(ico)
        assert result == png_data

    def test_bgra_dib_conversion(self):
        """A 2x2 BGRA DIB should convert to a valid PNG that GdkPixbuf loads."""
        pixel = b'\x00\x00\xff\xff'   # BGRA = blue=0, green=0, red=255, alpha=255
        pixels = pixel * 4             # 2x2
        ico = self._make_ico([(2, 2, pixels)])
        result = _ico_to_png(ico)
        assert result is not None
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

        from gi.repository import GdkPixbuf
        loader = GdkPixbuf.PixbufLoader()
        loader.write(result)
        loader.close()
        pixbuf = loader.get_pixbuf()
        assert pixbuf is not None
        assert pixbuf.get_width() == 2
        assert pixbuf.get_height() == 2

    def test_picks_largest_entry(self):
        """When multiple entries exist, the largest should be chosen."""
        import struct as s, zlib
        def _make_png(w, h):
            def chunk(ctype, data):
                c = ctype + data
                crc = s.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)
                return s.pack('>I', len(data)) + c + crc
            sig = b'\x89PNG\r\n\x1a\n'
            ihdr = chunk(b'IHDR', s.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
            raw = b''
            for _ in range(h):
                raw += b'\x00' + b'\xff\x00\x00\xff' * w
            idat = chunk(b'IDAT', zlib.compress(raw))
            iend = chunk(b'IEND', b'')
            return sig + ihdr + idat + iend

        small_png = _make_png(16, 16)
        large_png = _make_png(64, 64)
        ico = self._make_ico([
            (16, 16, small_png),
            (64, 64, large_png),
        ])
        result = _ico_to_png(ico)
        assert result == large_png


# ─── BrewBackend Extensions ──────────────────────────────────────────────────

class TestBrewBackendExtensions:
    def test_search_sorting(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        
        # Populate mock packages
        p1 = Package({'name': 'libgit2', 'desc': 'Git library'}, 'formula')
        p2 = Package({'name': 'git', 'desc': 'Version control'}, 'formula')
        p3 = Package({'name': 'git-lfs', 'desc': 'Git Large File Storage'}, 'formula')
        p4 = Package({'token': 'github', 'name': ['GitHub Desktop'], 'desc': 'Desktop client'}, 'cask')
        
        backend._formulae = [p1, p2, p3]
        backend._casks = [p4]
        
        # Search for 'git'
        res = backend.search('git')
        # Expect exact match first ('git'), then starts-with ('git-lfs', 'github'), then contains ('libgit2')
        assert [p.name for p in res] == ['git', 'git-lfs', 'github', 'libgit2']
        
        # Search with type filter
        res_casks = backend.search('git', pkg_type='cask')
        assert len(res_casks) == 1
        assert res_casks[0].name == 'github'

    def test_update_package_installed_state(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        
        pkg_f = Package({'name': 'ripgrep'}, 'formula')
        pkg_c = Package({'token': 'firefox'}, 'cask')
        
        # Install formula
        backend._update_package_installed_state('install', pkg_f)
        assert pkg_f.installed is True
        assert 'ripgrep' in backend._installed_formulae
        
        # Uninstall formula
        backend._update_package_installed_state('uninstall', pkg_f)
        assert pkg_f.installed is False
        assert 'ripgrep' not in backend._installed_formulae

        # Install cask
        backend._update_package_installed_state('install', pkg_c)
        assert pkg_c.installed is True
        assert 'firefox' in backend._installed_casks

    def test_apply_tap_scan_results(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        
        taps = {'custom/tap': []}
        non_core = [{'name': 'custom/tap', 'path': '/path'}]
        formulae = [Package({'name': 'foo'}, 'formula')]
        casks = [Package({'token': 'bar'}, 'cask')]
        
        signals_emitted = []
        backend.connect('taps-loaded', lambda b, t: signals_emitted.append(('taps', t)))
        backend.connect('formulae-loaded', lambda b, f: signals_emitted.append(('formulae', f)))
        backend.connect('casks-loaded', lambda b, c: signals_emitted.append(('casks', c)))
        
        backend._apply_tap_scan_results(taps, non_core, formulae, casks, True, True)
        
        assert backend._tap_packages == taps
        assert backend._tap_list == non_core
        assert backend._formulae == formulae
        assert backend._casks == casks
        assert len(signals_emitted) == 3

    def test_popular_taps_cache_hit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        
        # Pre-seed popular_taps cache
        cached_taps = [{'name': 'homebrew/cask-fonts', 'desc': 'Fonts tap'}]
        backend._save_cache('popular_taps', cached_taps)
        
        callback_called = []
        def cb(taps):
            callback_called.append(taps)
            
        backend.fetch_popular_taps_async(cb)
        
        # Yield to GLib main loop to process callback
        import time
        start = time.time()
        while not callback_called and time.time() - start < 1.0:
            GLib.MainContext.default().iteration(False)
            time.sleep(0.01)
            
        assert len(callback_called) == 1
        assert callback_called[0] == cached_taps

    def test_tap_untap_async(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        
        # Mock subprocess run to simulate successful tap/untap
        class MockCompletedProcess:
            returncode = 0
            stdout = "Successful operation"
            stderr = ""
        
        monkeypatch.setattr("subprocess.run", lambda cmd, **kwargs: MockCompletedProcess())
        monkeypatch.setattr("tavern.backend._brew_cmd", lambda args: ["brew"] + args)
        
        callback_args = []
        def cb(success, message):
            callback_args.append((success, message))
            
        backend.tap_async("custom/tap", cb)
        
        import time
        start = time.time()
        while not callback_args and time.time() - start < 2.0:
            GLib.MainContext.default().iteration(False)
            time.sleep(0.01)
            
        assert len(callback_args) == 1
        assert callback_args[0][0] is True
        assert "Successful operation" in callback_args[0][1]

    def test_get_related_packages_uses_dependencies_first(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        from tavern.backend import Package

        def _mk(name, deps=(), tap=''):
            d = {'name': name, 'desc': 'x', 'homepage': '',
                 'versions': {'stable': '1'}, 'dependencies': list(deps), 'tap': tap}
            return Package(d, 'formula', set())

        target = _mk('rg-tool', deps=['ripgrep', 'fd'])
        rg = _mk('ripgrep')
        fd = _mk('fd')
        other = _mk('unrelated')
        backend._formulae = [target, rg, fd, other]
        backend._casks = []

        related = backend.get_related_packages(target, limit=6)
        names = [p.name for p in related]
        assert names[:2] == ['ripgrep', 'fd']
        assert 'unrelated' not in names

    def test_get_related_packages_falls_back_to_tap_siblings(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        from tavern.backend import Package

        def _mk(name, deps=(), tap=''):
            return Package({'name': name, 'desc': 'x', 'homepage': '',
                            'versions': {'stable': '1'},
                            'dependencies': list(deps), 'tap': tap},
                           'formula', set())

        target = _mk('pkg-a', tap='foo/bar')
        sibling = _mk('pkg-b', tap='foo/bar')
        core = _mk('coreutils', tap='homebrew/core')
        backend._formulae = [target, sibling, core]
        backend._casks = []

        related = backend.get_related_packages(target, limit=6)
        names = [p.name for p in related]
        assert 'pkg-b' in names
        assert 'coreutils' not in names  # same-tap rule skips core

    def test_get_variants_returns_versioned_siblings(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        from tavern.backend import Package

        def _mk(name):
            return Package({'name': name, 'desc': 'x', 'homepage': '',
                            'versions': {'stable': '1'}}, 'formula', set())

        target = _mk('python')
        v310 = _mk('python@3.10')
        v311 = _mk('python@3.11')
        unrelated = _mk('ruby')
        backend._formulae = [target, v310, v311, unrelated]
        backend._casks = []

        variants = backend.get_variants(target)
        names = sorted(p.name for p in variants)
        assert names == ['python@3.10', 'python@3.11']

    def test_update_tap_runs_git_pull_and_reloads(self, tmp_path, monkeypatch):
        """update_tap_async should `git pull` the tap directory and re-scan it."""
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()

        tap_path = tmp_path / 'tap'
        tap_path.mkdir()
        backend._tap_list = [{'name': 'foo/bar', 'path': str(tap_path)}]

        observed = []
        reload_called = []

        def fake_run(cmd, **kwargs):
            observed.append(cmd)
            class R:
                returncode = 0
                stdout = 'Already up to date.'
                stderr = ''
            return R()

        monkeypatch.setattr('subprocess.run', fake_run)
        monkeypatch.setattr(backend, '_load_tap_packages',
                            lambda: reload_called.append(True))

        results = []
        backend.update_tap_async('foo/bar', lambda ok, msg: results.append((ok, msg)))

        import time
        start = time.time()
        while not results and time.time() - start < 2.0:
            GLib.MainContext.default().iteration(False)
            time.sleep(0.01)

        assert results and results[0][0] is True
        assert any(c[:3] == ['git', '-C', str(tap_path)] and 'pull' in c
                   for c in observed)
        # Reload happens on a background thread; wait briefly for it.
        start = time.time()
        while not reload_called and time.time() - start < 1.0:
            time.sleep(0.01)
        assert reload_called

    def test_update_tap_unknown_tap_reports_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        backend._tap_list = []

        results = []
        backend.update_tap_async('nope/missing',
                                 lambda ok, msg: results.append((ok, msg)))

        import time
        start = time.time()
        while not results and time.time() - start < 1.0:
            GLib.MainContext.default().iteration(False)
            time.sleep(0.01)

        assert results == [(False, 'Tap nope/missing not installed')]

    def test_get_tap_metadata_reads_git_state(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        tap_path = tmp_path / 'tap'
        (tap_path / '.git').mkdir(parents=True)
        backend._tap_list = [{'name': 'foo/bar', 'path': str(tap_path)}]

        def fake_run(cmd, **kwargs):
            class R:
                returncode = 0
                stderr = ''
            if 'remote.origin.url' in cmd:
                R.stdout = 'https://github.com/foo/homebrew-bar\n'
            elif 'rev-parse' in cmd:
                R.stdout = 'abc1234\n'
            elif 'log' in cmd:
                R.stdout = '2026-01-15T12:00:00Z\n'
            else:
                R.stdout = ''
            return R()

        monkeypatch.setattr('subprocess.run', fake_run)
        meta = backend.get_tap_metadata('foo/bar')
        assert meta['remote_url'] == 'https://github.com/foo/homebrew-bar'
        assert meta['head_rev'] == 'abc1234'
        assert meta['last_commit_date'].startswith('2026-01-15')

    def test_get_tap_metadata_missing_tap_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        backend._tap_list = []
        assert backend.get_tap_metadata('foo/bar') == {}

    def test_pin_unpin_async(self, tmp_path, monkeypatch):
        """pin_async / unpin_async run brew pin|unpin, reload pinned, fire callback."""
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()

        calls = []

        class _Result:
            def __init__(self, args):
                self.args = args
                self.returncode = 0
                # `brew list --pinned` returns the names, one per line; everything
                # else returns success with no output.
                if args[1:] == ['list', '--pinned']:
                    self.stdout = 'ripgrep\n' if calls_pinned_state['pinned'] else ''
                else:
                    self.stdout = ''
                self.stderr = ''

        calls_pinned_state = {'pinned': False}

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[1:] == ['pin', 'ripgrep']:
                calls_pinned_state['pinned'] = True
            elif cmd[1:] == ['unpin', 'ripgrep']:
                calls_pinned_state['pinned'] = False
            return _Result(cmd)

        monkeypatch.setattr('subprocess.run', fake_run)
        monkeypatch.setattr('tavern.backend._brew_cmd', lambda args: ['brew'] + args)

        from tavern.backend import Package
        pkg = Package({'name': 'ripgrep', 'desc': 'x', 'homepage': '',
                       'versions': {'stable': '1'}}, 'formula', set())

        results = []
        backend.pin_async(pkg, lambda ok, msg: results.append(('pin', ok)))
        backend.unpin_async(pkg, lambda ok, msg: results.append(('unpin', ok)))

        import time
        start = time.time()
        while len(results) < 2 and time.time() - start < 2.0:
            GLib.MainContext.default().iteration(False)
            time.sleep(0.01)

        assert results == [('pin', True), ('unpin', True)]
        assert ['brew', 'pin', 'ripgrep'] in calls
        assert ['brew', 'unpin', 'ripgrep'] in calls

    def test_pin_only_applies_to_formulae_and_casks(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()

        called = []
        monkeypatch.setattr('subprocess.run',
                            lambda *a, **kw: called.append(a) or None)

        from tavern.backend import Package
        flatpak_pkg = Package({'id': 'org.gnome.Gedit', 'name': 'Gedit', 'summary': ''}, 'flatpak', set())

        results = []
        backend.pin_async(flatpak_pkg, lambda ok, msg: results.append((ok, msg)))

        import time
        start = time.time()
        while not results and time.time() - start < 1.0:
            GLib.MainContext.default().iteration(False)
            time.sleep(0.01)

        assert results == [(False, 'Pinning only applies to formulae and casks')]
        assert called == []  # subprocess.run should not have been invoked

    def test_load_pinned_filters_outdated(self, tmp_path, monkeypatch):
        """_load_pinned should strip pinned names from the outdated set."""
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        backend._outdated_formulae = {
            'ripgrep': {'installed': '1', 'latest': '2'},
            'fd': {'installed': '1', 'latest': '2'},
        }
        backend._outdated_casks = {}

        class _R:
            returncode = 0
            stdout = 'ripgrep\n'
            stderr = ''
        monkeypatch.setattr('subprocess.run', lambda *a, **kw: _R())
        monkeypatch.setattr('tavern.backend._brew_cmd', lambda args: ['brew'] + args)

        # Synchronous idle_add so we can assert directly afterward.
        monkeypatch.setattr(GLib, 'idle_add',
                            lambda fn, *a, **kw: (fn(*a, **kw), False)[1])

        backend._load_pinned()

        assert backend.is_pinned('ripgrep')
        assert not backend.is_pinned('fd')
        assert 'ripgrep' not in backend._outdated_formulae
        assert 'fd' in backend._outdated_formulae

    def test_load_all_async_full_flow(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        
        # Mock Gio.Settings
        from gi.repository import Gio
        class MockSettings:
            def __init__(self, schema_id):
                self._store = {'outdated-check-enabled': True}
            def get_boolean(self, name):
                return self._store.get(name, False)
        monkeypatch.setattr(Gio, 'Settings', type('Settings', (), {'new': MockSettings}))

        # Synchronous threading mock
        import threading
        class SynchronousThread:
            def __init__(self, target, args=(), kwargs={}, daemon=True):
                self.target = target
                self.args = args
                self.kwargs = kwargs
            def start(self):
                self.target(*self.args, **self.kwargs)
        monkeypatch.setattr(threading, 'Thread', SynchronousThread)

        # Synchronous GLib idle_add
        def mock_idle_add(callback, *args, **kwargs):
            callback(*args, **kwargs)
            return False
        monkeypatch.setattr(GLib, 'idle_add', mock_idle_add)

        # Mock urlopen to return mock JSON
        class MockResponse:
            def __init__(self, data):
                self._data = data
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass
            def read(self):
                return self._data

        def mock_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, 'full_url') else str(req)
            if 'formula' in url:
                return MockResponse(json.dumps([{'name': 'ripgrep', 'desc': 'rg', 'versions': {'stable': '1.0.0'}}]).encode('utf-8'))
            if 'cask' in url:
                return MockResponse(json.dumps([{'token': 'firefox', 'name': ['Firefox'], 'version': '1.0.0'}]).encode('utf-8'))
            return MockResponse(b'[]')
        
        monkeypatch.setattr('tavern.backend.urlopen', mock_urlopen)

        # Mock subprocess run for brew list and brew tap commands
        def mock_run(cmd, **kwargs):
            cmd_str = ' '.join(cmd) if isinstance(cmd, list) else str(cmd)
            if 'list' in cmd_str:
                return MockCompletedProcess(0, 'ripgrep\nfirefox\n', '')
            if 'tap' in cmd_str:
                return MockCompletedProcess(0, 'custom/tap\n', '')
            if 'outdated' in cmd_str:
                # Mock outdated formula & casks json output
                outdated_json = {
                    'formulae': [{'name': 'ripgrep', 'installed_versions': ['0.9.0'], 'current_version': '1.0.0'}],
                    'casks': [{'name': 'firefox', 'installed_version': '0.9.0', 'current_version': '1.0.0'}]
                }
                return MockCompletedProcess(0, json.dumps(outdated_json), '')
            return MockCompletedProcess(0, '', '')
        monkeypatch.setattr('subprocess.run', mock_run)

        backend = BrewBackend()
        
        # Mock tap scanning to prevent disk-crawling of real Homebrew directory on host
        monkeypatch.setattr(backend, '_load_tap_packages', lambda: None)
        
        signals_received = []
        backend.connect('formulae-loaded', lambda b, f: signals_received.append('formulae'))
        backend.connect('casks-loaded', lambda b, c: signals_received.append('casks'))
        backend.connect('installed-loaded', lambda b, i: signals_received.append('installed'))
        backend.connect('taps-loaded', lambda b, t: signals_received.append('taps'))
        backend.connect('outdated-changed', lambda b, o: signals_received.append('outdated'))

        backend.load_all_async()
        
        assert 'formulae' in signals_received
        assert 'casks' in signals_received
        assert 'installed' in signals_received
        assert len(backend.formulae) > 0
        assert len(backend.casks) > 0

    def test_async_package_operations(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        
        import threading
        class SynchronousThread:
            def __init__(self, target, args=(), kwargs={}, daemon=True):
                self.target = target
                self.args = args
                self.kwargs = kwargs
            def start(self):
                self.target(*self.args, **self.kwargs)
        monkeypatch.setattr(threading, 'Thread', SynchronousThread)

        def mock_idle_add(callback, *args, **kwargs):
            callback(*args, **kwargs)
            return False
        monkeypatch.setattr(GLib, 'idle_add', mock_idle_add)

        # Mock Popen to run synchronously
        class MockPopen:
            def __init__(self, cmd, *args, **kwargs):
                import io
                self.returncode = 0
                self.stdout = io.StringIO("Installing...\nFinished!\n")
            def wait(self):
                return 0

        subprocess_calls = []
        def mock_popen(cmd, *args, **kwargs):
            subprocess_calls.append(' '.join(cmd) if isinstance(cmd, list) else str(cmd))
            return MockPopen(cmd)

        monkeypatch.setattr('subprocess.Popen', mock_popen)

        backend = BrewBackend()
        pkg = Package({'name': 'ripgrep'}, 'formula')

        results = []
        def callback(success, message):
            results.append((success, message))

        # Test install
        backend.install_async(pkg, callback)
        assert len(results) == 1
        assert results[0][0] is True
        assert any('install' in c for c in subprocess_calls)

        # Test remove
        backend.remove_async(pkg, callback)
        assert len(results) == 2
        assert results[1][0] is True
        assert any('uninstall' in c for c in subprocess_calls)

        # Test upgrade
        backend.upgrade_async(pkg, callback)
        assert len(results) == 3
        assert results[2][0] is True
        assert any('upgrade' in c for c in subprocess_calls)

    def test_fetch_icon_async_and_caching(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        
        import threading
        class SynchronousThread:
            def __init__(self, target, args=(), kwargs={}, daemon=True):
                self.target = target
                self.args = args
                self.kwargs = kwargs
            def start(self):
                self.target(*self.args, **self.kwargs)
        monkeypatch.setattr(threading, 'Thread', SynchronousThread)

        def mock_idle_add(callback, *args, **kwargs):
            callback(*args, **kwargs)
            return False
        monkeypatch.setattr(GLib, 'idle_add', mock_idle_add)

        # Mock GdkPixbuf.PixbufLoader
        from gi.repository import GdkPixbuf
        class MockLoader:
            def write(self, data):
                pass
            def close(self):
                pass
            def get_pixbuf(self):
                class MockPixbuf:
                    def get_width(self): return 64
                    def get_height(self): return 64
                    def scale_simple(self, w, h, interp): return self
                return MockPixbuf()

        monkeypatch.setattr(GdkPixbuf, 'PixbufLoader', MockLoader)
        monkeypatch.setattr(GdkPixbuf.Pixbuf, 'new_from_file_at_scale', lambda *args, **kwargs: MockLoader().get_pixbuf())

        # Mock urllib.request.urlopen to return dummy image data
        class MockResponse:
            def __init__(self):
                # Fake small PNG header padded to be > 200 bytes to bypass size filter
                self._data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82' + b'\x00' * 300
                self.headers = {'Content-Type': 'image/png'}
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass
            def read(self, *args, **kwargs):
                return self._data
        monkeypatch.setattr('tavern.backend.urlopen', lambda req, timeout=None: MockResponse())

        backend = BrewBackend()
        pkg = Package({'name': 'ripgrep', 'homepage': 'https://github.com/BurntSushi/ripgrep'}, 'formula')

        fetched_pixbufs = []
        def callback(p, pixbuf):
            fetched_pixbufs.append((p, pixbuf))

        # First load (should perform download & convert, then cache it)
        backend.fetch_icon_async(pkg, callback)
        assert len(fetched_pixbufs) == 1
        assert fetched_pixbufs[0][1] is not None

        # Second load (should hit cache immediately)
        fetched_pixbufs.clear()
        backend.fetch_icon_async(pkg, callback)
        assert len(fetched_pixbufs) == 1
        assert fetched_pixbufs[0][1] is not None

    def test_minimal_rb_parsing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()

        # Create temporary formula .rb file
        formula_rb = tmp_path / 'ripgrep.rb'
        formula_rb.write_text('''
        class Ripgrep < Formula
          desc "Search tool"
          homepage "https://rg.com"
          version "13.0.0"
          license "MIT"
          url "https://rg.com/tar.gz"
        end
        ''')

        # Create temporary cask .rb file
        cask_rb = tmp_path / 'firefox.rb'
        cask_rb.write_text('''
        cask "firefox" do
          version "120.0"
          desc "Web browser"
          homepage "https://firefox.org"
          url "https://firefox.org/dmg"
        end
        ''')

        formula_data = backend._minimal_formula_data_from_rb(str(formula_rb), 'homebrew/core', 'ripgrep')
        assert formula_data['desc'] == 'Search tool'
        assert formula_data['homepage'] == 'https://rg.com'
        assert formula_data['license'] == 'MIT'
        
        cask_data = backend._minimal_cask_data_from_rb(str(cask_rb), 'homebrew/cask', 'firefox')
        assert cask_data['desc'] == 'Web browser'
        assert cask_data['homepage'] == 'https://firefox.org'
        assert cask_data['version'] == '120.0'

    def test_fetch_screenshot_async(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        
        # Synchronous threading mock
        import threading
        class SynchronousThread:
            def __init__(self, target, args=(), kwargs={}, daemon=True):
                self.target = target
                self.args = args
                self.kwargs = kwargs
            def start(self):
                self.target(*self.args, **self.kwargs)
        monkeypatch.setattr(threading, 'Thread', SynchronousThread)

        def mock_idle_add(callback, *args, **kwargs):
            callback(*args, **kwargs)
            return False
        monkeypatch.setattr(GLib, 'idle_add', mock_idle_add)

        # Mock GdkPixbuf.PixbufLoader
        from gi.repository import GdkPixbuf
        class MockLoader:
            def write(self, data):
                pass
            def close(self):
                pass
            def get_pixbuf(self):
                class MockPixbuf:
                    def get_width(self): return 800
                    def get_height(self): return 600
                    def scale_simple(self, w, h, interp): return self
                return MockPixbuf()

        monkeypatch.setattr(GdkPixbuf, 'PixbufLoader', MockLoader)
        monkeypatch.setattr(GdkPixbuf.Pixbuf, 'new_from_file_at_scale', lambda *args, **kwargs: MockLoader().get_pixbuf())

        # Mock urlopen
        class MockResponse:
            def __init__(self):
                self._data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' + b'\x00' * 300
                self.headers = {'Content-Type': 'image/png'}
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass
            def read(self, *args, **kwargs):
                return self._data
        monkeypatch.setattr('tavern.backend.urlopen', lambda req, timeout=None: MockResponse())

        backend = BrewBackend()
        pkg = Package({'name': 'ripgrep', 'homepage': 'https://github.com/BurntSushi/ripgrep'}, 'formula')

        results = []
        backend.fetch_screenshot_async(pkg, lambda p, pixbuf: results.append(pixbuf))
        assert len(results) == 1
        assert results[0] is not None

    def test_fetch_readme_async(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        
        import threading
        class SynchronousThread:
            def __init__(self, target, args=(), kwargs={}, daemon=True):
                self.target = target
                self.args = args
                self.kwargs = kwargs
            def start(self):
                self.target(*self.args, **self.kwargs)
        monkeypatch.setattr(threading, 'Thread', SynchronousThread)

        def mock_idle_add(callback, *args, **kwargs):
            callback(*args, **kwargs)
            return False
        monkeypatch.setattr(GLib, 'idle_add', mock_idle_add)

        # Mock urlopen to return fake readme string
        class MockResponse:
            def __init__(self):
                self._data = b'# My Awesome README\nThis is a great tool.'
                self.headers = {'Content-Type': 'text/plain'}
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass
            def read(self, *args, **kwargs):
                return self._data
        monkeypatch.setattr('tavern.backend.urlopen', lambda req, timeout=None: MockResponse())

        backend = BrewBackend()
        pkg = Package({'name': 'ripgrep', 'homepage': 'https://github.com/BurntSushi/ripgrep'}, 'formula')

        results = []
        backend.fetch_readme_async(pkg, lambda p, text: results.append(text))
        assert len(results) == 1
        assert "My Awesome README" in results[0]

    def test_get_version_history(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        
        backend = BrewBackend()
        pkg = Package({'name': 'ripgrep', 'homepage': 'https://github.com/BurntSushi/ripgrep'}, 'formula')
        pkg.source_url = 'https://github.com/BurntSushi/ripgrep'
        backend._formulae = [pkg]
        
        class MockForge:
            def get_releases(self, owner, repo):
                return [{'version': '1.0.0', 'date': '2026-05-31', 'changelog': 'Initial release'}]
        
        monkeypatch.setattr('tavern.git_forge.get_forge_for_url', lambda url: (MockForge(), 'BurntSushi', 'ripgrep'))
        
        history = backend.get_version_history('ripgrep', 'formula')
        assert len(history) == 1
        assert history[0]['version'] == '1.0.0'

    def test_get_flatpak_info(self, monkeypatch):
        backend = BrewBackend()
        mocked_info = {'id': 'org.gnome.Lollypop', 'name': 'Lollypop'}
        monkeypatch.setattr(backend, '_fetch_json', lambda url: mocked_info)
        assert backend.get_flatpak_info('org.gnome.Lollypop') == mocked_info

    def test_get_version_history_cask(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        pkg = Package({'token': 'visual-studio-code', 'homepage': 'https://github.com/microsoft/vscode', 'version': '1.80.0', 'desc': 'VS Code'}, 'cask')
        pkg.source_url = 'https://github.com/microsoft/vscode'
        backend._casks = [pkg]
        
        class MockForge:
            def get_releases(self, owner, repo):
                return [{'version': '1.80.0', 'date': '2026-05-31', 'changelog': 'New release'}]
        
        monkeypatch.setattr('tavern.git_forge.get_forge_for_url', lambda url: (MockForge(), 'microsoft', 'vscode'))
        
        history = backend.get_version_history('visual-studio-code', 'cask')
        assert len(history) == 1
        assert history[0]['version'] == '1.80.0'

    def test_get_version_history_not_found(self):
        backend = BrewBackend()
        # Test unknown package
        assert backend.get_version_history('nonexistent-pkg', 'formula') == []
        # Test invalid pkg_type
        assert backend.get_version_history('ripgrep', 'invalid_type') == []

    def test_get_version_history_unknown_forge(self, monkeypatch):
        backend = BrewBackend()
        pkg = Package({'name': 'ripgrep'}, 'formula')
        pkg.source_url = 'https://example.com/ripgrep'
        backend._formulae = [pkg]
        
        monkeypatch.setattr('tavern.git_forge.get_forge_for_url', lambda url: (None, None, None))
        assert backend.get_version_history('ripgrep', 'formula') == []

    def test_get_version_history_cache_hit(self, monkeypatch):
        backend = BrewBackend()
        pkg = Package({'name': 'ripgrep'}, 'formula')
        pkg.source_url = 'https://github.com/BurntSushi/ripgrep'
        backend._formulae = [pkg]
        
        class MockForge:
            def get_releases(self, owner, repo):
                assert False, "Should have returned cached data and not called get_releases"
        
        monkeypatch.setattr('tavern.git_forge.get_forge_for_url', lambda url: (MockForge(), 'BurntSushi', 'ripgrep'))
        
        cached_releases = [{'version': '2.0.0', 'date': '2026-05-31', 'changelog': 'Cache hit works'}]
        monkeypatch.setattr(backend, '_load_cached', lambda key: (cached_releases, False))
        
        history = backend.get_version_history('ripgrep', 'formula')
        assert history == cached_releases

    def test_get_version_history_exception(self, monkeypatch):
        backend = BrewBackend()
        pkg = Package({'name': 'ripgrep'}, 'formula')
        pkg.source_url = 'https://github.com/BurntSushi/ripgrep'
        backend._formulae = [pkg]
        
        class FailingForge:
            def get_releases(self, owner, repo):
                raise Exception("Git Forge connection failed")
        
        monkeypatch.setattr('tavern.git_forge.get_forge_for_url', lambda url: (FailingForge(), 'BurntSushi', 'ripgrep'))
        monkeypatch.setattr(backend, '_load_cached', lambda key: (None, True))
        
        assert backend.get_version_history('ripgrep', 'formula') == []


class TestBrewBackendJWS:
    def test_load_from_host_jws_missing(self, tmp_path):
        backend = BrewBackend()
        # Mock paths to non-existent files
        cache_paths = {
            'formula': str(tmp_path / 'nonexistent_formula.jws.json'),
            'cask': str(tmp_path / 'nonexistent_cask.jws.json')
        }
        backend._get_host_brew_cache_paths = lambda: cache_paths
        
        assert backend._load_from_host_jws('formula') is None
        assert backend._load_from_host_jws('cask') is None

    def test_load_from_host_jws_invalid(self, tmp_path):
        backend = BrewBackend()
        # Create a truncated / invalid JSON file
        formula_path = tmp_path / 'formula.jws.json'
        with open(formula_path, 'w') as f:
            f.write('{"payload": "[ { "name": "truncated"')  # missing closing brackets
            
        cache_paths = {
            'formula': str(formula_path),
            'cask': str(tmp_path / 'nonexistent_cask.jws.json')
        }
        backend._get_host_brew_cache_paths = lambda: cache_paths
        
        assert backend._load_from_host_jws('formula') is None

    def test_load_from_host_jws_valid(self, tmp_path):
        backend = BrewBackend()
        # Create a valid JWS file
        formula_path = tmp_path / 'formula.jws.json'
        payload_data = [{'name': 'ripgrep', 'desc': 'fast search'}]
        jws_data = {
            'payload': json.dumps(payload_data),
            'signatures': ['mock_signature']
        }
        with open(formula_path, 'w') as f:
            json.dump(jws_data, f)
            
        cache_paths = {
            'formula': str(formula_path),
            'cask': str(tmp_path / 'nonexistent_cask.jws.json')
        }
        backend._get_host_brew_cache_paths = lambda: cache_paths
        
        result = backend._load_from_host_jws('formula')
        assert result == payload_data

    def test_refresh_cache_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        
        formula_path = tmp_path / 'formula.jws.json'
        cask_path = tmp_path / 'cask.jws.json'
        
        formula_payload = [{'name': 'ripgrep', 'desc': 'fast search', 'versions': {'stable': '1.0.0'}}]
        cask_payload = [{'token': 'firefox', 'name': ['Firefox'], 'version': '1.0.0'}]
        
        with open(formula_path, 'w') as f:
            json.dump({'payload': json.dumps(formula_payload)}, f)
        with open(cask_path, 'w') as f:
            json.dump({'payload': json.dumps(cask_payload)}, f)
            
        cache_paths = {
            'formula': str(formula_path),
            'cask': str(cask_path)
        }
        backend._get_host_brew_cache_paths = lambda: cache_paths
        
        # Prevent any network fetch calls
        backend._fetch_json = lambda url: None
        
        # Run refresh
        backend.refresh_cache_files()
        
        # Verify cached files on disk under Tavern's user cache directory
        tavern_formula_cache = tmp_path / 'tavern' / 'formulae.json'
        tavern_cask_cache = tmp_path / 'tavern' / 'casks.json'
        tavern_sp_cache = tmp_path / 'tavern' / 'linux_packages.json'
        
        assert tavern_formula_cache.exists()
        assert tavern_cask_cache.exists()
        assert tavern_sp_cache.exists()
        
        # Verify internal structures are loaded correctly
        assert len(backend.formulae) == 1
        assert backend.formulae[0].name == 'ripgrep'
        assert len(backend.casks) == 1
        assert backend.casks[0].name == 'firefox'



