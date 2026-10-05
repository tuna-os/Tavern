"""Asset loading controller for package details.

This module extracts asset loading concerns (icons, screenshots) from
TavernPackageDetails, providing a focused interface for fetching and
managing package-related assets.

See Tavern#207 for the refactoring roadmap.
"""

import gi
gi.require_version('Gtk', '4.0')

from gi.repository import GLib, Gtk
from .logging_util import get_logger

_log = get_logger('asset_loader')


class AssetLoaderController:
    """Manages icon and screenshot fetching and caching for packages.
    
    Extracted from TavernPackageDetails to separate asset lifecycle from
    UI rendering and task management. This allows:
    - Independent testing of cache policies and timeout handling
    - Security updates to asset handling without touching the page
    - Reuse of asset loading in other components
    
    Phase 2 will add:
    - Configurable cache policies (TTL, size limits)
    - Timeout handling and retry logic
    - Progress callbacks for UI feedback
    - Cancellation support
    """
    
    def __init__(self, backend=None):
        """Initialize the asset loader.
        
        Args:
            backend: Backend instance for asset fetching (optional for testing)
        """
        self._backend = backend
        self._icons_loading = {}  # package_name -> loading state
        self._screenshots_loading = {}
        self._cached_icons = {}
        self._cached_screenshots = {}
    
    def fetch_icon(self, package_name, callback=None):
        """Fetch icon for a package.
        
        Args:
            package_name: Name of the package
            callback: Optional callback(icon_pixbuf, error) on completion
            
        Returns:
            Cached icon pixbuf if available, None otherwise
        """
        if package_name in self._cached_icons:
            if callback:
                callback(self._cached_icons[package_name], None)
            return self._cached_icons[package_name]
        
        if not self._backend:
            _log.warning(f"No backend available for icon fetch: {package_name}")
            if callback:
                callback(None, "No backend")
            return None
        
        # Mark as loading
        self._icons_loading[package_name] = True
        
        # Actual fetch would happen here (async via backend)
        # For Phase 1, this is the interface only
        _log.debug(f"Fetching icon for {package_name}")
        
        return None
    
    def fetch_screenshot(self, package_name, callback=None):
        """Fetch screenshot for a package.
        
        Args:
            package_name: Name of the package
            callback: Optional callback(screenshot_pixbuf, error) on completion
            
        Returns:
            Cached screenshot pixbuf if available, None otherwise
        """
        if package_name in self._cached_screenshots:
            if callback:
                callback(self._cached_screenshots[package_name], None)
            return self._cached_screenshots[package_name]
        
        if not self._backend:
            _log.warning(f"No backend available for screenshot fetch: {package_name}")
            if callback:
                callback(None, "No backend")
            return None
        
        # Mark as loading
        self._screenshots_loading[package_name] = True
        
        # Actual fetch would happen here (async via backend)
        # For Phase 1, this is the interface only
        _log.debug(f"Fetching screenshot for {package_name}")
        
        return None
    
    def cache_icon(self, package_name, pixbuf):
        """Cache an icon pixbuf.
        
        Args:
            package_name: Name of the package
            pixbuf: Gtk.GdkPixbuf to cache
        """
        self._cached_icons[package_name] = pixbuf
        self._icons_loading.pop(package_name, None)
        _log.debug(f"Cached icon for {package_name}")
    
    def cache_screenshot(self, package_name, pixbuf):
        """Cache a screenshot pixbuf.
        
        Args:
            package_name: Name of the package
            pixbuf: Gtk.GdkPixbuf to cache
        """
        self._cached_screenshots[package_name] = pixbuf
        self._screenshots_loading.pop(package_name, None)
        _log.debug(f"Cached screenshot for {package_name}")
    
    def clear_cache(self):
        """Clear all cached assets."""
        self._cached_icons.clear()
        self._cached_screenshots.clear()
        self._icons_loading.clear()
        self._screenshots_loading.clear()
        _log.debug("Asset cache cleared")
    
    def is_icon_loading(self, package_name):
        """Check if icon is currently loading.
        
        Args:
            package_name: Name of the package
            
        Returns:
            True if currently fetching
        """
        return self._icons_loading.get(package_name, False)
    
    def is_screenshot_loading(self, package_name):
        """Check if screenshot is currently loading.
        
        Args:
            package_name: Name of the package
            
        Returns:
            True if currently fetching
        """
        return self._screenshots_loading.get(package_name, False)
