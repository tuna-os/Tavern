"""Literal command previews; execution requires an explicit confirmation."""
# SPDX-License-Identifier: GPL-3.0-or-later

import gettext
import shlex
import threading
from gi.repository import Adw, GLib, Gtk
from .brew_commands import run_read, transcript

_ = gettext.gettext


def text_view(text=''):
    view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                        wrap_mode=Gtk.WrapMode.WORD_CHAR,
                        top_margin=12, bottom_margin=12, left_margin=12, right_margin=12)
    view.get_buffer().set_text(text)
    scroll = Gtk.ScrolledWindow(min_content_height=200, max_content_height=420,
                               propagate_natural_height=True, child=view,
                               hscrollbar_policy=Gtk.PolicyType.NEVER)
    return scroll, view


def show_command(parent, title, description, *, args=None, text='', confirm=None,
                 confirm_label=None, destructive=False, cancelled=None, runner=run_read,
                 allow_legacy_install=False):
    """Run only the supplied preview argv; never interpret output as commands."""
    dialog = Adw.AlertDialog(heading=title, body=description)
    dialog.add_response('cancel', _('Cancel') if confirm else _('Close'))
    dialog.set_close_response('cancel')
    dialog.set_default_response('cancel')
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    scroll, view = text_view(text or (_('Loading…') if args is not None else _('No output yet')))
    box.append(scroll)
    copy = Gtk.Button(label=_('Copy Output'), halign=Gtk.Align.END)
    copy.connect('clicked', lambda _b: parent.get_clipboard().set(
        view.get_buffer().get_text(*view.get_buffer().get_bounds(), False)))
    box.append(copy)
    dialog.set_extra_child(box)
    if confirm:
        dialog.add_response('confirm', confirm_label or _('Continue'))
        dialog.set_response_appearance('confirm', Adw.ResponseAppearance.DESTRUCTIVE
                                       if destructive else Adw.ResponseAppearance.SUGGESTED)
        dialog.set_response_enabled('confirm', args is None)
    alive = [True]

    def response(_dialog, name):
        if not alive[0]:
            return
        alive[0] = False
        if name == 'confirm' and confirm and dialog.get_response_enabled('confirm'):
            confirm()
        elif cancelled:
            cancelled()

    dialog.connect('response', response)
    dialog.present(parent)
    if args is not None:
        def complete(output, success, legacy=False):
            if alive[0]:
                view.get_buffer().set_text('$ brew ' + shlex.join(args) + '\n\n' + output)
                if confirm:
                    dialog.set_response_enabled('confirm', success)
                    if legacy:
                        dialog.set_response_label('confirm', _('Install Without Preview'))
            return False

        def worker():
            legacy = False
            try:
                result = runner(args)
                output = transcript(result)
                success = result.returncode == 0
                legacy = allow_legacy_install and not success and any(
                    message in output.lower() for message in
                    ('invalid option: --dry-run', 'unknown option: --dry-run'))
                if legacy:
                    success = True
                    output += '\n\n' + _('This Homebrew version cannot preview installation. '
                                           'Update Homebrew for previews, or explicitly install without one.')
                if not success:
                    output += '\n\n' + _('Preview failed; nothing has been queued.')
            except Exception as error:
                output, success = str(error), False
            GLib.idle_add(complete, output, success, legacy)

        threading.Thread(target=worker, daemon=True, name='tavern-preview').start()
    return dialog
