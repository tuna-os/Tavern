# tap_choice_dialog.py - Render the router's qualified tap choices
# SPDX-License-Identifier: GPL-3.0-or-later

import gettext

from gi.repository import Adw, Gtk

_ = gettext.gettext


def show_tap_choice(parent, package, options, on_selected):
    """Present choices and return the selected qualified name to the router."""
    dialog = Adw.AlertDialog()
    dialog.set_heading(_('Choose a Tap'))
    dialog.set_body(
        _('"{name}" is available from multiple taps.\nChoose which one to install from:')
        .format(name=package.display_name or package.name)
    )
    dialog.add_response('cancel', _('Cancel'))
    dialog.set_close_response('cancel')

    listbox = Gtk.ListBox()
    listbox.add_css_class('boxed-list')
    listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
    listbox.set_margin_top(8)
    for qualified in options:
        parts = qualified.rsplit('/', 1)
        tap_name = parts[0] if len(parts) == 2 else qualified
        row = Adw.ActionRow()
        row.set_title(qualified)
        row.set_subtitle(_('from tap: {tap}').format(tap=tap_name))
        row._qualified = qualified
        listbox.append(row)

    first = listbox.get_row_at_index(0)
    if first:
        listbox.select_row(first)
    dialog.set_extra_child(listbox)
    dialog.add_response('install', _('Install'))
    dialog.set_response_appearance('install', Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response('install')

    def on_response(_dialog, response):
        if response != 'install':
            return
        row = listbox.get_selected_row()
        if row:
            on_selected(row._qualified)

    dialog.connect('response', on_response)
    dialog.present(parent)
    return dialog
