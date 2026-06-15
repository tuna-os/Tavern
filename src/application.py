# application.py - GtkApplication subclass
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import threading
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gio, GLib, Gtk
from .window import TavernWindow
from .search_provider import TavernSearchProvider
from .logging_util import get_logger

_log = get_logger('application')


class TavernApplication(Adw.Application):
    """The main application singleton class."""

    def __init__(self, version='0.1.0', **kwargs):
        app_id = kwargs.pop('application_id', 'dev.hanthor.Tavern')
        super().__init__(
            application_id=app_id,
            flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
            **kwargs,
        )
        self.version = version
        self._package_to_open = None
        self._tap_to_open = None
        self._brewfile_to_open = None
        
        self._search_provider = None

        self.create_action('quit', lambda *_: self.quit(), ['<primary>q'])
        self.create_action('about', self._on_about_action)

        # Action used by the GNOME Shell search provider to open a package
        show_pkg = Gio.SimpleAction.new('show-package', GLib.VariantType.new('s'))
        show_pkg.connect('activate', self._on_show_package)
        self.add_action(show_pkg)

        _log.debug('TavernApplication created  version=%s', version)

    # ── D-Bus registration (for GNOME Shell search provider) ──────
    def do_dbus_register(self, connection, object_path):
        """Export search provider interface before the app is activated."""
        self._search_provider = TavernSearchProvider(self)
        self._search_provider.export(connection)
        return Gio.Application.do_dbus_register(self, connection, object_path)

    def do_dbus_unregister(self, connection, object_path):
        """Unexport search provider on shutdown."""
        if self._search_provider:
            self._search_provider.unexport()
        Gio.Application.do_dbus_unregister(self, connection, object_path)

    # ── Startup & Background Cache Refresher Worker ─────────────────
    def do_startup(self):
        """Initialize the background service worker once on startup."""
        Adw.Application.do_startup(self)
        self.start_background_refresher()

    def start_background_refresher(self):
        """Start a periodic background worker to keep the package cache fresh."""
        _log.info('Starting periodic background cache refresher worker')
        
        def check_and_refresh():
            # Run in a background thread to avoid blocking the main D-Bus loop
            thread = threading.Thread(target=self._refresh_cache_thread, daemon=True)
            thread.start()
            return True # Keep the GLib timer active
        
        # Check every 2 hours (7200 seconds)
        GLib.timeout_add_seconds(7200, check_and_refresh)
        # Also run once shortly after startup (e.g. after 10 seconds) to ensure fresh cache
        GLib.timeout_add_seconds(10, lambda: threading.Thread(target=self._refresh_cache_thread, daemon=True).start() or False)

    def _refresh_cache_thread(self):
        _log.debug('Background cache refresh check started')
        cache_dir = os.path.join(GLib.get_user_cache_dir(), 'tavern')
        cache_path = os.path.join(cache_dir, 'formulae.json')
        
        # Check if cache is stale (older than 4 hours for background worker)
        needs_refresh = True
        if os.path.exists(cache_path):
            try:
                age = GLib.get_real_time() / 1e6 - os.path.getmtime(cache_path)
                if age < 14400: # 4 hours
                     needs_refresh = False
                     _log.debug('Cache is fresh (age=%.0fs), skipping background refresh', age)
            except Exception as e:
                _log.warning('Failed to check cache age: %s', e)
        
        if needs_refresh:
            _log.info('Cache is stale, performing background refresh of Homebrew metadata...')
            try:
                from .backend import BrewBackend
                backend = BrewBackend()
                backend.refresh_cache_files()
                _log.info('Background cache refresh completed successfully!')
            except Exception as e:
                _log.error('Background cache refresh failed: %s', e)

    # ── Show-package action (search provider deep-link) ──────────
    def _on_show_package(self, action, param):
        """Handle the show-package action from the search provider."""
        pkg_name = param.get_string()
        _log.info('show-package action: %s', pkg_name)
        self._package_to_open = pkg_name
        self.activate()

    def _parse_argument_uri(self, arg):
        """Parse URIs like brew:// or https://formulae.brew.sh/ and extract target."""
        if not arg:
            return None, None

        arg_lower = arg.lower()
        # Handle brew:// scheme
        if arg_lower.startswith('brew://'):
            path = arg[7:] # strip brew://
            if path.lower().startswith('formula/'):
                return 'package', path[8:]
            elif path.lower().startswith('formulae/'):
                return 'package', path[9:]
            elif path.lower().startswith('cask/'):
                return 'package', path[5:]
            elif path.lower().startswith('casks/'):
                return 'package', path[6:]
            elif path.lower().startswith('tap/'):
                return 'tap', path[4:]
            else:
                # Default fallback: treat as package name
                return 'package', path

        # Handle https://formulae.brew.sh/ web URLs
        elif arg_lower.startswith('https://formulae.brew.sh/'):
            path = arg[25:] # strip prefix
            if path.lower().startswith('formula/'):
                name = path[8:].rstrip('/')
                return 'package', name
            elif path.lower().startswith('cask/'):
                name = path[5:].rstrip('/')
                return 'package', name

        return None, None

    def do_command_line(self, command_line):
        """Handle command-line arguments."""
        import sys
        _log.info('do_command_line called with args')
        
        args = sys.argv[1:]
        if command_line:
            args = command_line.get_arguments()[1:]
            
        _log.info('Parsed args for command line: %s', args)
        
        package_name = None
        tap_name = None
        brewfile_path = None

        for i, arg in enumerate(args):
            target_type, target_val = self._parse_argument_uri(arg)
            if target_type == 'package':
                package_name = target_val
            elif target_type == 'tap':
                tap_name = target_val
            elif arg in ('--package', '-p') and i + 1 < len(args):
                package_name = args[i + 1]
            elif arg.startswith('--package='):
                package_name = arg.split('=', 1)[1]
            elif arg in ('--brewfile', '-b') and i + 1 < len(args):
                brewfile_path = args[i + 1]
            elif arg.startswith('--brewfile='):
                brewfile_path = arg.split('=', 1)[1]

        if package_name:
            _log.info('Opening package from command-line: %s', package_name)
            self._package_to_open = package_name

        if tap_name:
            _log.info('Opening tap from command-line: %s', tap_name)
            self._tap_to_open = tap_name

        if brewfile_path:
            _log.info('Opening Brewfile from command-line: %s', brewfile_path)
            self._brewfile_to_open = brewfile_path

        self.activate()
        return 0


    def do_activate(self):
        import time
        activate_start = time.perf_counter()
        
        _log.info('do_activate: called')
        _log.info('do_activate: _package_to_open=%s, _tap_to_open=%s, _brewfile_to_open=%s', 
                  self._package_to_open, self._tap_to_open, self._brewfile_to_open)
        
        win = self.props.active_window
        if not win:
            window_start = time.perf_counter()
            _log.debug('Creating new TavernWindow')
            win = TavernWindow(
                application=self,
                package_to_open=self._package_to_open
            )
            # Apply devel styling (striped titlebar) when running as the
            # development build — mirrors the GNOME convention used by
            # Builder, Nautilus nightly, Bazaar nightly, etc.
            if self.get_application_id().endswith('.Devel'):
                win.add_css_class('devel')
            window_time = (time.perf_counter() - window_start) * 1000
            _log.info('TavernWindow created: %.1f ms', window_time)
            self._package_to_open = None
        else:
            if self._package_to_open:
                win.open_package_by_name(self._package_to_open)
                self._package_to_open = None
            if self._tap_to_open:
                win.open_tap_by_name(self._tap_to_open)
                self._tap_to_open = None
            if self._brewfile_to_open:
                win.open_brewfile(self._brewfile_to_open)
                self._brewfile_to_open = None

        # Load CSS
        css_start = time.perf_counter()
        css_provider = Gtk.CssProvider()
        css_provider.load_from_resource('/dev/hanthor/Tavern/style.css')
        Gtk.StyleContext.add_provider_for_display(
            win.get_display(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        css_time = (time.perf_counter() - css_start) * 1000
        _log.info('CSS loaded and applied: %.1f ms', css_time)

        win.present()
        present_time = (time.perf_counter() - activate_start) * 1000
        _log.info('Window presented: %.1f ms', present_time)

        # Open brewfile if requested
        if self._brewfile_to_open:
            _log.info('do_activate: Opening brewfile: %s', self._brewfile_to_open)
            self._open_brewfile_dialog(win, self._brewfile_to_open)
            self._brewfile_to_open = None

        # Open tap if requested
        if self._tap_to_open:
            if hasattr(win, 'open_tap_by_name'):
                _log.info('do_activate: Opening tap: %s', self._tap_to_open)
                win.open_tap_by_name(self._tap_to_open)
            self._tap_to_open = None
        
        total_activate_time = (time.perf_counter() - activate_start) * 1000
        _log.info('do_activate: completed in %.1f ms', total_activate_time)

    def do_open(self, files, n_files, hint):
        _log.info('do_open called  n_files=%d  hint=%r', n_files, hint)
        self.do_activate()
        win = self.props.active_window
        for gfile in files:
            path = gfile.get_path()
            if path and path.endswith('.Brewfile'):
                _log.info('Opening Brewfile: %s', path)
                win.open_brewfile(path)

    def _open_brewfile_dialog(self, window, path):
        """Open a Brewfile."""
        window.open_brewfile(path)

    def _on_about_action(self, *args):
        about = Adw.AboutDialog(
            application_name='Tavern',
            application_icon='dev.hanthor.Tavern',
            developer_name='James',
            version=self.version,
            developers=['James'],
            copyright='© 2026 James',
            license_type=Gtk.License.GPL_3_0,
            website='https://github.com/hanthor/tavern',
            issue_url='https://github.com/hanthor/tavern/issues',
            comments='A Homebrew App Store for GNOME',
        )
        about.present(self.props.active_window)

    def create_action(self, name, callback, shortcuts=None):
        action = Gio.SimpleAction.new(name, None)
        action.connect('activate', callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f'app.{name}', shortcuts)
