# brewfile_dialog.py
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, GObject, Gio
from .backend import Package
from .logging_util import get_logger

_log = get_logger('brewfile_dialog')


@Gtk.Template(resource_path='/org.tunaos.tavern/brewfile-dialog.ui')
class TavernBrewfileDialog(Adw.Window):
    __gtype_name__ = 'TavernBrewfileDialog'

    list_box = Gtk.Template.Child()

    def __init__(self, window, **kwargs):
        super().__init__(**kwargs)
        self.main_window = window
        self.backend = window.backend
        self.task_manager = window.task_manager
        self.parsed_data = None
        self.set_modal(True)
        self._packages = []

    def load_brewfile(self, path):
        _log.info('Loading Brewfile: %s', path)
        self.parsed_data = self.backend.parse_brewfile(path)
        self.set_title(f"Brewfile: {path.split('/')[-1]}")
        self._populate_list()

    def _populate_list(self):
        # Create package rows
        # Taps
        for tap in self.parsed_data['taps']:
            row = Adw.ActionRow(title=f'Tap: {tap}')
            self.list_box.append(row)
        
        # Formulae
        for brew in self.parsed_data['formulae']:
            pkg = self._get_or_create_package(brew, 'formula')
            if pkg:
                self._packages.append(pkg)
                row = Adw.ActionRow(title=f'Formula: {pkg.display_name or pkg.name}')
                if pkg.installed:
                    row.set_subtitle("Installed")
                self.list_box.append(row)
        
        # Casks
        for cask in self.parsed_data['casks']:
            pkg = self._get_or_create_package(cask, 'cask')
            if pkg:
                self._packages.append(pkg)
                row = Adw.ActionRow(title=f'Cask: {pkg.display_name or pkg.name}')
                if pkg.installed:
                    row.set_subtitle("Installed")
                self.list_box.append(row)

    def _get_or_create_package(self, name, pkg_type):
        pkgs = self.backend.formulae if pkg_type == 'formula' else self.backend.casks
        for p in pkgs:
            if p.name == name or p.full_name == name:
                return p
        
        # Create a placeholder if not loaded or not in central index
        data = {'name': [name], 'token': name} if pkg_type == 'cask' else {'name': name}
        return Package(data=data, pkg_type=pkg_type, installed_set=[])

    @Gtk.Template.Callback()
    def _on_install_all_clicked(self, *args):
        _log.info('Install-all from Brewfile: %d packages', len(self._packages))
        for tap in self.parsed_data['taps']:
            # Using an arbitrary task for tap
            pass
        
        for pkg in self._packages:
            if not pkg.installed:
                self.task_manager.install(pkg)
        self.close()

    @Gtk.Template.Callback()
    def _on_remove_all_clicked(self, *args):
        _log.info('Remove-all from Brewfile: %d packages', len(self._packages))
        for pkg in self._packages:
            if pkg.installed:
                self.task_manager.remove(pkg)
        self.close()
