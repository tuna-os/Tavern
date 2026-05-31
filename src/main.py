# main.py - Entry point for Tavern
# SPDX-License-Identifier: GPL-3.0-or-later

import sys
import os
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gio
from .logging_util import init_logging, get_logger

_log = get_logger('main')

# Load the gresource bundle before importing modules that use Gtk.Template
def _load_resources():
    """Load the compiled resource bundle and Adwaita resources."""
    # Try to load Adwaita resources from Homebrew lib first
    adwaita_paths = [
        os.path.join(os.path.expanduser('~'), '.linuxbrew', 'lib', 'libadwaita-1.so.0'),
        '/home/linuxbrew/.linuxbrew/lib/libadwaita-1.so.0',
        '/usr/lib64/libadwaita-1.so.0',
        '/usr/lib/libadwaita-1.so.0',
    ]
    
    for lib_path in adwaita_paths:
        if os.path.exists(lib_path):
            try:
                # Try to load Adwaita's built-in gresources
                # Some versions embed resources in the library
                glib = __import__('gi.repository.GLib', fromlist=['GLib']).GLib
                # This forces the library to initialize its resources
                import ctypes
                ctypes.CDLL(lib_path, mode=ctypes.RTLD_GLOBAL)
                _log.debug('Loaded Adwaita library: %s', lib_path)
                break
            except Exception as e:
                _log.debug('Failed to load Adwaita library %s: %s', lib_path, e)
    
    # Try multiple possible locations for tavern's resource bundle
    resource_paths = [
        os.path.join(os.path.dirname(__file__), 'tavern.gresource'),  # In-source
        os.path.join(os.path.expanduser('~'), '.local', 'share', 'tavern', 'tavern.gresource'),  # Installed
        '/usr/local/share/tavern/tavern.gresource',  # System install
        '/usr/share/tavern/tavern.gresource',  # System install (distro)
    ]
    
    for path in resource_paths:
        if os.path.exists(path):
            try:
                resources = Gio.Resource.load(path)
                Gio.resources_register(resources)
                _log.debug('Loaded gresource from %s', path)
                return True
            except Exception as e:
                _log.warning('Failed to load gresource from %s: %s', path, e)
    
    _log.warning('Could not find or load gresource bundle')
    return False


def main(version):
    import time
    startup_start = time.perf_counter()
    
    # Initialise logging/profiling subsystem (off by default;
    # set TAVERN_LOG=1 and/or TAVERN_PROFILE=1 to activate).
    init_logging()
    _log.info('=' * 70)
    _log.info('TAVERN DESKTOP STARTUP')
    _log.info('=' * 70)
    _log.info('Starting Tavern  version=%s  python=%s', version, sys.version.split()[0])

    # Load resources before importing modules that use Gtk.Template
    resource_start = time.perf_counter()
    _load_resources()
    resource_time = (time.perf_counter() - resource_start) * 1000
    _log.info('Resources loaded: %.1f ms', resource_time)

    # Now import application after resources are loaded
    import_start = time.perf_counter()
    from .application import TavernApplication
    import_time = (time.perf_counter() - import_start) * 1000
    _log.info('Application module imported: %.1f ms', import_time)

    # Create application
    app_start = time.perf_counter()
    app = TavernApplication(version=version)
    app_time = (time.perf_counter() - app_start) * 1000
    _log.info('Application instance created: %.1f ms', app_time)

    # Run application
    run_start = time.perf_counter()
    _log.info('Running application...')
    result = app.run(sys.argv)
    run_time = (time.perf_counter() - run_start) * 1000
    
    # Total startup time (until window is shown)
    startup_time = (time.perf_counter() - startup_start) * 1000
    _log.info('=' * 70)
    _log.info('STARTUP TIMELINE:')
    _log.info('  Resources loaded:      %.1f ms', resource_time)
    _log.info('  Module imported:       %.1f ms', import_time)
    _log.info('  App instance created:  %.1f ms', app_time)
    _log.info('  App.run() total:       %.1f ms', run_time)
    _log.info('  TOTAL STARTUP:         %.1f ms', startup_time)
    _log.info('=' * 70)
    
    return result
