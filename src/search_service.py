# search_service.py - Lightweight GNOME Shell search-provider process
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio

from .search_provider import TavernSearchProvider


class TavernSearchService(Gio.Application):
    """Serve cached search results without importing GTK or the package backend."""

    def __init__(self, desktop_app_id='org.tunaos.tavern'):
        super().__init__(
            application_id=f'{desktop_app_id}.SearchProvider',
            flags=Gio.ApplicationFlags.IS_SERVICE,
        )
        self.desktop_app_id = desktop_app_id
        self._provider = TavernSearchProvider(self, desktop_app_id=desktop_app_id)

    def do_dbus_register(self, connection, object_path):
        self._provider.export(connection)
        return Gio.Application.do_dbus_register(self, connection, object_path)

    def do_dbus_unregister(self, connection, object_path):
        self._provider.unexport()
        Gio.Application.do_dbus_unregister(self, connection, object_path)

    def open_package(self, package_name):
        Gio.AppInfo.launch_default_for_uri(
            f'brew://formula/{package_name}', None,
        )

    def open_search(self, query):
        Gio.AppInfo.launch_default_for_uri(f'brew://{query}', None)


def main(desktop_app_id='org.tunaos.tavern'):
    return TavernSearchService(desktop_app_id).run(['tavern-search-provider'])
