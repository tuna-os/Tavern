# version_history_dialog.py - Show version history and changelogs
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, GObject, GLib
from .logging_util import get_logger

_log = get_logger('version_history')


class TavernVersionHistoryDialog(Adw.NavigationPage):
    """Show version history and changelogs for a package, with optional pinning."""

    __gtype_name__ = 'TavernVersionHistoryDialog'

    __gsignals__ = {
        'pin-version': (GObject.SignalFlags.RUN_LAST, None, (str,)),  # version to pin
    }

    def __init__(self, package=None, backend=None, **kwargs):
        super().__init__(**kwargs)
        self._package = package
        self._backend = backend
        self._current_selection = None

        # Build UI programmatically
        self._build_ui()

        if package:
            _log.debug('Opening version history for %s (%s)', package.name, package.pkg_type)
            self.set_title(f'Version History: {package.display_name or package.name}')
            self._load_version_history()

    def _build_ui(self):
        """Build the two-column layout: versions list + changelog detail."""
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main_box.set_margin_top(12)
        main_box.set_margin_bottom(12)
        main_box.set_margin_start(12)
        main_box.set_margin_end(12)

        # Header with title + close button
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        # Title
        title_label = Gtk.Label(label='Loading versions...')
        title_label.set_halign(Gtk.Align.START)
        title_label.add_css_class('title-3')
        header_box.append(title_label)
        self._title_label = title_label

        # Pin button (right-aligned)
        pin_button = Gtk.Button(label='Pin to This Version')
        pin_button.connect('clicked', self._on_pin_clicked)
        pin_button.set_halign(Gtk.Align.END)
        header_box.set_hexpand(True)
        header_box.append(pin_button)
        self._pin_button = pin_button

        main_box.append(header_box)

        # Horizontal paned layout: versions list on left, changelog on right
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(200)
        paned.set_wide_handle(True)

        # Left: Versions ListBox
        versions_scroll = Gtk.ScrolledWindow()
        versions_scroll.set_hexpand(True)
        versions_scroll.set_vexpand(True)
        versions_scroll.set_min_content_width(200)

        self._versions_list = Gtk.ListBox()
        self._versions_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._versions_list.connect('row-selected', self._on_version_selected)
        self._versions_list.add_css_class('boxed-list')
        versions_scroll.set_child(self._versions_list)

        paned.set_start_child(versions_scroll)

        # Right: Changelog detail
        changelog_scroll = Gtk.ScrolledWindow()
        changelog_scroll.set_hexpand(True)
        changelog_scroll.set_vexpand(True)
        changelog_scroll.set_min_content_width(300)

        self._changelog_view = Gtk.TextView()
        self._changelog_view.set_editable(False)
        self._changelog_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self._changelog_view.set_monospace(False)
        changelog_scroll.set_child(self._changelog_view)

        paned.set_end_child(changelog_scroll)
        main_box.append(paned)

        # Loading spinner
        spinner_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        spinner_box.set_halign(Gtk.Align.CENTER)
        spinner_box.set_valign(Gtk.Align.CENTER)
        spinner_box.set_spacing(12)

        spinner = Gtk.Spinner()
        spinner.start()
        spinner_box.append(spinner)

        loading_label = Gtk.Label(label='Fetching version history...')
        loading_label.add_css_class('dim-label')
        spinner_box.append(loading_label)

        self._loading_box = spinner_box
        self._spinner = spinner

        # Stack to switch between loading and content
        self._stack = Gtk.Stack()
        self._stack.add_named(self._loading_box, 'loading')
        self._stack.add_named(main_box, 'content')
        self._stack.set_visible_child_name('loading')
        self._stack.set_hexpand(True)
        self._stack.set_vexpand(True)

        self.set_child(self._stack)

    def _load_version_history(self):
        """Load version history in background thread."""
        if not self._package or not self._backend:
            _log.warning('Version history load requested without package or backend')
            return

        def run_load():
            try:
                history = self._backend.get_version_history(
                    self._package.name, self._package.pkg_type
                )
                GLib.idle_add(self._populate_versions, history)
            except Exception as e:
                _log.error('Failed to load version history: %s', e)
                GLib.idle_add(self._show_error, str(e))

        import threading
        thread = threading.Thread(target=run_load, daemon=True)
        thread.start()

    def _populate_versions(self, history):
        """Populate versions list from history data."""
        if not history:
            self._show_error('No version history available')
            return

        _log.info('Loaded %d versions for %s', len(history), self._package.name)

        # Clear list
        while True:
            row = self._versions_list.get_first_child()
            if not row:
                break
            self._versions_list.remove(row)

        # Add version rows
        for idx, version_info in enumerate(history):
            version = version_info.get('version', 'Unknown')
            date = version_info.get('date', '')

            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(12)
            box.set_margin_end(12)

            version_label = Gtk.Label(label=version)
            version_label.set_halign(Gtk.Align.START)
            version_label.add_css_class('monospace')
            box.append(version_label)

            if date:
                date_label = Gtk.Label(label=date)
                date_label.set_halign(Gtk.Align.START)
                date_label.add_css_class('dim-label')
                date_label.add_css_class('caption')
                box.append(date_label)

            row.set_child(box)
            row.version_info = version_info  # Store metadata
            self._versions_list.append(row)

            # Auto-select first version
            if idx == 0:
                self._versions_list.select_row(row)

        # Switch to content view
        self._stack.set_visible_child_name('content')

    def _show_error(self, message):
        """Show error message and hide loading spinner."""
        _log.warning('Version history error: %s', message)
        error_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        error_box.set_halign(Gtk.Align.CENTER)
        error_box.set_valign(Gtk.Align.CENTER)

        error_icon = Gtk.Image.new_from_icon_name('dialog-error-symbolic')
        error_icon.set_icon_size(Gtk.IconSize.LARGE)
        error_box.append(error_icon)

        error_label = Gtk.Label(label='Failed to load version history')
        error_label.add_css_class('title-3')
        error_box.append(error_label)

        detail_label = Gtk.Label(label=message)
        detail_label.add_css_class('dim-label')
        detail_label.set_wrap(True)
        detail_label.set_max_width_chars(40)
        error_box.append(detail_label)

        self._stack.add_named(error_box, 'error')
        self._stack.set_visible_child_name('error')

    def _on_version_selected(self, listbox, row):
        """Handle version selection to display changelog."""
        if not row:
            return

        self._current_selection = row
        version_info = row.version_info
        changelog = version_info.get('changelog', 'No changelog available.')

        self._changelog_view.get_buffer().set_text(changelog, -1)
        _log.debug('Selected version: %s', version_info.get('version', 'Unknown'))

    def _on_pin_clicked(self, button):
        """Emit pin-version signal with selected version."""
        if not self._current_selection:
            _log.warning('Pin clicked but no version selected')
            return

        version = self._current_selection.version_info.get('version', '')
        if version:
            _log.info('Pinning package %s to version %s', self._package.name, version)
            self.emit('pin-version', version)
            # Optionally show toast in parent window (caller can handle)
        else:
            _log.warning('Cannot pin: version unknown')
