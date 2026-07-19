# updates_card.py - Updates card widget showing available package updates
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject, GLib

from .logging_util import get_logger

_log = get_logger('updates_card')


class UpdatesCard(Gtk.Box):
    """Card showing available Homebrew package updates."""

    __gtype_name__ = 'TavernUpdatesCard'

    __gsignals__ = {
        'update-all-requested': (GObject.SignalFlags.RUN_LAST, None, ()),
        'package-activated': (GObject.SignalFlags.RUN_LAST, None, (object,)),  # package object
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.set_spacing(0)
        self.add_css_class('updates-card')
        
        self._backend = None
        self._task_manager = None
        self._outdated_data = None

        # Header
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header_box.set_margin_top(12)
        header_box.set_margin_bottom(12)
        header_box.set_margin_start(12)
        header_box.set_margin_end(12)

        self._count_label = Gtk.Label()
        self._count_label.add_css_class('title-2')
        header_box.append(self._count_label)

        # Update All button
        self._update_all_btn = Gtk.Button(label='Update All')
        self._update_all_btn.connect('clicked', self._on_update_all_clicked)
        header_box.append(self._update_all_btn)

        self.append(header_box)

        # Separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self.append(sep)

        # Scrolled window with updates list
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(False)
        scroll.set_min_content_height(200)
        scroll.set_max_content_height(400)
        scroll.set_propagate_natural_height(True)

        self._updates_list = Gtk.ListBox()
        self._updates_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._updates_list.add_css_class('boxed-list')
        self._updates_list.connect('row-activated', self._on_row_activated)
        scroll.set_child(self._updates_list)

        self.append(scroll)

        self._outdated_packages = []  # List of (name, pkg_type, installed, latest) tuples

    def set_backend(self, backend):
        """Set the backend reference."""
        self._backend = backend
        if backend:
            backend.connect('outdated-changed', self._on_outdated_changed)

    def set_task_manager(self, task_manager):
        """Set the task manager reference."""
        self._task_manager = task_manager

    def _on_outdated_changed(self, backend, outdated_data):
        """Handle backend's outdated-changed signal."""
        _log.debug('Outdated changed signal: %s', outdated_data)
        self._outdated_data = dict(outdated_data) if outdated_data else {}
        # Convert dict to list of tuples for display
        packages_list = [(name, info) for name, info in self._outdated_data.items()]
        self.set_outdated_packages(packages_list)

    def set_outdated_packages(self, outdated_list):
        """Update the list of outdated packages."""
        self._outdated_packages = outdated_list or []

        # Clear existing rows
        while True:
            row = self._updates_list.get_first_child()
            if not row:
                break
            self._updates_list.remove(row)

        # Add new rows
        for name, info in self._outdated_packages:
            # Get pkg_type from info dict, default to 'formula'
            pkg_type = info.get('pkg_type', 'formula')
            
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(12)
            box.set_margin_end(12)

            # Package name with type badge
            header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            
            name_label = Gtk.Label(label=name)
            name_label.set_halign(Gtk.Align.START)
            name_label.add_css_class('body-strong')
            header_box.append(name_label)

            # Type badge
            type_label = Gtk.Label(label=pkg_type)
            type_label.add_css_class('caption')
            type_label.add_css_class('dim-label')
            header_box.append(type_label)
            
            box.append(header_box)

            # Version info
            installed = info.get('installed', '?')
            latest = info.get('latest', '?')
            version_label = Gtk.Label(label=f'{installed} → {latest}')
            version_label.set_halign(Gtk.Align.START)
            version_label.add_css_class('body')
            version_label.add_css_class('dim-label')
            box.append(version_label)

            row.set_child(box)
            # Store metadata as normal Python attributes on the row for later retrieval
            row._package_name = name
            row._package_type = pkg_type
            self._updates_list.append(row)

        # Update count label
        count = len(self._outdated_packages)
        if count == 0:
            self._count_label.set_text('No updates available')
            self._update_all_btn.set_sensitive(False)
        elif count == 1:
            self._count_label.set_text('1 update available')
            self._update_all_btn.set_sensitive(True)
        else:
            self._count_label.set_text(f'{count} updates available')
            self._update_all_btn.set_sensitive(True)

    def _on_update_all_clicked(self, button):
        """Handle Update All button click."""
        _log.info('Update All clicked: %d packages', len(self._outdated_packages))
        if self._task_manager and self._outdated_data:
            for name, info in self._outdated_data.items():
                pkg_type = info.get('pkg_type', 'formula')
                # Find package in backend and queue for upgrade
                package = self._find_package(name, pkg_type)
                if package:
                    _log.info('Queueing upgrade for %s (%s)', name, pkg_type)
                    self._task_manager.upgrade(package)
                else:
                    _log.warning('Could not find package %s (%s) for upgrade', name, pkg_type)

    def _find_package(self, name, pkg_type):
        """Find a package in the backend by name and type."""
        if not self._backend:
            return None
        
        if pkg_type == 'formula':
            for pkg in self._backend.formulae:
                if pkg.name == name or pkg.full_name == name:
                    return pkg
        elif pkg_type == 'cask':
            for pkg in self._backend.casks:
                if pkg.name == name or pkg.full_name == name:
                    return pkg
        return None

    def _on_row_activated(self, listbox, row):
        """Handle row activation - emit signal to show package details."""
        if row:
            name = getattr(row, '_package_name', None)
            pkg_type = getattr(row, '_package_type', None)
            if name:
                _log.info('Activated package: %s (%s)', name, pkg_type)
                package = self._find_package(name, pkg_type)
                if package:
                    self.emit('package-activated', package)
                else:
                    _log.warning('Could not find package for details: %s (%s)', name, pkg_type)
