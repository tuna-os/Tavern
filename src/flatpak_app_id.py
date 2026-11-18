# flatpak_app_id.py - The shape of a Flatpak application ID
# SPDX-License-Identifier: GPL-3.0-or-later

"""Check that text is a Flatpak application ID.

A Brewfile, a tap or a README can name a Flatpak. Before Tavern puts that name
in a Flathub request or an ``appstream://`` link, it must be an application ID
and nothing else. The backend and external_links.py both use this check, so
it imports no GTK and opens nothing.
"""

import re

# A Flatpak application ID: three or more elements joined by periods, where an
# element starts with a letter or an underscore.
_FLATPAK_APP_ID = re.compile(r'[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*){2,}')
_FLATPAK_APP_ID_MAX_LENGTH = 255


def is_flatpak_app_id(app_id):
    """True when ``app_id`` has the form of a Flatpak application ID."""
    return (
        isinstance(app_id, str)
        and len(app_id) <= _FLATPAK_APP_ID_MAX_LENGTH
        and _FLATPAK_APP_ID.fullmatch(app_id) is not None
    )
