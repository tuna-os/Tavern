# search_provider.py - GNOME Shell Search Provider
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import threading

import gi
gi.require_version('Gio', '2.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gio, GLib

from .logging_util import get_logger

_log = get_logger('search_provider')

# The XML interface we will implement
SEARCH_PROVIDER_XML = """
<node>
  <interface name="org.gnome.Shell.SearchProvider2">
    <method name="GetInitialResultSet">
      <arg type="as" name="Terms" direction="in"/>
      <arg type="as" name="Results" direction="out"/>
    </method>
    <method name="GetSubsearchResultSet">
      <arg type="as" name="PreviousResults" direction="in"/>
      <arg type="as" name="Terms" direction="in"/>
      <arg type="as" name="Results" direction="out"/>
    </method>
    <method name="GetResultMetas">
      <arg type="as" name="Results" direction="in"/>
      <arg type="aa{sv}" name="Metas" direction="out"/>
    </method>
    <method name="ActivateResult">
      <arg type="s" name="Result" direction="in"/>
      <arg type="as" name="Terms" direction="in"/>
      <arg type="u" name="Timestamp" direction="in"/>
    </method>
    <method name="LaunchSearch">
      <arg type="as" name="Terms" direction="in"/>
      <arg type="u" name="Timestamp" direction="in"/>
    </method>
  </interface>
</node>
"""


class TavernSearchProvider:
    """Implements the org.gnome.Shell.SearchProvider2 D-Bus interface."""

    def __init__(self, application):
        self.application = application
        self.connection = None
        self.registration_id = 0
        self._node_info = Gio.DBusNodeInfo.new_for_xml(SEARCH_PROVIDER_XML)
        self._interface_info = self._node_info.interfaces[0]
        self._packages_cache = []
        self._cache_loaded = False
        self._cache_lock = threading.Lock()

    def export(self, connection):
        """Export the search provider on the given D-Bus connection."""
        if self.registration_id > 0:
            return

        self.connection = connection
        # Object path must match the ObjectPath in the search-provider ini:
        # slash-separated app id + /SearchProvider. Dots are illegal in
        # D-Bus object paths, so the id must be transformed, not embedded.
        app_id = None
        if self.application is not None:
            app_id = self.application.get_application_id()
        app_id = app_id or 'org.tunaos.tavern'
        object_path = '/' + app_id.replace('.', '/') + '/SearchProvider'
        try:
            self.registration_id = self.connection.register_object(
                object_path,
                self._interface_info,
                self._handle_method_call,
                None,  # get_property
                None   # set_property
            )
            _log.info('Search provider exported on D-Bus')
        except Exception as e:
            _log.error('Failed to export search provider: %s', e)

    def unexport(self):
        """Unexport the search provider."""
        if self.registration_id > 0 and self.connection:
            self.connection.unregister_object(self.registration_id)
            self.registration_id = 0
            self.connection = None
            _log.info('Search provider unexported')

    def _ensure_cache_loaded(self):
        with self._cache_lock:
            if self._cache_loaded:
                return

            cache_dir = os.path.join(GLib.get_user_cache_dir(), 'tavern')
            cache_path = os.path.join(cache_dir, 'linux_packages.json')

            if os.path.exists(cache_path):
                try:
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        self._packages_cache = json.load(f)
                    _log.debug('Loaded %d packages from search provider cache', len(self._packages_cache))
                except Exception as e:
                    _log.error('Failed to load search provider cache: %s', e)
                    self._packages_cache = []

            self._cache_loaded = True

    def _search(self, terms):
        self._ensure_cache_loaded()
        
        query = " ".join(terms).lower().strip()
        if not query:
            return []

        results = []
        for pkg in self._packages_cache:
            name = (pkg.get('name') or '').lower()
            display_name = (pkg.get('display_name') or '').lower()
            desc = (pkg.get('description') or '').lower()

            if query in name or query in display_name or query in desc:
                results.append(pkg)

        def sort_key(pkg):
            n = (pkg.get('name') or '').lower()
            if n == query:
                return (0, n)
            if n.startswith(query):
                return (1, n)
            return (2, n)

        results.sort(key=sort_key)
        # Limit to reasonable number of results for GNOME shell
        return [p.get('name') for p in results[:20] if p.get('name')]

    def _handle_method_call(self, connection, sender, object_path, interface_name, method_name, parameters, invocation):
        _log.debug('SearchProvider method called: %s', method_name)

        if method_name == "GetInitialResultSet":
            terms = parameters.unpack()[0]
            results = self._search(terms)
            invocation.return_value(GLib.Variant("(as)", (results,)))

        elif method_name == "GetSubsearchResultSet":
            # Just do a fresh search as it's fast enough
            terms = parameters.unpack()[1]
            results = self._search(terms)
            invocation.return_value(GLib.Variant("(as)", (results,)))

        elif method_name == "GetResultMetas":
            ids = parameters.unpack()[0]
            self._ensure_cache_loaded()
            
            # Map of name -> package struct for quick lookup
            pkg_map = {p.get('name'): p for p in self._packages_cache}
            cache_dir = os.path.join(GLib.get_user_cache_dir(), 'tavern')

            # Fallback icon: the app's own icon, resolved from the actual
            # application id so it also works for the .Devel build (whose
            # installed icons are renamed to org.tunaos.tavern.Devel*).
            app_id = self.application.get_application_id() or 'org.tunaos.tavern'
            fallback_icon = Gio.ThemedIcon.new_with_default_fallbacks(app_id)

            metas = []
            for pkg_id in ids:
                pkg = pkg_map.get(pkg_id) or {}

                # GNOME Shell expects one meta per requested id — emit a
                # minimal entry rather than skipping, or results misalign.
                meta = {
                    "id": GLib.Variant("s", pkg_id),
                    "name": GLib.Variant("s", pkg.get('display_name') or pkg_id),
                    "description": GLib.Variant("s", pkg.get('description') or "")
                }

                # Prefer a previously downloaded per-package icon
                icon_path = os.path.join(cache_dir, f'icon_{pkg_id}.png')
                try:
                    if os.path.getsize(icon_path) > 0:
                        gfile = Gio.File.new_for_path(icon_path)
                        meta["icon"] = Gio.FileIcon.new(gfile).serialize()
                except OSError:
                    pass
                if "icon" not in meta:
                    meta["icon"] = fallback_icon.serialize()

                metas.append(meta)

            invocation.return_value(GLib.Variant("(aa{sv})", (metas,)))

        elif method_name == "ActivateResult":
            pkg_id = parameters.unpack()[0]
            _log.info('Activating result: %s', pkg_id)
            
            # Use the application action to show the package
            self.application.activate_action("show-package", GLib.Variant("s", pkg_id))
            invocation.return_value(None)

        elif method_name == "LaunchSearch":
            terms = parameters.unpack()[0]
            query = " ".join(terms)
            _log.info('Launching search for: %s', query)
            
            # Open app and search (we re-use show-package with the query, or could just open window)
            # Actually just activating the app is usually enough for LaunchSearch
            # because GNOME Shell moves focus to the app
            self.application.activate()
            invocation.return_value(None)

        else:
            invocation.return_error_literal(Gio.DBusError.UNKNOWN_METHOD, "Unknown method")

