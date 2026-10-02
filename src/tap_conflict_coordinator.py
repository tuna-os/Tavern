# tap_conflict_coordinator.py - Ambiguous-tap and tap-conflict install dialogs
# SPDX-License-Identifier: GPL-3.0-or-later

import gettext

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk

from .logging_util import get_logger

_ = gettext.gettext

_log = get_logger('tap_conflict_coordinator')


class TapConflictCoordinator:
    """Owns the ambiguous-tap-choice and tap-conflict-resolution dialog flows.

    Extracted from TavernWindow: this only needs a dialog parent, the task
    manager to queue follow-up operations on, and the toast overlay to report
    outcomes on. It carries its own follow-up state (`_pending_reinstall`,
    `_conflict_conn`) rather than storing it on the window.
    """

    def __init__(self, parent, task_manager, toast_overlay):
        self._parent = parent
        self._task_manager = task_manager
        self._toast_overlay = toast_overlay
        self._pending_reinstall = None
        self._conflict_conn = None

    def offer_ambiguous_tap_choice(self, task):
        """Show a dialog letting the user pick which tap to install from."""
        pkg = task.package
        options = task.ambiguous_taps  # ['user/tap/name', ...]

        dialog = Adw.AlertDialog()
        dialog.set_heading(_('Choose a Tap'))
        dialog.set_body(
            _('"{name}" is available from multiple taps.\nChoose which one to install from:').format(name=pkg.display_name or pkg.name)
        )
        dialog.add_response('cancel', _('Cancel'))
        dialog.set_close_response('cancel')

        listbox = Gtk.ListBox()
        listbox.add_css_class('boxed-list')
        listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        listbox.set_margin_top(8)

        for qualified in options:
            # Parse tap name from fully-qualified: user/repo/pkg → user/repo
            parts = qualified.rsplit('/', 1)
            tap_name = parts[0] if len(parts) == 2 else qualified
            row = Adw.ActionRow()
            row.set_title(qualified)
            row.set_subtitle(_('from tap: {tap}').format(tap=tap_name))
            row._qualified = qualified
            listbox.append(row)

        # Select first row by default
        first = listbox.get_row_at_index(0)
        if first:
            listbox.select_row(first)

        dialog.set_extra_child(listbox)
        dialog.add_response('install', _('Install'))
        dialog.set_response_appearance('install', Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response('install')
        dialog.connect('response', self.on_ambiguous_tap_response, listbox, pkg)
        dialog.present(self._parent)

    def on_ambiguous_tap_response(self, dialog, response, listbox, pkg):
        if response != 'install':
            return
        row = listbox.get_selected_row()
        if not row:
            return
        qualified = getattr(row, '_qualified', None)
        if not qualified:
            return
        _log.info('User chose qualified install: %s', qualified)
        self._task_manager.install_qualified(pkg, qualified)

    def offer_tap_conflict_resolution(self, task):
        """Show a dialog offering to switch taps when a multi-tap conflict occurs."""
        pkg = task.package
        info = task.conflict_info
        installed_tap = info['installed_tap']
        target_tap    = info['target_tap']
        is_core = target_tap in ('homebrew/core', 'homebrew/cask')

        dialog = Adw.AlertDialog()
        dialog.set_heading(_('Tap Conflict'))
        dialog.set_body(
            _('"{name}" is already installed from the {tap} tap.\n\n{resolution}').format(
                name=pkg.display_name or pkg.name,
                tap=installed_tap,
                resolution=(
                    _('Would you like to uninstall it from {src} and reinstall from {dst}?').format(src=installed_tap, dst=target_tap)
                    if is_core else
                    _('Formulae with the same name from different taps cannot both be installed.')
                )
            )
        )
        dialog.add_response('cancel', _('Cancel'))
        if is_core:
            dialog.add_response('switch', _('Switch to {tap}').format(tap=target_tap))
            dialog.set_response_appearance('switch', Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')
        dialog.connect('response', self.on_conflict_resolution, task)
        dialog.present(self._parent)

    def on_conflict_resolution(self, dialog, response, task):
        if response != 'switch':
            return
        pkg = task.package
        _log.info('Switching tap for %s: uninstall then reinstall', pkg.name)
        # Queue the uninstall, then re-queue the install once the remove
        # task finishes (see on_conflict_uninstall_finished).
        self._task_manager.remove(pkg)
        self._pending_reinstall = pkg
        if self._conflict_conn is None:
            self._conflict_conn = self._task_manager.connect(
                'task-finished', self.on_conflict_uninstall_finished
            )

    def on_conflict_uninstall_finished(self, mgr, task):
        from .task_manager import TaskOperation, TaskStatus
        pkg = self._pending_reinstall
        if not pkg or task.package is not pkg or task.operation != TaskOperation.REMOVE:
            return
        self._pending_reinstall = None
        if task.status == TaskStatus.COMPLETED:
            self._task_manager.install(pkg)
        else:
            self._toast_overlay.add_toast(Adw.Toast.new(
                _('Could not uninstall {name} — tap switch cancelled').format(name=pkg.name)
            ))
