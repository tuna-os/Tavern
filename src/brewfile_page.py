# brewfile_page.py - Page for displaying Brewfile contents
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, GObject, GLib
import subprocess
import time
import threading
import gettext
from concurrent.futures import ThreadPoolExecutor, as_completed
from .backend import Package
from .package_tile import TavernPackageTile
from .logging_util import get_logger, log_timing
from .brewfile_plan import build_plan
from .brewfile_document import BrewfileDocument
from .command_dialog import show_command

_ = gettext.gettext

_log = get_logger('brewfile_page')


@Gtk.Template(resource_path='/org.tunaos.tavern/brewfile-page.ui')
class TavernBrewfilePage(Adw.Bin):
    __gtype_name__ = 'TavernBrewfilePage'

    __gsignals__ = {
        'package-activated': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'install-requested': (GObject.SignalFlags.RUN_LAST, None, (object,)),
    }

    brewfile_stack = Gtk.Template.Child()
    taps_section = Gtk.Template.Child()
    taps_flow = Gtk.Template.Child()
    formulae_section = Gtk.Template.Child()
    formulae_flow = Gtk.Template.Child()
    casks_section = Gtk.Template.Child()
    casks_flow = Gtk.Template.Child()
    flatpaks_section = Gtk.Template.Child()
    flatpaks_flow = Gtk.Template.Child()
    install_all_button = Gtk.Template.Child()
    remove_all_button = Gtk.Template.Child()
    source_button = Gtk.Template.Child()
    deps_button = Gtk.Template.Child()
    source_notice = Gtk.Template.Child()
    extra_entries_label = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.backend = None
        self.task_manager = None
        self._brewfile_path = None
        self._document = None
        self._default_notice = self.source_notice.get_label()
        self.parsed_data = None
        self._packages = []
        self._flatpak_errors = {}
        self._cask_errors = {}
        self._tile_map = {}  # Maps package name -> (tile, package) for lazy icon loading
        self._flatpak_error_lock = threading.Lock()
        self._cask_error_lock = threading.Lock()
        
        # Connect button signals
        self.install_all_button.connect('clicked', self._on_install_all_clicked)
        self.remove_all_button.connect('clicked', self._on_remove_all_clicked)
        self.source_button.connect('clicked', self._show_source)
        self.deps_button.connect('clicked', self._show_dependencies)

    def set_backend_and_manager(self, backend, task_manager):
        """Set the backend and task manager after widget creation."""  
        self.backend = backend
        self.task_manager = task_manager

    def load_brewfile(self, path):
        """Load and display a Brewfile with overall timing."""
        _log.info('=' * 70)
        _log.info('Loading Brewfile: %s', path)
        _log.info('=' * 70)
        self._brewfile_path = path
        self._packages = []
        self._tile_map = {}
        self.source_notice.set_label(self._default_notice)
        try:
            self._document = BrewfileDocument.read(path)
        except (OSError, UnicodeError) as error:
            self._document = None
            self.parsed_data = None
            self.source_notice.set_label(str(error))
            self.brewfile_stack.set_visible_child_name('content')
            return
        self.extra_entries_label.set_label('\n'.join(
            f'{kind}: {name}' for kind, name in self._document.extra_entries))
        
        overall_start = time.perf_counter()
        self.brewfile_stack.set_visible_child_name('loading')
        self._flatpak_errors = {}
        self._cask_errors = {}
        
        # Parse the brewfile
        self.parsed_data = self.backend.parse_brewfile(path)
        
        # Display tap declarations without executing the Brewfile or adding taps.
        self._process_taps()
        
        # Load packages in a thread to avoid blocking UI
        import threading
        
        def load_and_log():
            self._load_packages_thread()
            overall_elapsed = (time.perf_counter() - overall_start) * 1000
            _log.info('=' * 70)
            _log.info('TOTAL BREWFILE LOAD TIME: %.1f ms', overall_elapsed)
            _log.info('=' * 70)
        
        thread = threading.Thread(target=load_and_log, daemon=True)
        thread.start()

    def _process_taps(self):
        """Render declarations only. Reading a file must never add its taps."""
        taps = (self.parsed_data or {}).get('taps', [])
        self.taps_section.set_visible(bool(taps))
        while child := self.taps_flow.get_first_child():
            self.taps_flow.remove(child)
        for entry in taps:
            name = entry['name'] if isinstance(entry, dict) else entry
            label = Gtk.Label(label=name, margin_start=8, margin_end=8,
                              margin_top=6, margin_bottom=6)
            label.set_tooltip_text(_('Declared in Brewfile; not added by opening this file'))
            self.taps_flow.append(label)
    def _load_packages_thread(self):
        """Load packages with lazy loading: show names immediately, fetch details async."""
        import time
        thread_start = time.perf_counter()
        
        try:
            if not self.parsed_data:
                _log.warning('No parsed data available')
                GLib.idle_add(self._populate_tiles, [], [], [])
                return
            
            # PHASE 1: Create placeholder packages with just names - INSTANT display
            formulae_placeholders = []
            casks_placeholders = []
            flatpak_placeholders = []
            
            # Sort alphabetically for better UX
            sorted_formulae = sorted(self.parsed_data.get('formulae', []))
            sorted_casks = sorted(self.parsed_data.get('casks', []))
            sorted_flatpaks = sorted(self.parsed_data.get('flatpaks', []))
            
            _log.info('Creating placeholders: %d formulae, %d casks, %d flatpaks', 
                     len(sorted_formulae), len(sorted_casks), len(sorted_flatpaks))
            
            # Create minimal placeholder packages
            for formula_name in sorted_formulae:
                pkg = Package(data={'name': formula_name, 'desc': ''}, pkg_type='formula')
                formulae_placeholders.append(pkg)
                self._packages.append(pkg)
            
            for cask_name in sorted_casks:
                pkg = Package(data={'token': cask_name, 'name': [cask_name], 'desc': ''}, pkg_type='cask')
                casks_placeholders.append(pkg)
                self._packages.append(pkg)
            
            for app_id in sorted_flatpaks:
                pkg = Package(data={'id': app_id, 'name': app_id, 'summary': ''}, pkg_type='flatpak')
                flatpak_placeholders.append(pkg)
                self._packages.append(pkg)
            
            placeholder_time = (time.perf_counter() - thread_start) * 1000
            _log.info('Placeholders created in %.1f ms - displaying UI now', placeholder_time)
            
            # PHASE 2: Show UI immediately with placeholders
            GLib.idle_add(self._populate_tiles, formulae_placeholders, casks_placeholders, flatpak_placeholders)
            
            # PHASE 3: Fetch metadata and icons asynchronously in background
            _log.info('Starting lazy metadata and icon loading')
            self._lazy_load_metadata(
                sorted_formulae, formulae_placeholders, 'formula',
                sorted_casks, casks_placeholders, 'cask',
                sorted_flatpaks, flatpak_placeholders, 'flatpak'
            )
            
            total_time = (time.perf_counter() - thread_start) * 1000
            _log.info('UI displayed + background loading started in %.1f ms', total_time)
            
        except Exception as e:
            _log.error('FATAL ERROR in _load_packages_thread: %s', e, exc_info=True)
            GLib.idle_add(self._populate_tiles, [], [], [])
    
    def _lazy_load_metadata(self, formulae_names, formulae_pkgs, formula_type,
                            casks_names, casks_pkgs, cask_type,
                            flatpaks_names, flatpaks_pkgs, flatpak_type):
        """Lazy load metadata with strict phase order and parallel workers per phase."""
        import time
        
        def load_metadata_for_package(name, pkg, pkg_type):
            """Fetch full metadata and update the package object."""
            try:
                start = time.perf_counter()
                
                if pkg_type == 'flatpak':
                    full_pkg = self._get_or_fetch_flatpak(name)
                else:
                    full_pkg = self._get_or_fetch_package(name, pkg_type)
                
                if full_pkg:
                    # Update the placeholder package with full data
                    pkg.set_property('name', full_pkg.name)
                    pkg.set_property('full-name', full_pkg.full_name)
                    pkg.set_property('description', full_pkg.description)
                    pkg.set_property('homepage', full_pkg.homepage)
                    pkg.set_property('version', full_pkg.version)
                    pkg.set_property('display_name', full_pkg.display_name)
                    if hasattr(full_pkg, 'icon_url'):
                        pkg.set_property('icon_url', full_pkg.icon_url)
                    
                    elapsed = (time.perf_counter() - start) * 1000
                    _log.debug('Lazy loaded %s (%s): %.1f ms', name, pkg_type, elapsed)
                    
                    flatpak_error = None
                    if pkg_type == 'flatpak':
                        with self._flatpak_error_lock:
                            flatpak_error = self._flatpak_errors.get(name)

                    if flatpak_error:
                        GLib.idle_add(self._mark_flatpak_failed, name, flatpak_error)

                    # NOW load the icon for this package
                    if name in self._tile_map and not flatpak_error:
                        tile, _ = self._tile_map[name]
                        GLib.idle_add(self._load_tile_icon, tile, pkg)
                    
                    return True
                else:
                    _log.warning('Failed to lazy load %s', name)
                    return False
            except Exception as e:
                _log.error('Error lazy loading %s: %s', name, e)
                return False
        
        formula_items = [(name, pkg, 'formula') for name, pkg in zip(formulae_names, formulae_pkgs)]
        cask_items = [(name, pkg, 'cask') for name, pkg in zip(casks_names, casks_pkgs)]
        flatpak_items = [(app_id, pkg, 'flatpak') for app_id, pkg in zip(flatpaks_names, flatpaks_pkgs)]

        all_total = len(formula_items) + len(cask_items) + len(flatpak_items)
        _log.info('Starting package metadata phases: formula -> cask -> flatpak')

        loaded = 0
        failed = 0

        def run_phase(phase_name, items):
            nonlocal loaded, failed
            if not items:
                _log.info('Phase %s: no items', phase_name)
                return

            _log.info('Phase %s: starting %d items with 10 workers', phase_name, len(items))
            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_item = {
                    executor.submit(load_metadata_for_package, name, pkg, pkg_type): (name, pkg_type)
                    for name, pkg, pkg_type in items
                }

                phase_done = 0
                phase_loaded = 0
                phase_failed = 0
                for future in as_completed(future_to_item):
                    name, _ = future_to_item[future]
                    try:
                        success = future.result()
                        if success:
                            loaded += 1
                            phase_loaded += 1
                        else:
                            failed += 1
                            phase_failed += 1
                    except Exception as e:
                        failed += 1
                        phase_failed += 1
                        _log.error('Exception loading %s in phase %s: %s', name, phase_name, e)

                    phase_done += 1
                    total_done = loaded + failed
                    if total_done % 10 == 0 or phase_done == len(items):
                        _log.info(
                            'Lazy load progress: %d/%d complete (%d succeeded, %d failed)',
                            total_done,
                            all_total,
                            loaded,
                            failed,
                        )

            _log.info(
                'Phase %s complete: %d/%d succeeded, %d failed',
                phase_name,
                phase_loaded,
                len(items),
                phase_failed,
            )

        run_phase('formula', formula_items)
        run_phase('cask', cask_items)
        run_phase('flatpak', flatpak_items)

        _log.info(
            'Ordered lazy loading complete: %d loaded, %d failed out of %d total',
            loaded,
            failed,
            all_total,
        )

    def _mark_flatpak_failed(self, app_id, error_message):
        """Move failed flatpak tile to bottom, gray it out, and set error tooltip."""
        if app_id not in self._tile_map:
            return False

        tile, _ = self._tile_map[app_id]
        if not tile:
            return False

        tile.add_css_class('flatpak-failed')
        tile.set_tooltip_text(error_message)

        try:
            self.flatpaks_flow.remove(tile)
            self.flatpaks_flow.append(tile)
        except Exception as e:
            _log.debug('Could not reorder failed flatpak tile %s: %s', app_id, e)

        return False

    def _populate_tiles(self, formulae, casks, flatpaks):
        """Populate tiles on the main thread - icons loaded lazily later."""
        # Store tile references for lazy icon loading
        self._tile_map = {}
        
        if formulae:
            self.formulae_section.set_visible(True)
            for pkg in formulae:
                tile = TavernPackageTile(package=pkg)
                tile.connect('activated', self._on_tile_clicked)
                tile.connect('install-requested', self._on_tile_install_requested)
                # DON'T load icons yet - will be done after metadata fetches
                self._tile_map[pkg.name] = (tile, pkg)
                self.formulae_flow.append(tile)
        
        if casks:
            self.casks_section.set_visible(True)
            for pkg in casks:
                tile = TavernPackageTile(package=pkg)
                tile.connect('activated', self._on_tile_clicked)
                tile.connect('install-requested', self._on_tile_install_requested)
                # DON'T load icons yet
                self._tile_map[pkg.name] = (tile, pkg)
                self.casks_flow.append(tile)

        if flatpaks:
            self.flatpaks_section.set_visible(True)
            for pkg in flatpaks:
                tile = TavernPackageTile(package=pkg)
                tile.connect('activated', self._on_tile_clicked)
                tile.connect('install-requested', self._on_tile_install_requested)
                # DON'T load icons yet
                self._tile_map[pkg.name] = (tile, pkg)
                self.flatpaks_flow.append(tile)
        
        _log.info('Finished populating %d tiles (icons loading in background)', len(self._packages))
        self.brewfile_stack.set_visible_child_name('content')
        return False

    def _get_or_fetch_flatpak(self, app_id):
        """Fetch flatpak metadata from Flathub appstream with graceful fallback."""
        _log.info('Fetching flatpak metadata for %s', app_id)
        try:
            appstream = self.backend.get_flatpak_info(app_id)
            if appstream:
                with self._flatpak_error_lock:
                    self._flatpak_errors.pop(app_id, None)
                _log.debug('Successfully fetched flatpak metadata for %s', app_id)
                return Package(data=appstream, pkg_type='flatpak')
            else:
                with self._flatpak_error_lock:
                    self._flatpak_errors[app_id] = 'Metadata not found on Flathub for this app ID.'
                _log.warning('Flathub API returned empty result for flatpak %s (may not exist)', app_id)
        except Exception as e:
            with self._flatpak_error_lock:
                self._flatpak_errors[app_id] = str(e)
            _log.warning('Failed to fetch flatpak metadata for %s: %s (using fallback)', app_id, e)

        # Create package with Flathub fallback info
        _log.info('Creating fallback package for flatpak %s with Flathub link', app_id)
        return Package(
            data={
                'id': app_id,
                'name': app_id,
                'summary': 'Flatpak application from Brewfile',
                'urls': {'homepage': f'https://flathub.org/apps/{app_id}'},
            },
            pkg_type='flatpak',
        )

    def _get_or_fetch_package(self, name, pkg_type):
        """Get package from backend or fetch info with graceful fallback."""
        pkgs = self.backend.formulae if pkg_type == 'formula' else self.backend.casks
        
        # Try to find in loaded packages
        for p in pkgs:
            if p.name == name or p.full_name == name:
                if pkg_type == 'cask':
                    with self._cask_error_lock:
                        self._cask_errors.pop(name, None)
                _log.debug('Found %s in cache', name)
                return p
        
        # Not found - fetch info for this specific package
        _log.info('Package %s not in cache, fetching details', name)
        installed_set = self.backend.installed_names(pkg_type)
        try:
            pkg_info = self.backend.get_package_info(name, pkg_type)
            
            if pkg_info:
                if pkg_type == 'cask':
                    with self._cask_error_lock:
                        self._cask_errors.pop(name, None)
                _log.info('Successfully fetched info for %s', name)
                return Package(data=pkg_info, pkg_type=pkg_type, installed_set=installed_set)
            else:
                if pkg_type == 'cask':
                    with self._cask_error_lock:
                        self._cask_errors[name] = 'Cask metadata not found from Homebrew API.'
                _log.warning('Package %s returned no info (may not exist or be from unfetched tap)', name)
        except Exception as e:
            if pkg_type == 'cask':
                with self._cask_error_lock:
                    self._cask_errors[name] = str(e)
            _log.error('Error fetching package info for %s: %s', name, e)
        
        # Create a graceful fallback package with helpful information
        _log.info('Creating fallback package for %s (from Brewfile)', name)
        fallback_data = {
            'name': name,
            'desc': 'Package from Brewfile (details not available)',
            'homepage': f'https://brew.sh',  # Generic Homebrew link
        }
        if pkg_type == 'cask':
            fallback_data = {
                'token': name,
                'full_token': name,
                'name': [name],
                'desc': 'Cask from Brewfile (details not available)',
                'homepage': 'https://brew.sh',
                'version': '',
            }
        return Package(data=fallback_data, 
                      pkg_type=pkg_type, installed_set=installed_set)

    def _load_tile_icon(self, tile, package):
        """Load icon for a package tile with profiling."""
        icon_start = time.perf_counter()
        
        def on_icon_fetched(pkg, pixbuf):
            elapsed_ms = (time.perf_counter() - icon_start) * 1000
            if pixbuf:
                tile.set_icon_pixbuf(pixbuf)
                _log.debug('Icon loaded for %s: %.1f ms', pkg.name, elapsed_ms)
            else:
                _log.debug('No icon found for %s: %.1f ms', pkg.name, elapsed_ms)
        
        self.backend.fetch_icon_async(package, on_icon_fetched)

    def _on_tile_clicked(self, tile):
        pkg = tile.get_package()
        if pkg:
            if pkg.pkg_type == 'flatpak':
                self._open_flatpak_in_bazaar(pkg)
                return
            self.emit('package-activated', pkg)

    def _on_tile_install_requested(self, tile):
        pkg = tile.get_package()
        if pkg:
            self.emit('install-requested', pkg)

    def _show_source(self, _button):
        if self._document is not None:
            show_command(self.get_root(), _('Complete Brewfile'),
                         _('The tiles do not evaluate Ruby conditions. This is the full source.'),
                         text=self._document.source)

    def _show_dependencies(self, _button):
        document = self._document
        if document is None:
            return

        def preview():
            try:
                document.verify()
            except (OSError, ValueError) as error:
                show_command(self.get_root(), _('Brewfile Changed'), str(error), text=str(error))
                return
            show_command(self.get_root(), _('Brewfile Dependencies'),
                         _('Homebrew dependencies only; this is not a complete plan for other package managers.'),
                         args=document.deps_args, runner=read_dependencies)

        def read_dependencies(args):
            from .brew_commands import run_read
            document.verify()
            return run_read(args)

        show_command(self.get_root(), _('Trust This Brewfile?'),
                     _('Homebrew evaluates Brewfiles as Ruby, even when listing dependencies. '
                       'Only continue if you trust the complete file and any files it loads.'),
                     text=document.source, confirm=preview, confirm_label=_('Show Dependencies'))

    def _on_install_all_clicked(self, button):
        document = self._document
        if document is None or self.task_manager is None:
            return
        show_command(self.get_root(), _('Install This Brewfile?'),
                     _('Homebrew will execute the complete original Ruby file. Only continue if you '
                       'trust it and any files it loads. All supported entry types and options are '
                       'preserved, including Cargo, uv, npm and editor extensions. Existing packages '
                       'are not upgraded. Metadata lookup failures do not remove entries.'),
                     text=document.source,
                     confirm=lambda: self.task_manager.submit_command(
                         document.install_args, _('Install Brewfile'), preflight=document.verify),
                     confirm_label=_('Install Brewfile'))

    def _on_remove_all_clicked(self, button):
        if not self.parsed_data or self.task_manager is None:
            return
        # Bulk removal only covers Homebrew entries. Do not claim that generic
        # bundle cleanup is the inverse: it removes packages OUTSIDE this file.
        from .brew_commands import validate_name
        plan = build_plan(self.parsed_data)
        formulae, casks = plan.formulae, plan.casks
        if not formulae and not casks:
            return
        for name in (*formulae, *casks):
            validate_name(name)

        def remove():
            if formulae:
                self.task_manager.submit_command(
                    ('uninstall', '--formula', *formulae), _('Remove Brewfile Formulae'))
            if casks:
                self.task_manager.submit_command(
                    ('uninstall', '--cask', *casks), _('Remove Brewfile Casks'))

        show_command(self.get_root(), _('Remove Homebrew Packages?'),
                     _('Only the formulae and casks listed below are removed. '
                       'Taps, Flatpaks, language tools and editor extensions are left unchanged.'),
                     text='\n'.join((*formulae, *casks)), confirm=remove,
                     confirm_label=_('Remove'), destructive=True)
    def _open_flatpak_in_bazaar(self, package):
        """Open a flatpak app id using appstream URI so MIME/xdg routing can launch Bazaar."""
        app_id = package.name
        uri = f'appstream://{app_id}'
        try:
            subprocess.Popen(['xdg-open', uri])
            _log.info('Opened flatpak in Bazaar via URI: %s', uri)
        except Exception as e:
            _log.error('Failed to open flatpak URI %s: %s', uri, e)
