# stats_dialog.py - Dialog showing download statistics
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, GObject
from .logging_util import get_logger

_log = get_logger('stats_dialog')


@Gtk.Template(resource_path='/dev/hanthor/Tavern/stats-dialog.ui')
class TavernStatsDialog(Adw.Dialog):
    __gtype_name__ = 'TavernStatsDialog'

    total_installs_label = Gtk.Template.Child()
    count_30d = Gtk.Template.Child()
    count_90d = Gtk.Template.Child()
    count_365d = Gtk.Template.Child()
    bar_30d = Gtk.Template.Child()
    bar_90d = Gtk.Template.Child()
    bar_365d = Gtk.Template.Child()

    def __init__(self, package, **kwargs):
        super().__init__(**kwargs)
        self._package = package
        self._populate()

    def _format_count(self, count):
        if count >= 1_000_000:
            return f"{count / 1_000_000:.2f}M"
        elif count >= 1000:
            return f"{count / 1000:.2f}K"
        return f"{count:,}"

    def _populate(self):
        pkg = self._package
        if not pkg:
            return

        total_installs = pkg.installs_365d
        
        # Determine the maximum count to scale the progress bars
        max_installs = max(pkg.installs_30d, pkg.installs_90d, pkg.installs_365d)
        
        # Populate labels
        self.count_30d.set_label(self._format_count(pkg.installs_30d))
        self.count_90d.set_label(self._format_count(pkg.installs_90d))
        self.count_365d.set_label(self._format_count(pkg.installs_365d))

        if total_installs <= 0:
            self.total_installs_label.set_label("---")
        else:
            self.total_installs_label.set_label(f"{self._format_count(total_installs)} Total Installs")

        # Set progress bars based on the relative fraction (normalized to the max, which is likely 365d)
        if max_installs > 0:
            self.bar_30d.set_fraction(pkg.installs_30d / max_installs)
            self.bar_90d.set_fraction(pkg.installs_90d / max_installs)
            self.bar_365d.set_fraction(pkg.installs_365d / max_installs)
        else:
            self.bar_30d.set_fraction(0.0)
            self.bar_90d.set_fraction(0.0)
            self.bar_365d.set_fraction(0.0)
