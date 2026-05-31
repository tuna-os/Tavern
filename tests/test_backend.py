# test_backend.py - Unit tests for the Homebrew backend
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import textwrap

import pytest

from gi.repository import GLib, GObject
from tavern.backend import Package, BrewBackend, _brew_cmd, _is_flatpak, _find_brew, _ico_to_png


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
        assert result['taps'] == ['homebrew/cask']
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

