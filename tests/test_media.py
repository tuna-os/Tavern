# test_media.py - Unit tests for icon/screenshot/README fetching (src/media.py)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# MediaMixin previously had no direct tests.  These cover the README image
# extraction (markdown + HTML, relative URL resolution, badge filtering, SVG
# gating), the favicon finder's priority order, the icon source cascade, the
# screenshot cache/download path, and the inflight-coalescing in
# fetch_icon_async — all with mocked network responses and no display server.

import json
import os
import threading
from types import SimpleNamespace
import pytest

import tavern.media as media_mod
from tavern.media import MediaMixin
from tavern.package import Package
from gi.repository import GObject, GdkPixbuf


class _FakeResp:
    def __init__(self, data=b'', status=200, headers=None):
        self._data = data
        self.status = status
        self.headers = {'Content-Length': str(len(data)), **(headers or {})}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        if n == -1:
            return self._data
        return self._data[:n]


class _RecorderExecutor:
    def __init__(self):
        self.submitted = []

    def submit(self, fn, *args, **kwargs):
        self.submitted.append((fn, args, kwargs))


class _MediaHost(MediaMixin):
    """Minimal host that mixes in MediaMixin the way BrewBackend does."""

    def __init__(self, cache_dir):
        self._cache_dir = cache_dir
        self._icon_lock = threading.Lock()
        self._icon_inflight = {}
        self._icon_executor = _RecorderExecutor()


@pytest.fixture
def host(tmp_path):
    return _MediaHost(str(tmp_path))


@pytest.fixture
def idle(monkeypatch):
    calls = []
    monkeypatch.setattr(media_mod.GLib, 'idle_add', lambda fn, *a, **k: calls.append((fn, a, k)) or 1)
    return calls


def _pkg(**kw):
    base = {'name': 'ripgrep', 'homepage': '', 'source_url': '', 'icon_url': ''}
    base.update(kw)
    return SimpleNamespace(**base)


def _urlopen(handlers):
    """Return a urlopen replacement dispatching on URL substrings."""
    def urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, 'full_url') else str(req)
        for pattern, resp in handlers:
            if pattern in url:
                return resp
        raise OSError(f'unhandled url: {url}')
    return urlopen


@pytest.fixture
def fake_github_readme(monkeypatch):
    """Serve a README with a couple of markdown + html images."""
    readme = (
        '# ripgrep\n\n'
        '![logo](https://raw.githubusercontent.com/BurntSushi/ripgrep/master/logo.png)\n'
        '![screenshot](./screenshot.png)\n'
        '![relative](/docs/img.png)\n'
        '![badge](https://img.shields.io/badge/build-passing-green.svg)\n'
        '<img src="https://example.com/html-img.png" alt="x">\n'
        '![travis](https://travis-ci.org/BurntSushi/ripgrep.svg?branch=master)\n'
        '![svg](https://raw.githubusercontent.com/BurntSushi/ripgrep/master/icon.svg)\n'
    )
    monkeypatch.setattr(media_mod, 'urlopen',
                        _urlopen([('raw.githubusercontent.com', _FakeResp(readme.encode()))]))
    return readme


# ─── README image extraction ─────────────────────────────────────────────────

@pytest.fixture
def no_svg_loader(monkeypatch):
    """Pin gdk-pixbuf's SVG support OFF.

    _fetch_readme_images consults GdkPixbuf.Pixbuf.get_formats() to decide
    whether to keep .svg URLs, so any assertion about SVG filtering otherwise
    depends on whether librsvg happens to be installed on the machine running
    the tests — green on a bare container, red on most desktops and on GitHub's
    ubuntu runner images, which do ship the SVG loader.
    """
    monkeypatch.setattr(
        GdkPixbuf.Pixbuf, 'get_formats',
        staticmethod(lambda: [SimpleNamespace(get_name=lambda: 'png'),
                              SimpleNamespace(get_name=lambda: 'jpeg')]))


@pytest.fixture
def stub_pixbuf_loader(monkeypatch):
    """Make the download paths decode this module's stand-in payloads.

    After fetching, media.py decodes the bytes with a real
    GdkPixbuf.PixbufLoader (icons at :135, screenshots at :303) and then calls
    scale_simple() on the result. The payloads here are byte-count stand-ins —
    a PNG magic number followed by filler — so the real loader raises, the
    surrounding try/except swallows it, and the fetch returns None before the
    assertion under test is ever reached.

    Yields a genuine 4x4 pixbuf rather than a bare Pixbuf() so that the
    scale_simple()/get_width() calls downstream behave like the real thing.
    """
    real = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 4, 4)

    class _FakeLoader:
        def write(self, data):
            return True

        def close(self):
            return True

        def get_pixbuf(self):
            return real

    monkeypatch.setattr(GdkPixbuf, 'PixbufLoader', _FakeLoader)
    return real


class TestFetchReadmeImages:
    def test_extracts_and_resolves_images(self, host, fake_github_readme, no_svg_loader):
        pkg = _pkg(homepage='https://github.com/BurntSushi/ripgrep',
                   source_url='https://github.com/BurntSushi/ripgrep/archive/1.0.tar.gz')
        imgs = host._fetch_readme_images(pkg)
        base = 'https://raw.githubusercontent.com/BurntSushi/ripgrep/HEAD/'
        assert imgs == [
            'https://raw.githubusercontent.com/BurntSushi/ripgrep/master/logo.png',
            base + 'screenshot.png',
            base + 'docs/img.png',
            'https://example.com/html-img.png',
        ]

    def test_badges_and_travis_filtered(self, host, fake_github_readme):
        pkg = _pkg(homepage='https://github.com/BurntSushi/ripgrep')
        imgs = host._fetch_readme_images(pkg)
        assert not any('shields.io' in u or 'travis' in u for u in imgs)

    def test_svg_skipped_without_svg_support(self, host, fake_github_readme, no_svg_loader):
        pkg = _pkg(homepage='https://github.com/BurntSushi/ripgrep')
        imgs = host._fetch_readme_images(pkg)
        assert not any(u.endswith('.svg') for u in imgs)

    def test_svg_kept_when_supported(self, host, fake_github_readme, monkeypatch):
        monkeypatch.setattr(GdkPixbuf.Pixbuf, 'get_formats',
                            staticmethod(lambda: [SimpleNamespace(get_name=lambda: 'svg')]))
        pkg = _pkg(homepage='https://github.com/BurntSushi/ripgrep')
        imgs = host._fetch_readme_images(pkg)
        assert any(u.endswith('.svg') for u in imgs)

    def test_cached_on_package_object(self, host, fake_github_readme):
        pkg = _pkg(homepage='https://github.com/BurntSushi/ripgrep')
        first = host._fetch_readme_images(pkg)
        second = host._fetch_readme_images(pkg)
        assert first == second
        assert pkg._readme_images is second  # cached reference, no second fetch

    def test_no_github_url_returns_empty(self, host, monkeypatch):
        calls = []
        monkeypatch.setattr(media_mod, 'urlopen', lambda *a, **k: calls.append(1) or _FakeResp(b''))
        pkg = _pkg(homepage='https://example.com/not-github')
        assert host._fetch_readme_images(pkg) == []
        assert calls == []

    def test_readme_fetch_failure_returns_empty(self, host, monkeypatch):
        def boom(*a, **k):
            raise OSError('network down')

        monkeypatch.setattr(media_mod, 'urlopen', boom)
        pkg = _pkg(homepage='https://github.com/user/repo')
        assert host._fetch_readme_images(pkg) == []
        assert pkg._readme_images == []  # marked attempted

    def test_skips_well_known_non_project_paths(self, host, fake_github_readme):
        pkg = _pkg(homepage='https://github.com/releases/tag/1.0')
        assert host._fetch_readme_images(pkg) == []

    def test_markdown_img_without_alt(self, host, monkeypatch):
        readme = '![x](https://example.com/a.png)\n![alt text with spaces](https://example.com/b.png)\n'
        monkeypatch.setattr(media_mod, 'urlopen',
                            _urlopen([('raw.githubusercontent.com', _FakeResp(readme.encode()))]))
        pkg = _pkg(homepage='https://github.com/o/r')
        imgs = host._fetch_readme_images(pkg)
        assert imgs == ['https://example.com/a.png', 'https://example.com/b.png']


# ─── favicon discovery ────────────────────────────────────────────────────────

class TestFindFaviconUrl:
    def test_apple_touch_icon_highest_priority(self, host, monkeypatch):
        html = b'''<html><head>
        <link rel="icon" href="/favicon.ico">
        <link rel="apple-touch-icon" href="https://cdn.example.com/apple-180.png">
        <link rel="icon" type="image/png" href="/favicon.png">
        </head></html>'''
        monkeypatch.setattr(media_mod, 'urlopen', _urlopen([('example.com', _FakeResp(html))]))
        assert host._find_favicon_url('https://example.com') == 'https://cdn.example.com/apple-180.png'

    def test_png_preferred_over_ico(self, host, monkeypatch):
        html = b'<html><head><link rel="icon" href="/favicon.ico"><link rel="icon" type="image/png" href="/favicon.png"></head></html>'
        monkeypatch.setattr(media_mod, 'urlopen', _urlopen([('example.com', _FakeResp(html))]))
        assert host._find_favicon_url('https://example.com') == 'https://example.com/favicon.png'

    def test_relative_href_resolved_against_origin(self, host, monkeypatch):
        html = b'<html><head><link rel="icon" type="image/png" href="/static/icon.png"></head></html>'
        monkeypatch.setattr(media_mod, 'urlopen', _urlopen([('example.com', _FakeResp(html))]))
        assert host._find_favicon_url('https://example.com/blog/index.html') == 'https://example.com/static/icon.png'

    def test_data_uri_href_skipped(self, host, monkeypatch):
        html = b'<html><head><link rel="icon" href="data:image/png;base64,AAAA"></head></html>'
        monkeypatch.setattr(media_mod, 'urlopen', _urlopen([('example.com', _FakeResp(html))]))
        assert host._find_favicon_url('https://example.com') is None

    def test_fallback_favicon_png(self, host, monkeypatch):
        html = b'<html><head></head></html>'
        monkeypatch.setattr(media_mod, 'urlopen', _urlopen([
            ('example.com/favicon.png', _FakeResp(b'x' * 300)),
            ('example.com', _FakeResp(html)),
        ]))
        assert host._find_favicon_url('https://example.com') == 'https://example.com/favicon.png'

    def test_fallback_prefers_ico_after_png_missing(self, host, monkeypatch):
        html = b'<html><head></head></html>'

        def urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, 'full_url') else str(req)
            if 'favicon.png' in url:
                raise OSError('404')
            if 'favicon.ico' in url:
                return _FakeResp(b'y' * 300)
            return _FakeResp(html)

        monkeypatch.setattr(media_mod, 'urlopen', urlopen)
        assert host._find_favicon_url('https://example.com') == 'https://example.com/favicon.ico'

    def test_small_fallback_file_rejected(self, host, monkeypatch):
        html = b'<html><head></head></html>'
        monkeypatch.setattr(media_mod, 'urlopen', _urlopen([
            ('example.com/favicon.png', _FakeResp(b'x')),  # content-length 1, below threshold
            ('example.com', _FakeResp(html)),
        ]))
        assert host._find_favicon_url('https://example.com') is None

    def test_network_error_returns_none(self, host, monkeypatch):
        monkeypatch.setattr(media_mod, 'urlopen', lambda *a, **k: (_ for _ in ()).throw(OSError('down')))
        assert host._find_favicon_url('https://example.com') is None


# ─── README fetch thread ──────────────────────────────────────────────────────

class TestFetchReadmeThread:
    def test_readme_found(self, host, idle, monkeypatch):
        monkeypatch.setattr(media_mod, 'urlopen', _urlopen([
            ('README.md', _FakeResp(b'# hello readme')),
        ]))
        pkg = _pkg(homepage='https://github.com/o/r')
        results = []
        host._fetch_readme_thread(pkg, lambda p, t: results.append((p, t)))
        fn, args, _ = idle[-1]
        fn(*args)
        assert args[0] is pkg
        assert args[1] == '# hello readme'

    def test_no_owner_passes_none(self, host, idle, monkeypatch):
        calls = []
        monkeypatch.setattr(media_mod, 'urlopen', lambda *a, **k: calls.append(1) or _FakeResp(b''))
        pkg = _pkg(homepage='https://example.com/plain')
        results = []
        host._fetch_readme_thread(pkg, lambda p, t: results.append((p, t)))
        fn, args, _ = idle[-1]
        fn(*args)
        assert args[1] is None
        assert calls == []

    def test_tries_next_readme_name_on_failure(self, host, idle, monkeypatch):
        def urlopen(req, timeout=None):
            url = req.full_url
            if 'README.md' in url:
                raise OSError('404')
            if 'readme.md' in url:
                return _FakeResp(b'lowercase readme')
            raise OSError(url)

        monkeypatch.setattr(media_mod, 'urlopen', urlopen)
        pkg = _pkg(homepage='https://github.com/o/r')
        results = []
        host._fetch_readme_thread(pkg, lambda p, t: results.append((p, t)))
        fn, args, _ = idle[-1]
        fn(*args)
        assert args[1] == 'lowercase readme'


# ─── icon fetch ───────────────────────────────────────────────────────────────

class TestFetchIcon:
    def _png_bytes(self):
        # Minimal valid-enough payload (>200 bytes) — content matters only for
        # length checks and pixbuf loader, which is stubbed.
        return b'\x89PNG\r\n\x1a\n' + b'0' * 300

    def test_cached_icon_used(self, host, monkeypatch):
        icon_path = os.path.join(host._cache_dir, 'icon_ripgrep.png')
        with open(icon_path, 'wb') as f:
            f.write(b'cached')

        pixbuf = GdkPixbuf.Pixbuf()
        monkeypatch.setattr(GdkPixbuf.Pixbuf, 'new_from_file_at_scale',
                            staticmethod(lambda p, w, h, k: pixbuf))
        monkeypatch.setattr(media_mod, 'urlopen', lambda *a, **k: (_ for _ in ()).throw(AssertionError('no network')))
        pkg = _pkg(name='ripgrep')
        result = host._fetch_icon(pkg)
        assert result is pixbuf

    def test_explicit_icon_url_used_first(self, host, monkeypatch, stub_pixbuf_loader):
        data = self._png_bytes()
        monkeypatch.setattr(media_mod, 'urlopen', _urlopen([
            ('icons.example.com', _FakeResp(data, headers={'Content-Type': 'image/png'})),
        ]))
        pkg = _pkg(name='app', icon_url='https://icons.example.com/app.png')
        result = host._fetch_icon(pkg)
        assert result is not None
        assert os.path.exists(os.path.join(host._cache_dir, 'icon_app.png'))

    def test_github_avatar_appended_for_github_homepage(self, host, monkeypatch, stub_pixbuf_loader):
        data = self._png_bytes()
        monkeypatch.setattr(media_mod, 'urlopen', _urlopen([
            ('github.com', _FakeResp(data, headers={'Content-Type': 'image/png'})),
        ]))
        pkg = _pkg(name='cli', homepage='https://github.com/owner/cli',
                   source_url='https://github.com/owner/cli/archive/1.0.tar.gz')
        result = host._fetch_icon(pkg)
        assert result is not None

    def test_short_payload_filtered(self, host, monkeypatch):
        monkeypatch.setattr(media_mod, 'urlopen', _urlopen([
            ('example.com', _FakeResp(b'tiny')),  # < 200 bytes → skipped
            ('s2.google.com', _FakeResp(b'tiny')),
        ]))
        pkg = _pkg(name='app', homepage='https://example.com')
        assert host._fetch_icon(pkg) is None

    def test_no_icon_sources_returns_none(self, host, monkeypatch):
        calls = []
        monkeypatch.setattr(media_mod, 'urlopen', lambda *a, **k: calls.append(1) or _FakeResp(b''))
        pkg = _pkg(name='app')  # no homepage, no icon_url, no source_url
        assert host._fetch_icon(pkg) is None

    def test_ico_conversion_path(self, host, monkeypatch, stub_pixbuf_loader):
        # Build a real ICO containing an embedded PNG so ico_to_png decodes it.
        png = b'\x89PNG\r\n\x1a\n' + b'1' * 300
        ico = struct_pack_ico(png)
        html = b'<html><head><link rel="icon" href="/favicon.ico"></head></html>'
        monkeypatch.setattr(media_mod, 'urlopen', _urlopen([
            ('example.com/favicon.ico', _FakeResp(ico, headers={'Content-Type': 'image/x-icon'})),
            ('example.com', _FakeResp(html)),
        ]))
        pkg = _pkg(name='app', homepage='https://example.com')
        result = host._fetch_icon(pkg)
        assert result is not None


def struct_pack_ico(png):
    """Wrap PNG bytes in a minimal ICO container (single embedded-PNG entry)."""
    import struct
    header = struct.pack('<HHH', 0, 1, 1)
    entry = struct.pack('<BBBBHHII', 16, 16, 0, 0, 1, 32, len(png), 22)
    return header + entry + png


# ─── screenshot fetch ─────────────────────────────────────────────────────────

class TestFetchScreenshot:
    def test_cached_screenshot_used(self, host, idle, monkeypatch):
        shot = os.path.join(host._cache_dir, 'screenshot_app.jpg')
        with open(shot, 'wb') as f:
            f.write(b'cached-jpg')

        pixbuf = GdkPixbuf.Pixbuf()
        monkeypatch.setattr(GdkPixbuf.Pixbuf, 'new_from_file_at_scale',
                            staticmethod(lambda p, w, h, k: pixbuf))
        pkg = _pkg(name='app')
        results = []
        host._fetch_screenshot_thread(pkg, lambda p, s: results.append((p, s)))
        fn, args, _ = idle[-1]
        fn(*args)
        assert args[0] is pkg
        assert args[1] is pixbuf

    def test_download_saves_and_returns(self, host, idle, monkeypatch, stub_pixbuf_loader):
        data = b'\xff\xd8\xff\xe0' + b'2' * 500  # fake jpeg > 100 bytes
        monkeypatch.setattr(media_mod, 'urlopen', _urlopen([
            ('tavern-metadata', _FakeResp(data, headers={'Content-Type': 'image/jpeg'})),
        ]))
        pkg = _pkg(name='app')
        results = []
        host._fetch_screenshot_thread(pkg, lambda p, s: results.append((p, s)))
        fn, args, _ = idle[-1]
        fn(*args)
        assert args[1] is not None
        saved = os.path.join(host._cache_dir, 'screenshot_app.jpg')
        assert os.path.exists(saved)
        assert open(saved, 'rb').read() == data

    def test_all_sources_fail_passes_none(self, host, idle, monkeypatch):
        monkeypatch.setattr(media_mod, 'urlopen', lambda *a, **k: (_ for _ in ()).throw(OSError('down')))
        pkg = _pkg(name='app')
        results = []
        host._fetch_screenshot_thread(pkg, lambda p, s: results.append((p, s)))
        fn, args, _ = idle[-1]
        fn(*args)
        assert args[1] is None


# ─── inflight coalescing ──────────────────────────────────────────────────────

class TestFetchIconAsync:
    def test_second_request_for_same_package_coalesced(self, host):
        pkg = _pkg(name='ripgrep')
        cbs = []
        host.fetch_icon_async(pkg, lambda p, i: cbs.append(1))
        host.fetch_icon_async(pkg, lambda p, i: cbs.append(2))
        assert len(host._icon_executor.submitted) == 1
        assert len(host._icon_inflight['ripgrep']) == 2

    def test_different_packages_submit_separately(self, host):
        host.fetch_icon_async(_pkg(name='a'), lambda *a: None)
        host.fetch_icon_async(_pkg(name='b'), lambda *a: None)
        assert len(host._icon_executor.submitted) == 2

    def test_job_clears_inflight_and_dispatches_callbacks(self, host, idle, monkeypatch):
        pkg = _pkg(name='ripgrep')
        pixbuf = GdkPixbuf.Pixbuf()
        monkeypatch.setattr(host, '_fetch_icon', lambda p: pixbuf)
        results = []
        host.fetch_icon_async(pkg, lambda p, i: results.append((p, i)))
        host._fetch_icon_job(pkg)

        assert 'ripgrep' not in host._icon_inflight
        assert len(idle) == 1
        fn, args, _ = idle[-1]
        fn(*args)
        assert args[0] is pkg and args[1] is pixbuf

    def test_job_handles_fetch_exception(self, host, idle, monkeypatch):
        pkg = _pkg(name='ripgrep')

        def boom(p):
            raise RuntimeError('bad image')

        monkeypatch.setattr(host, '_fetch_icon', boom)
        results = []
        host.fetch_icon_async(pkg, lambda p, i: results.append((p, i)))
        host._fetch_icon_job(pkg)

        fn, args, _ = idle[-1]
        fn(*args)
        assert args[1] is None  # failure yields None, not a crash


class TestCacheSlug:
    """Cache filenames must not let untrusted package names escape the dir."""

    def test_traversal_dots_are_stripped(self):
        assert media_mod._cache_slug('../../etc/passwd') == 'etc_passwd'
        assert media_mod._cache_slug('/etc/passwd') == 'etc_passwd'

    def test_shell_metachars_folded(self):
        assert media_mod._cache_slug('foo;rm -rf /') == 'foo_rm_-rf'
        assert media_mod._cache_slug("evil$(id)") == 'evil_id'

    def test_safe_names_unchanged(self):
        assert media_mod._cache_slug('ripgrep') == 'ripgrep'
        assert media_mod._cache_slug('font-fira-code') == 'font-fira-code'
        assert media_mod._cache_slug('foo.bar_baz-1.2') == 'foo.bar_baz-1.2'

    def test_empty_falls_back(self):
        assert media_mod._cache_slug('') == 'unnamed'
        assert media_mod._cache_slug(None) == 'unnamed'

    def test_slug_is_single_path_component(self):
        import os
        slug = media_mod._cache_slug('a/b/../../c')
        # No separators survive; any ``..`` artifact is collapsed.
        assert '/' not in slug
        assert '..' not in slug


class TestReadCapped:
    """Downloads are bounded so a hostile README can't OOM the app."""

    def test_small_payload_passes_through(self):
        data = b'x' * 100
        assert media_mod._read_capped(SimpleNamespace(read=lambda n: data)) == data

    def test_oversized_payload_raises(self):
        big = b'x' * (media_mod.MAX_IMAGE_BYTES + 1)

        class Chunked:
            def __init__(self):
                self.sent = 0

            def read(self, n):
                if self.sent >= len(big):
                    return b''
                out = big[self.sent:self.sent + n]
                self.sent += n
                return out

        import pytest
        with pytest.raises(MemoryError):
            media_mod._read_capped(Chunked())

    def test_chunked_streaming_accumulates(self):
        class Chunked:
            def __init__(self, chunks):
                self.chunks = list(chunks)

            def read(self, n):
                return self.chunks.pop(0) if self.chunks else b''

        out = media_mod._read_capped(Chunked([b'ab', b'cd', b'ef']))
        assert out == b'abcdef'
