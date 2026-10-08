# asset_loader.py - Asset loading and caching controller for packages
# SPDX-License-Identifier: GPL-3.0-or-later

"""Asset loading controller for package details and tiles.

This module separates asset loading concerns (icons, screenshots) from
monolithic UI classes, providing a dedicated interface for fetching,
caching, and managing package-related visual media.

See Tavern#207 and Tavern#220 for context.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')

from gi.repository import Gdk, GLib, GObject
from .logging_util import get_logger

_log = get_logger('asset_loader')


class AssetLoaderController(GObject.Object):
    """Manages icon and screenshot fetching, caching, and lifecycle for packages.

    Extracted from TavernPackageDetails to separate asset orchestration from
    page UI layout, WebView rendering, and task management.
    """

    __gtype_name__ = 'TavernAssetLoaderController'

    __gsignals__ = {
        'icon-loaded': (GObject.SignalFlags.RUN_LAST, None, (object, object)),          # package, Gdk.Texture or None
        'screenshot-loaded': (GObject.SignalFlags.RUN_LAST, None, (object, object)),    # package, Gdk.Texture or None
    }

    def __init__(self, backend=None, **kwargs):
        super().__init__(**kwargs)
        self._backend = backend
        self._cached_icon_textures = {}        # package.name -> Gdk.Texture
        self._cached_screenshot_textures = {}  # package.name -> Gdk.Texture
        self._active_package = None

    def set_backend(self, backend):
        """Update or assign the backend instance."""
        self._backend = backend

    def set_package(self, package):
        """Set the active package whose assets are currently being displayed."""
        self._active_package = package

    def load_assets(self, package):
        """Trigger asynchronous fetching of icon and screenshot for package."""
        self.set_package(package)
        if not package or not self._backend:
            return

        self.fetch_icon(package)
        self.fetch_screenshot(package)

    def fetch_icon(self, package, callback=None):
        """Fetch icon for a package asynchronously.

        If a cached Gdk.Texture is already available, callback is invoked immediately.
        Otherwise delegates to backend.fetch_icon_async.
        """
        pkg_name = getattr(package, 'name', str(package))
        if pkg_name in self._cached_icon_textures:
            texture = self._cached_icon_textures[pkg_name]
            if callback:
                callback(package, texture)
            self.emit('icon-loaded', package, texture)
            return texture

        if not self._backend:
            _log.debug('No backend available for icon fetch: %s', pkg_name)
            if callback:
                callback(package, None)
            return None

        def _on_backend_icon(pkg, pixbuf):
            texture = None
            if pixbuf:
                try:
                    texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                    self._cached_icon_textures[pkg.name] = texture
                except Exception as e:
                    _log.debug('Failed to convert icon pixbuf to texture: %s', e)
            if callback:
                callback(pkg, texture)
            if self._active_package and pkg.name == self._active_package.name:
                self.emit('icon-loaded', pkg, texture)

        self._backend.fetch_icon_async(package, _on_backend_icon)
        return None

    def fetch_screenshot(self, package, callback=None):
        """Fetch screenshot for a package asynchronously.

        If a cached Gdk.Texture is already available, callback is invoked immediately.
        Otherwise delegates to backend.fetch_screenshot_async.
        """
        pkg_name = getattr(package, 'name', str(package))
        if pkg_name in self._cached_screenshot_textures:
            texture = self._cached_screenshot_textures[pkg_name]
            if callback:
                callback(package, texture)
            self.emit('screenshot-loaded', package, texture)
            return texture

        if not self._backend:
            _log.debug('No backend available for screenshot fetch: %s', pkg_name)
            if callback:
                callback(package, None)
            return None

        def _on_backend_screenshot(pkg, pixbuf):
            texture = None
            if pixbuf:
                try:
                    texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                    self._cached_screenshot_textures[pkg.name] = texture
                except Exception as e:
                    _log.debug('Failed to convert screenshot pixbuf to texture: %s', e)
            if callback:
                callback(pkg, texture)
            if self._active_package and pkg.name == self._active_package.name:
                self.emit('screenshot-loaded', pkg, texture)

        self._backend.fetch_screenshot_async(package, _on_backend_screenshot)
        return None

    def get_cached_icon(self, package_name):
        """Return cached icon texture if present."""
        return self._cached_icon_textures.get(package_name)

    def get_cached_screenshot(self, package_name):
        """Return cached screenshot texture if present."""
        return self._cached_screenshot_textures.get(package_name)

    def cache_icon_texture(self, package_name, texture):
        """Explicitly store an icon texture in memory cache."""
        self._cached_icon_textures[package_name] = texture

    def cache_screenshot_texture(self, package_name, texture):
        """Explicitly store a screenshot texture in memory cache."""
        self._cached_screenshot_textures[package_name] = texture

    def clear_cache(self):
        """Clear memory cache of textures."""
        self._cached_icon_textures.clear()
        self._cached_screenshot_textures.clear()
