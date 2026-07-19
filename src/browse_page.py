# browse_page.py - Browse / discover page
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, GObject
from .backend import BrewBackend
from .package_tile import TavernPackageTile, clear_flow
from .logging_util import get_logger

_log = get_logger('browse_page')


# Well-known popular formulae to feature
POPULAR_FORMULAE = [
    'git', 'wget', 'curl', 'node', 'python@3.12', 'ffmpeg', 'htop',
    'vim', 'neovim', 'tmux', 'ripgrep', 'fzf', 'jq', 'bat', 'eza',
    'imagemagick', 'yt-dlp', 'gh', 'go', 'rust', 'php',
]

# Well-known popular casks to feature
POPULAR_CASKS = [
    'firefox', 'google-chrome', 'visual-studio-code', 'vlc', 'iterm2',
    'slack', 'zoom', 'spotify', 'discord', 'rectangle', 'obsidian',
    'warp', 'tableplus', 'postman', 'docker', 'alfred',
]


@Gtk.Template(resource_path='/org.tunaos.tavern/browse-page.ui')
class TavernBrowsePage(Adw.Bin):
    __gtype_name__ = 'TavernBrowsePage'

    __gsignals__ = {
        'package-activated': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'install-requested': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'remove-requested':  (GObject.SignalFlags.RUN_LAST, None, (object,)),
    }

    browse_stack = Gtk.Template.Child()
    popular_flow = Gtk.Template.Child()
    casks_flow = Gtk.Template.Child()
    recent_flow = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._backend = None

    def set_backend(self, backend):
        self._backend = backend

    def set_loading(self):
        self.browse_stack.set_visible_child_name('loading')

    def populate_formulae(self, packages):
        _log.debug('populate_formulae: %d packages', len(packages))
        self._fill_flow(self.popular_flow, packages, POPULAR_FORMULAE)
        self._fill_recent(packages)
        self._maybe_show_content()

    def populate_casks(self, packages):
        _log.debug('populate_casks: %d packages', len(packages))
        self._fill_flow(self.casks_flow, packages, POPULAR_CASKS)
        self._maybe_show_content()

    def _load_tile_icon(self, tile, package):
        """Ask the backend to fetch an icon and push it into the tile when ready."""
        if not self._backend:
            return
        def on_icon_fetched(pkg, pixbuf):
            if pixbuf:
                tile.set_icon_pixbuf(pixbuf)
        self._backend.fetch_icon_async(package, on_icon_fetched)

    def _fill_flow(self, flowbox, packages, preferred_names):
        clear_flow(flowbox)

        # Build name->pkg map
        name_map = {p.name: p for p in packages}

        shown = []
        # First add preferred names in order
        for name in preferred_names:
            if name in name_map:
                shown.append(name_map[name])

        # Fill remaining slots from package list (sorted by name length as lightweight
        # popularity proxy - shorter names tend to be well-known)
        remaining = [p for p in packages if p.name not in {s.name for s in shown}]
        remaining.sort(key=lambda p: len(p.name))
        shown.extend(remaining[: 24 - len(shown)])

        for pkg in shown:
            tile = TavernPackageTile(package=pkg)
            tile.connect('activated', self._on_tile_clicked)
            tile.connect('install-requested', self._on_tile_install_requested)
            tile.connect('remove-requested', self._on_tile_remove_requested)
            self._load_tile_icon(tile, pkg)
            flowbox.append(tile)

    def _fill_recent(self, packages):
        clear_flow(self.recent_flow)
            
        if not packages:
            return
            
        import random
        from datetime import date
        
        # Use today's date as a seed so the "Discover" list changes daily but stays consistent
        rng = random.Random(date.today().toordinal())
        
        # Pick 12 random packages
        selected = rng.sample(packages, min(12, len(packages)))
        
        for pkg in selected:
            tile = TavernPackageTile(package=pkg)
            tile.connect('activated', self._on_tile_clicked)
            tile.connect('install-requested', self._on_tile_install_requested)
            tile.connect('remove-requested', self._on_tile_remove_requested)
            self._load_tile_icon(tile, pkg)
            self.recent_flow.append(tile)


    def _maybe_show_content(self):
        # Show content only when at least one section has tiles
        if self.popular_flow.get_first_child() or self.casks_flow.get_first_child():
            self.browse_stack.set_visible_child_name('content')

    def _on_tile_clicked(self, tile):
        pkg = tile.get_package()
        if pkg:
            self.emit('package-activated', pkg)

    def _on_tile_install_requested(self, tile):
        pkg = tile.get_package()
        if pkg:
            self.emit('install-requested', pkg)

    def _on_tile_remove_requested(self, tile):
        pkg = tile.get_package()
        if pkg:
            self.emit('remove-requested', pkg)
