# external_links.py - The only module that hands a URI to the desktop
# SPDX-License-Identifier: GPL-3.0-or-later

"""Open links outside Tavern.

The desktop opens a URI with the application that claims its scheme. Text from
a README, a tap, a Brewfile or command output must not choose that scheme or
the rest of the URI freely, so each function here checks its argument first.
No other module calls a launcher API;
tests/test_dependency_boundaries.py makes sure of this.

Gtk is imported inside the functions that need it: the search provider process
imports this module and does not load GTK.
"""

import subprocess

from gi.repository import Gio

from .flatpak_app_id import is_flatpak_app_id
from .logging_util import get_logger
from .readme_renderer import is_external_link_allowed

_log = get_logger('external_links')


def open_web_link(uri, parent=None):
    """Open an http, https or mailto link. Return False when ``uri`` is not one."""
    if not is_external_link_allowed(uri):
        _log.debug('Did not open a link that is not a web link: %s', uri)
        return False
    from gi.repository import Gtk
    Gtk.UriLauncher.new(uri).launch(parent, None, None, None)
    return True


def web_link_button(uri, label):
    """Return a link button that opens ``uri`` only when it is a web link."""
    from gi.repository import Gtk
    button = Gtk.LinkButton.new_with_label(uri, label)
    button.set_sensitive(is_external_link_allowed(uri))
    button.connect('activate-link', _on_link_button_activated)
    return button


def _on_link_button_activated(button):
    if open_web_link(button.get_uri(), button.get_root()):
        button.set_visited(True)
    # True stops the default handler, which opens a URI of any scheme.
    return True


def open_flatpak_app_page(app_id):
    """Show a Flatpak application in the software center.

    Return False when ``app_id`` is not an application ID.
    """
    if not is_flatpak_app_id(app_id):
        _log.debug('Did not open a software center page for %r', app_id)
        return False
    subprocess.Popen(['xdg-open', f'appstream://{app_id}'])
    return True


def open_brew_link(target):
    """Open ``brew://<target>``, which the desktop gives to Tavern."""
    Gio.AppInfo.launch_default_for_uri(f'brew://{target}', None)
