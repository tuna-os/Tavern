# test_asset_loader.py - Tests for AssetLoaderController
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from gi.repository import Gdk, GdkPixbuf, GLib, GObject

from tavern.asset_loader import AssetLoaderController
from tavern.backend import Package


@pytest.fixture
def sample_pixbuf():
    return GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 32, 32)


@pytest.fixture
def sample_package():
    return Package({'name': 'ripgrep', 'desc': 'Fast line-oriented search'}, 'formula')


class MockBackend(GObject.Object):
    def __init__(self, pixbuf=None):
        super().__init__()
        self.pixbuf = pixbuf
        self.icon_calls = []
        self.screenshot_calls = []

    def fetch_icon_async(self, package, callback):
        self.icon_calls.append(package)
        if callback:
            callback(package, self.pixbuf)

    def fetch_screenshot_async(self, package, callback):
        self.screenshot_calls.append(package)
        if callback:
            callback(package, self.pixbuf)


def test_asset_loader_init_and_backend():
    controller = AssetLoaderController()
    assert controller._backend is None

    backend = MockBackend()
    controller.set_backend(backend)
    assert controller._backend is backend


def test_asset_loader_fetch_icon_with_backend(sample_package, sample_pixbuf):
    backend = MockBackend(pixbuf=sample_pixbuf)
    controller = AssetLoaderController(backend=backend)
    controller.set_package(sample_package)

    received_texture = []
    signals_received = []

    controller.connect('icon-loaded', lambda loader, pkg, tex: signals_received.append((pkg, tex)))

    def on_icon(pkg, tex):
        received_texture.append((pkg, tex))

    controller.fetch_icon(sample_package, on_icon)

    assert len(backend.icon_calls) == 1
    assert len(received_texture) == 1
    pkg, tex = received_texture[0]
    assert pkg.name == 'ripgrep'
    assert tex is not None
    assert isinstance(tex, Gdk.Texture)

    assert len(signals_received) == 1
    assert controller.get_cached_icon('ripgrep') == tex

    # Second fetch should hit memory cache immediately without calling backend again
    cached_cb = []
    controller.fetch_icon(sample_package, lambda p, t: cached_cb.append((p, t)))
    assert len(backend.icon_calls) == 1
    assert len(cached_cb) == 1
    assert cached_cb[0][1] == tex


def test_asset_loader_fetch_screenshot_with_backend(sample_package, sample_pixbuf):
    backend = MockBackend(pixbuf=sample_pixbuf)
    controller = AssetLoaderController(backend=backend)
    controller.set_package(sample_package)

    received_texture = []
    signals_received = []

    controller.connect('screenshot-loaded', lambda loader, pkg, tex: signals_received.append((pkg, tex)))

    def on_screenshot(pkg, tex):
        received_texture.append((pkg, tex))

    controller.fetch_screenshot(sample_package, on_screenshot)

    assert len(backend.screenshot_calls) == 1
    assert len(received_texture) == 1
    pkg, tex = received_texture[0]
    assert pkg.name == 'ripgrep'
    assert tex is not None
    assert isinstance(tex, Gdk.Texture)

    assert len(signals_received) == 1
    assert controller.get_cached_screenshot('ripgrep') == tex


def test_asset_loader_load_assets(sample_package, sample_pixbuf):
    backend = MockBackend(pixbuf=sample_pixbuf)
    controller = AssetLoaderController(backend=backend)

    controller.load_assets(sample_package)
    assert len(backend.icon_calls) == 1
    assert len(backend.screenshot_calls) == 1


def test_asset_loader_no_backend(sample_package):
    controller = AssetLoaderController(backend=None)

    cb_calls = []
    res = controller.fetch_icon(sample_package, lambda p, t: cb_calls.append(t))
    assert res is None
    assert cb_calls == [None]

    cb_ss_calls = []
    res_ss = controller.fetch_screenshot(sample_package, lambda p, t: cb_ss_calls.append(t))
    assert res_ss is None
    assert cb_ss_calls == [None]


def test_asset_loader_cache_management(sample_package, sample_pixbuf):
    controller = AssetLoaderController()
    texture = Gdk.Texture.new_for_pixbuf(sample_pixbuf)

    controller.cache_icon_texture('ripgrep', texture)
    controller.cache_screenshot_texture('ripgrep', texture)

    assert controller.get_cached_icon('ripgrep') == texture
    assert controller.get_cached_screenshot('ripgrep') == texture

    controller.clear_cache()
    assert controller.get_cached_icon('ripgrep') is None
    assert controller.get_cached_screenshot('ripgrep') is None
