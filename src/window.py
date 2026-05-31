# window.py - Main application window
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, Gio, GObject
from .backend import BrewBackend
from .task_manager import TaskManager
from .logging_util import get_logger

_log = get_logger('window')

# These imports register the GTypes BEFORE the window template is parsed.
# GTK needs to know about these custom widget types when building the UI.
from .browse_page import TavernBrowsePage      # noqa: F401
from .search_page import TavernSearchPage      # noqa: F401
from .installed_page import TavernInstalledPage  # noqa: F401
from .tap_page import TavernTapPage            # noqa: F401
from .global_progress import TavernGlobalProgress # noqa: F401
from .brewfile_page import TavernBrewfilePage  # noqa: F401
from .updates_card import UpdatesCard  # noqa: F401
from .version_history_dialog import TavernVersionHistoryDialog  # noqa: F401


@Gtk.Template(resource_path='/dev/hanthor/Tavern/window.ui')
class TavernWindow(Adw.ApplicationWindow):
    __gtype_name__ = 'TavernWindow'

    toast_overlay = Gtk.Template.Child()
    content_stack = Gtk.Template.Child()
    browse_page = Gtk.Template.Child()
    search_page = Gtk.Template.Child()
    installed_page = Gtk.Template.Child()
    tap_page = Gtk.Template.Child()
    main_stack = Gtk.Template.Child()
    task_button = Gtk.Template.Child()
    task_indicator_stack = Gtk.Template.Child()
    task_count_label = Gtk.Template.Child()
    navigation_view = Gtk.Template.Child()
    loading_label = Gtk.Template.Child()
    loading_progress_bar = Gtk.Template.Child()

    def __init__(self, package_to_open=None, **kwargs):
        import time
        init_start = time.perf_counter()
        
        super().__init__(**kwargs)
        _log.info('TavernWindow.__init__: starting')

        # Store deeplink target
        self._package_to_open = package_to_open
        self._formulae_loaded = False
        self._casks_loaded = False
        self._brewfile_page_count = 0  # Counter for unique brewfile tab names
        self._open_brewfiles = {}  # page_name -> abs_path
        # Track initial fetching
        self._initial_load_done = False

        # Show loading page
        self.content_stack.set_visible_child_name("loading")

        # Shared backend
        backend_start = time.perf_counter()
        self.backend = BrewBackend()
        self.backend.bind_property('loading_status', self.loading_label, 'label', GObject.BindingFlags.DEFAULT)
        self.backend.bind_property('loading_progress', self.loading_progress_bar, 'fraction', GObject.BindingFlags.DEFAULT)
        backend_time = (time.perf_counter() - backend_start) * 1000
        _log.info('Backend created: %.1f ms', backend_time)

        # Task manager (central operation coordinator)
        task_mgr_start = time.perf_counter()
        self.task_manager = TaskManager(self.backend)
        self.task_manager.connect('task-added', self._on_task_added)
        self.task_manager.connect('task-finished', self._on_task_finished)
        self.task_manager.connect('notify::active-count', self._on_active_count_changed)
        self.task_manager.connect('task-changed', self._on_task_progress_changed)
        task_mgr_time = (time.perf_counter() - task_mgr_start) * 1000
        _log.info('Task manager created: %.1f ms', task_mgr_time)

        # Task button in header bar
        self.task_button.connect('clicked', self._on_task_button_clicked)

        self._outdated_count = 0  # Track current outdated package count
        
        # Wire pages to backend
        pages_start = time.perf_counter()
        self.browse_page.set_backend(self.backend)
        self.search_page.set_backend(self.backend)
        self.installed_page.set_backend_and_manager(self.backend, self.task_manager)
        self.tap_page.set_backend(self.backend)

        # Wire package open signal from pages
        self.browse_page.connect('package-activated', self._on_package_activated)
        self.search_page.connect('package-activated', self._on_package_activated)
        self.installed_page.connect('package-activated', self._on_package_activated)
        self.tap_page.connect('package-activated', self._on_package_activated)
        self.tap_page.connect('tap-operation', self._on_tap_operation)
        self.installed_page.connect('outdated-count-changed', self._on_outdated_count_changed)

        # Wire package install/remove signals from inline tile buttons
        self.browse_page.connect('install-requested', self._on_install_requested)
        self.search_page.connect('install-requested', self._on_install_requested)
        self.installed_page.connect('install-requested', self._on_install_requested)
        self.tap_page.connect('install-requested', self._on_install_requested)

        self.browse_page.connect('remove-requested', self._on_remove_requested)
        self.search_page.connect('remove-requested', self._on_remove_requested)
        self.installed_page.connect('remove-requested', self._on_remove_requested)
        self.tap_page.connect('remove-requested', self._on_remove_requested)
        pages_time = (time.perf_counter() - pages_start) * 1000
        _log.info('Pages wired: %.1f ms', pages_time)

        # Window actions
        actions_start = time.perf_counter()
        refresh_action = Gio.SimpleAction.new('refresh', None)
        refresh_action.connect('activate', self._on_refresh)
        self.add_action(refresh_action)

        open_brewfile_action = Gio.SimpleAction.new('open-brewfile', None)
        open_brewfile_action.connect('activate', self._on_open_brewfile)
        self.add_action(open_brewfile_action)
        self.get_application().set_accels_for_action('win.open-brewfile', ['<Ctrl>o'])
        actions_time = (time.perf_counter() - actions_start) * 1000
        _log.info('Window actions setup: %.1f ms', actions_time)

        # Settings for size persistence
        settings_start = time.perf_counter()
        self._settings = Gio.Settings.new('dev.hanthor.Tavern')
        self.set_default_size(
            self._settings.get_int('window-width'),
            self._settings.get_int('window-height'),
        )
        if self._settings.get_boolean('window-maximized'):
            self.maximize()
        settings_time = (time.perf_counter() - settings_start) * 1000
        _log.info('Settings restored: %.1f ms', settings_time)

        self.connect('close-request', self._on_close)

        # Start loading
        backend_load_start = time.perf_counter()
        self.backend.connect('formulae-loaded', self._on_formulae_loaded)
        self.backend.connect('casks-loaded', self._on_casks_loaded)
        self.backend.connect('installed-loaded', self._on_installed_loaded)
        self.backend.connect('notify::loading', self._on_backend_loading_changed)
        _log.info('Kicking off backend.load_all_async()')
        self.backend.load_all_async()
        backend_load_time = (time.perf_counter() - backend_load_start) * 1000
        _log.info('Backend.load_all_async() started: %.1f ms', backend_load_time)
        
        total_init_time = (time.perf_counter() - init_start) * 1000
        _log.info('TavernWindow.__init__: completed in %.1f ms', total_init_time)

    def _find_package_by_name(self, package_name):
        target = (package_name or '').strip().lower()
        if not target:
            return None

        for pkg in self.backend.formulae:
            if pkg.name.lower() == target or (pkg.display_name and pkg.display_name.lower() == target):
                return pkg

        for pkg in self.backend.casks:
            if pkg.name.lower() == target or (pkg.display_name and pkg.display_name.lower() == target):
                return pkg

        return None

    def open_package_by_name(self, package_name, show_not_found=True):
        """Open a package details page by name (deeplink support)."""
        _log.info('Attempting to open package: %s', package_name)

        package = self._find_package_by_name(package_name)
        if package:
            _log.info('Found package: %s (%s)', package.name, package.pkg_type)
            self._on_package_activated(None, package)
            return True

        if show_not_found:
            _log.warning('Package not found: %s', package_name)
            self.toast_overlay.add_toast(Adw.Toast.new(f'Package "{package_name}" not found'))
        return False


    # ── Task manager signals ─────────────────────────────────────
    def _on_task_added(self, mgr, task):
        _log.info('Task added: %s', task.title)
        op_label = task.title
        self.toast_overlay.add_toast(Adw.Toast.new(f'{op_label}…'))

    def _on_task_finished(self, mgr, task):
        _log.info('Task finished: %s  status=%s', task.title, task.status)
        pkg = task.package
        from .task_manager import TaskStatus
        if task.status == TaskStatus.COMPLETED:
            verb = 'Installed' if task.operation == 'install' else (
                'Removed' if task.operation == 'uninstall' else 'Upgraded'
            )
            self.toast_overlay.add_toast(Adw.Toast.new(
                f'{verb}: {pkg.display_name or pkg.name}'
            ))
        elif task.status == TaskStatus.FAILED:
            if task.ambiguous_taps:
                self._offer_ambiguous_tap_choice(task)
            elif task.conflict_info:
                self._offer_tap_conflict_resolution(task)
            else:
                self.toast_overlay.add_toast(Adw.Toast.new(
                    f'Failed: {pkg.display_name or pkg.name}'
                ))
        # Refresh installed page
        self.installed_page.refresh(self.backend)

    def _on_active_count_changed(self, mgr, pspec):
        count = mgr.active_count
        if count > 0:
            self.task_button.set_tooltip_text(f'{count} task{"s" if count != 1 else ""} running')
            self.task_indicator_stack.set_visible_child_name('active')
            self.task_count_label.set_label(str(count))
            self.task_count_label.set_visible(True)
        else:
            self.task_button.set_tooltip_text('Downloads & Tasks')
            self.task_indicator_stack.set_visible_child_name('idle')
            self.task_count_label.set_visible(False)

    def _on_task_progress_changed(self, mgr, task):
        pass  # progress visible in task panel and tile inline bar

    def _on_task_button_clicked(self, button):
        from .task_panel import TavernTaskPanel
        panel = TavernTaskPanel(task_manager=self.task_manager)
        panel.present(self)

    # ── Package / data signals ───────────────────────────────────
    def _on_formulae_loaded(self, backend, packages):
        _log.info('Formulae loaded: %d packages', len(packages))
        self._formulae_loaded = True
        self.browse_page.populate_formulae(packages)
        self.search_page.set_packages(backend.formulae, backend.casks)
        self._check_deeplink()

    def _on_casks_loaded(self, backend, packages):
        _log.info('Casks loaded: %d packages', len(packages))
        self._casks_loaded = True
        self.browse_page.populate_casks(packages)
        self.search_page.set_packages(backend.formulae, backend.casks)
        self._check_deeplink()

    def _on_installed_loaded(self, backend, _):
        _log.debug('Installed-loaded signal received')

    def _on_outdated_count_changed(self, page, count):
        """Update the Installed tab badge when the outdated count changes."""
        installed_stack_page = self.main_stack.get_page(self.installed_page)
        
        if count == 0:
            installed_stack_page.set_badge_number(0)
            installed_stack_page.set_needs_attention(False)
            return
            
        installed_stack_page.set_badge_number(count)
        installed_stack_page.set_needs_attention(True)
        
        # Show toast notification
        if count > 0:
            msg = f'{count} package{"s" if count != 1 else ""} can be updated'
            toast = Adw.Toast.new(msg)
            self.toast_overlay.add_toast(toast)

    def _on_backend_loading_changed(self, backend, _pspec):
        if backend.loading:
            return

        if not self._initial_load_done:
            self._initial_load_done = True
            # Transition to main content smoothly
            self.content_stack.set_visible_child_name("main")

        if self._package_to_open:
            self.open_package_by_name(self._package_to_open, show_not_found=True)
            self._package_to_open = None

    def _check_deeplink(self):
        """Check if we should open a package from deeplink after data loads."""
        if not self._package_to_open:
            return

        if self.open_package_by_name(self._package_to_open, show_not_found=False):
            self._package_to_open = None


    def _on_package_activated(self, page, package):
        _log.debug('Package activated: %s (%s)', package.name, package.pkg_type)
        from .package_details import TavernPackageDetails
        dialog = TavernPackageDetails(
            package=package,
            backend=self.backend,
            task_manager=self.task_manager,
        )
        dialog.connect('package-changed', self._on_package_changed)
        dialog.connect('package-history-requested', self._on_package_history_requested)
        dialog.connect('package-activated', self._on_package_activated)
        self.navigation_view.push(dialog)

    def _on_package_changed(self, dialog, package):
        # Refresh installed page when something is installed/removed
        self.installed_page.refresh(self.backend)

    def _offer_ambiguous_tap_choice(self, task):
        """Show a dialog letting the user pick which tap to install from."""
        pkg = task.package
        options = task.ambiguous_taps  # ['user/tap/name', ...]

        dialog = Adw.AlertDialog()
        dialog.set_heading('Choose a Tap')
        dialog.set_body(
            f'"{pkg.display_name or pkg.name}" is available from multiple taps.\n'
            'Choose which one to install from:'
        )
        dialog.add_response('cancel', 'Cancel')
        dialog.set_close_response('cancel')

        listbox = Gtk.ListBox()
        listbox.add_css_class('boxed-list')
        listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        listbox.set_margin_top(8)

        for qualified in options:
            # Parse tap name from fully-qualified: user/repo/pkg → user/repo
            parts = qualified.rsplit('/', 1)
            tap_name = parts[0] if len(parts) == 2 else qualified
            row = Adw.ActionRow()
            row.set_title(qualified)
            row.set_subtitle(f'from tap: {tap_name}')
            row._qualified = qualified
            listbox.append(row)

        # Select first row by default
        first = listbox.get_row_at_index(0)
        if first:
            listbox.select_row(first)

        dialog.set_extra_child(listbox)
        dialog.add_response('install', 'Install')
        dialog.set_response_appearance('install', Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response('install')
        dialog.connect('response', self._on_ambiguous_tap_response, listbox, pkg)
        dialog.present(self)

    def _on_ambiguous_tap_response(self, dialog, response, listbox, pkg):
        if response != 'install':
            return
        row = listbox.get_selected_row()
        if not row:
            return
        qualified = getattr(row, '_qualified', None)
        if not qualified:
            return
        _log.info('User chose qualified install: %s', qualified)
        self.task_manager.install_qualified(pkg, qualified)

    def _offer_tap_conflict_resolution(self, task):
        """Show a dialog offering to switch taps when a multi-tap conflict occurs."""
        pkg = task.package
        info = task.conflict_info
        installed_tap = info['installed_tap']
        target_tap    = info['target_tap']
        is_core = target_tap in ('homebrew/core', 'homebrew/cask')

        dialog = Adw.AlertDialog()
        dialog.set_heading('Tap Conflict')
        dialog.set_body(
            f'"{pkg.display_name or pkg.name}" is already installed from the '
            f'{installed_tap} tap.\n\n'
            + (
                f'Would you like to uninstall it from {installed_tap} and reinstall '
                f'from {target_tap}?'
                if is_core else
                f'Formulae with the same name from different taps cannot both be installed.'
            )
        )
        dialog.add_response('cancel', 'Cancel')
        if is_core:
            dialog.add_response('switch', f'Switch to {target_tap}')
            dialog.set_response_appearance('switch', Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')
        dialog.connect('response', self._on_conflict_resolution, task)
        dialog.present(self)

    def _on_conflict_resolution(self, dialog, response, task):
        if response != 'switch':
            return
        pkg = task.package
        _log.info('Switching tap for %s: uninstall then reinstall', pkg.name)
        # Run uninstall then re-queue install
        def after_uninstall(success, _msg):
            if success:
                self.task_manager.install(pkg)
            else:
                self.toast_overlay.add_toast(Adw.Toast.new(
                    f'Failed to uninstall {pkg.name} for tap switch'
                ))
        self.task_manager.remove(pkg)
        # We can't easily chain after remove via task_manager signals here,
        # so use the backend directly for the uninstall + then install
        # Actually re-queue properly via task_manager signal
        self._pending_reinstall = pkg
        if not hasattr(self, '_conflict_conn'):
            self._conflict_conn = self.task_manager.connect(
                'task-finished', self._on_conflict_uninstall_finished
            )

    def _on_conflict_uninstall_finished(self, mgr, task):
        from .task_manager import TaskOperation, TaskStatus
        pkg = getattr(self, '_pending_reinstall', None)
        if not pkg or task.package is not pkg or task.operation != TaskOperation.REMOVE:
            return
        self._pending_reinstall = None
        if task.status == TaskStatus.COMPLETED:
            self.task_manager.install(pkg)
        else:
            self.toast_overlay.add_toast(Adw.Toast.new(
                f'Could not uninstall {pkg.name} — tap switch cancelled'
            ))

    def _on_tap_operation(self, page, message):
        self.toast_overlay.add_toast(Adw.Toast.new(message))

    def _on_install_requested(self, page, package):
        _log.info('Install requested from page: %s (%s)', package.name, package.pkg_type)
        self.task_manager.install(package)

    def _on_remove_requested(self, page, package):
        _log.info('Remove requested from page: %s (%s)', package.name, package.pkg_type)
        self.task_manager.remove(package)

    def _on_package_history_requested(self, card, package):
        """Open version history dialog for a package."""
        _log.debug('Package history requested: %s', package.name)
        version_dialog = TavernVersionHistoryDialog(
            package=package,
            backend=self.backend,
        )
        version_dialog.connect('pin-version', self._on_pin_version_requested)
        self.navigation_view.push(version_dialog)

    def _on_pin_version_requested(self, dialog, version):
        """Handle version pinning request (stretch goal feature)."""
        _log.info('Pin version requested: %s (not yet implemented)', version)
        # TODO: Implement version pinning
        # This would store preference and prevent upgrades

    def _on_refresh(self, action, param):
        _log.info('Manual refresh triggered')
        self.browse_page.set_loading()
        self.backend.load_all_async()
        self.toast_overlay.add_toast(Adw.Toast.new('Refreshing package list…'))

    def _on_open_brewfile(self, action, param):
        _log.info('Open Brewfile action triggered')
        from gi.repository import Gtk
        
        # Create file filter for .Brewfile files
        filter_brewfile = Gtk.FileFilter()
        filter_brewfile.set_name('Brewfile')
        filter_brewfile.add_pattern('*.Brewfile')
        filter_brewfile.add_pattern('Brewfile')
        
        filter_all = Gtk.FileFilter()
        filter_all.set_name('All files')
        filter_all.add_pattern('*')
        
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_brewfile)
        filters.append(filter_all)
        
        # Create and configure file dialog
        dialog = Gtk.FileDialog()
        dialog.set_title('Open Brewfile')
        dialog.set_filters(filters)
        dialog.set_default_filter(filter_brewfile)
        
        # Suggest the ublue-os brewfile directory if it exists
        import os
        default_path = '/usr/share/ublue-os/homebrew'
        if os.path.exists(default_path):
            initial_folder = Gio.File.new_for_path(default_path)
            dialog.set_initial_folder(initial_folder)
        
        # Open dialog and handle response
        dialog.open(self, None, self._on_brewfile_selected)

    def _on_brewfile_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                path = file.get_path()
                _log.info('User selected Brewfile: %s', path)
                self.open_brewfile(path)
        except Exception as e:
            if 'dismissed' not in str(e).lower():
                _log.error('Error opening Brewfile: %s', e)
                self.toast_overlay.add_toast(Adw.Toast.new('Failed to open Brewfile'))

    def open_brewfile(self, path):
        """Open a Brewfile as a new tab in the main window."""
        import os
        
        _log.info('open_brewfile called with path: %s', path)
        
        # Normalize the path for consistent comparison
        abs_path = os.path.abspath(path)
        
        # Check if this Brewfile is already open
        for page_name, brewfile_path in self._open_brewfiles.items():
            if os.path.abspath(brewfile_path) == abs_path:
                _log.info('Brewfile already open: %s', abs_path)
                self.main_stack.set_visible_child_name(page_name)
                self.toast_overlay.add_toast(Adw.Toast.new(f'Already viewing {os.path.basename(path)}'))
                return
        
        # Extract filename for tab title
        filename = os.path.basename(path)
        # Remove .Brewfile extension
        if filename.endswith('.Brewfile'):
            title = filename[:-9]  # Remove '.Brewfile'
        elif filename == 'Brewfile':
            title = 'Brewfile'
        else:
            title = filename
        
        # Capitalize first letter
        title = title.capitalize()
        
        # Create brewfile page
        from .brewfile_page import TavernBrewfilePage
        brewfile_page = TavernBrewfilePage()
        brewfile_page.set_backend_and_manager(self.backend, self.task_manager)
        
        # Connect signals
        brewfile_page.connect('package-activated', self._on_package_activated)
        brewfile_page.connect('install-requested', self._on_install_requested)
        
        # Add as a new tab with a unique name
        self._brewfile_page_count += 1
        page_name = f'brewfile_{self._brewfile_page_count}'
        
        # Track this Brewfile
        self._open_brewfiles[page_name] = abs_path
        
        # Add page to stack
        stack_page = self.main_stack.add_titled(
            brewfile_page,
            page_name,
            title
        )
        
        # Switch to the new tab
        self.main_stack.set_visible_child_name(page_name)
        
        # Load the brewfile
        _log.info('Calling load_brewfile for: %s', path)
        brewfile_page.load_brewfile(path)
        
        _log.info('Added Brewfile tab: %s', title)

    def _on_close(self, *args):
        w, h = self.get_default_size()
        self._settings.set_int('window-width', w)
        self._settings.set_int('window-height', h)
        self._settings.set_boolean('window-maximized', self.is_maximized())
