# deeplink_router.py - Widget-free deep-link and qualified tap routing
# SPDX-License-Identifier: GPL-3.0-or-later

import gettext

from .logging_util import get_logger

_ = gettext.gettext
_log = get_logger('deeplink_router')


class DeepLinkRouter:
    """Resolve targets against the current catalog through injected view actions.

    Partial catalog loads retry pending links silently. The final load attempts
    each remaining target once, reports misses, and opens a pending Brewfile.
    No widgets or signal subscriptions are owned here.
    """

    def __init__(self, backend, *, show_package, select_tap, show_message,
                 open_brewfile, show_tap_choice, install_qualified,
                 package_to_open=None, tap_to_open=None, brewfile_to_open=None):
        self.backend = backend
        self._show_package = show_package
        self._select_tap = select_tap
        self._show_message = show_message
        self._open_brewfile = open_brewfile
        self._show_tap_choice = show_tap_choice
        self._install_qualified = install_qualified
        self.package_to_open = package_to_open
        self.tap_to_open = tap_to_open
        self.brewfile_to_open = brewfile_to_open

    def find_package_by_name(self, package_name):
        target = (package_name or '').strip().lower()
        if not target:
            return None
        for packages in (self.backend.formulae, self.backend.casks):
            for package in packages:
                if (package.name.lower() == target or
                        (package.display_name and package.display_name.lower() == target)):
                    return package
        return None

    def open_package_by_name(self, package_name, show_not_found=True):
        _log.info('Attempting to open package: %s', package_name)
        package = self.find_package_by_name(package_name)
        if package:
            self._show_package(package)
            return True
        if show_not_found:
            _log.warning('Package not found: %s', package_name)
            self._show_message(_('Package "{name}" not found').format(name=package_name))
        return False

    def open_tap_by_name(self, tap_name, show_not_found=True):
        _log.info('Attempting to open tap: %s', tap_name)
        if self._select_tap(tap_name):
            return True
        if show_not_found:
            _log.warning('Tap not found: %s', tap_name)
            self._show_message(_('Tap "{name}" not found').format(name=tap_name))
        return False

    def check_pending(self, final=False):
        if self.package_to_open:
            opened = self.open_package_by_name(self.package_to_open, show_not_found=final)
            if opened or final:
                self.package_to_open = None
        if self.tap_to_open:
            opened = self.open_tap_by_name(self.tap_to_open, show_not_found=final)
            if opened or final:
                self.tap_to_open = None
        if final and self.brewfile_to_open:
            path = self.brewfile_to_open
            self.brewfile_to_open = None
            self._open_brewfile(path)

    def offer_ambiguous_tap_choice(self, task):
        package = task.package
        options = tuple(task.ambiguous_taps)
        if not options:
            return

        def on_selected(qualified):
            if qualified in options:
                _log.info('User chose qualified install: %s', qualified)
                self._install_qualified(package, qualified)

        self._show_tap_choice(package, options, on_selected)
