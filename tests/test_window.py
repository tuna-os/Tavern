# test_window.py
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
import os
import sys
from gi.repository import Gtk, GLib, Gio, Adw
from tavern.application import TavernApplication
from tavern.window import TavernWindow
from tavern.backend import Package, BrewBackend
from tavern.task_manager import TaskManager, TaskStatus

# ─── Mock Gio.Settings ────────────────────────────────────────────────────────

class MockSettings:
    def __init__(self, schema_id):
        self._store = {
            'window-width': 1024,
            'window-height': 768,
            'window-maximized': False,
        }
    def get_int(self, name):
        return self._store[name]
    def get_boolean(self, name):
        return self._store[name]
    def set_int(self, name, value):
        self._store[name] = value
    def set_boolean(self, name, value):
        self._store[name] = value

Gio.Settings = type('Settings', (), {'new': MockSettings})

# ─── Tests ────────────────────────────────────────────────────────────────────

def test_window_workflows(tmp_path, monkeypatch):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    # 1. Mock Gtk/Adw dialogs and transitions to avoid headless display errors
    monkeypatch.setattr(Adw.AlertDialog, 'present', lambda self, parent=None: None)
    monkeypatch.setattr(Adw.NavigationView, 'push', lambda self, child: None)
    
    # Mock TavernTaskPanel, TavernPackageDetails, TavernVersionHistoryDialog
    import tavern.task_panel as tp_mod
    import tavern.package_details as pd_mod
    import tavern.version_history_dialog as vh_mod
    monkeypatch.setattr(tp_mod.TavernTaskPanel, 'present', lambda self, parent=None: None)
    monkeypatch.setattr(pd_mod.TavernPackageDetails, 'connect', lambda *args: 0)
    monkeypatch.setattr(vh_mod.TavernVersionHistoryDialog, 'connect', lambda *args: 0)
    
    # Mock Gtk.FileDialog
    def mock_file_dialog_open(self, parent, cancellable, callback):
        callback(self, object()) # callback immediately
    def mock_file_dialog_open_finish(self, result):
        class MockFile:
            def get_path(self):
                return str(tmp_path / 'imported.Brewfile')
        return MockFile()
    monkeypatch.setattr(Gtk.FileDialog, 'open', mock_file_dialog_open)
    monkeypatch.setattr(Gtk.FileDialog, 'open_finish', mock_file_dialog_open_finish)
    
    # 2. Setup Application and Window
    app = TavernApplication(version="1.0.0", application_id="org.tunaos.tavern.TestWindow")
    app.register(None)
    
    win = TavernWindow(application=app)
    assert win is not None
    backend_reload_calls = []
    monkeypatch.setattr(win.backend, 'load_all_async', lambda: backend_reload_calls.append(True))
    
    # Pre-populate backend with mock packages
    pkg_rg = Package({'name': 'ripgrep', 'desc': 'rg'}, 'formula')
    pkg_fox = Package({'token': 'firefox', 'name': ['Firefox']}, 'cask')
    win.backend._formulae = [pkg_rg]
    win.backend._casks = [pkg_fox]
    
    # 3. Test package lookup and opening methods
    assert win._find_package_by_name('ripgrep') == pkg_rg
    assert win._find_package_by_name('firefox') == pkg_fox
    assert win._find_package_by_name('nonexistent') is None
    
    # Test open_package_by_name
    assert win.open_package_by_name('ripgrep') is True
    assert win.open_package_by_name('nonexistent', show_not_found=True) is False
    
    # 4. Test Task signals
    class MockTask:
        def __init__(self, package, operation='install', status=TaskStatus.COMPLETED):
            self.package = package
            self.operation = operation
            self.status = status
            self.title = 'Mock Task Title'
            self.ambiguous_taps = []
            self.conflict_info = None
            
    # Trigger task-added
    task1 = MockTask(pkg_rg, 'install', TaskStatus.RUNNING)
    win._on_task_added(win.task_manager, task1)
    
    # Trigger task-finished success (install)
    win._on_task_finished(win.task_manager, MockTask(pkg_rg, 'install', TaskStatus.COMPLETED))
    assert backend_reload_calls == [True]
    # Trigger task-finished success (uninstall)
    win.task_manager.active_count = 1
    win._on_task_finished(win.task_manager, MockTask(pkg_rg, 'uninstall', TaskStatus.COMPLETED))
    assert backend_reload_calls == [True]
    # Trigger task-finished success (upgrade)
    win.task_manager.active_count = 0
    win._on_task_finished(win.task_manager, MockTask(pkg_rg, 'upgrade', TaskStatus.COMPLETED))
    assert backend_reload_calls == [True, True]
    # Trigger task-finished failed
    win._on_task_finished(win.task_manager, MockTask(pkg_rg, 'install', TaskStatus.FAILED))
    
    # Trigger task-finished ambiguous tap failed
    task_ambig = MockTask(pkg_rg, 'install', TaskStatus.FAILED)
    task_ambig.ambiguous_taps = ['user/tap/ripgrep']
    win._on_task_finished(win.task_manager, task_ambig)
    
    # Trigger task-finished conflict failed
    task_conflict = MockTask(pkg_rg, 'install', TaskStatus.FAILED)
    task_conflict.conflict_info = {'installed_tap': 'user/tap', 'target_tap': 'homebrew/core'}
    win._on_task_finished(win.task_manager, task_conflict)
    
    # Trigger ambiguous tap row response
    dialog_mock = Adw.AlertDialog()
    class MockRow:
        def __init__(self, val):
            self._qualified = val
    class MockListBox:
        def __init__(self, row):
            self._row = row
        def get_selected_row(self):
            return self._row
            
    win._on_ambiguous_tap_response(dialog_mock, 'install', MockListBox(MockRow('user/tap/ripgrep')), pkg_rg)
    win._on_ambiguous_tap_response(dialog_mock, 'cancel', None, pkg_rg)
    
    # Trigger conflict resolution responses
    win._on_conflict_resolution(dialog_mock, 'switch', task_conflict)
    win._on_conflict_resolution(dialog_mock, 'cancel', task_conflict)
    
    # Trigger conflict uninstall finished
    task_uninstall = MockTask(pkg_rg, 'uninstall', TaskStatus.COMPLETED)
    win._on_conflict_uninstall_finished(win.task_manager, task_uninstall)
    
    # 5. Test active count changes
    class MockPspec:
        pass
    win.task_manager.active_count = 3
    win._on_active_count_changed(win.task_manager, MockPspec())
    assert win.task_count_label.get_label() == '3'
    
    win.task_manager.active_count = 0
    win._on_active_count_changed(win.task_manager, MockPspec())
    assert win.task_count_label.get_visible() is False
    
    # Trigger task_progress / task_button_clicked
    win._on_task_progress_changed(win.task_manager, task1)
    win._on_task_button_clicked(None)
    
    # 6. Test Data Loaded signals
    win._on_formulae_loaded(win.backend, [pkg_rg])
    win._on_casks_loaded(win.backend, [pkg_fox])
    win._on_installed_loaded(win.backend, None)
    
    # Test outdated count changed
    win._on_outdated_count_changed(None, 0)
    win._on_outdated_count_changed(None, 2)
    
    # Test backend loading changed
    win.backend.loading = False
    win._package_to_open = 'ripgrep'
    win._on_backend_loading_changed(win.backend, None)
    
    # Test _check_deeplink
    win._package_to_open = 'firefox'
    win._tap_to_open = 'hanthor/tap'
    win._check_deeplink()
    
    # Test open_tap_by_name (should return False in test context since mock list is empty)
    assert win.open_tap_by_name('hanthor/tap') is False
    
    # 7. Test page-level request signals
    win._on_tap_operation(None, 'Tap completed')
    win._on_install_requested(None, pkg_rg)
    win._on_remove_requested(None, pkg_rg)
    win._on_package_history_requested(None, pkg_rg)
    win._on_pin_version_requested(None, '1.0.0')
    win._on_package_changed(None, pkg_rg)
    
    # 8. Test actions
    win._on_refresh(None, None)
    
    # Test open brewfile
    win._on_open_brewfile(None, None)
    
    # Test open_brewfile tab creation & loading
    dummy_brewfile = tmp_path / 'my.Brewfile'
    dummy_brewfile.write_text('brew "ripgrep"\n')
    
    win.open_brewfile(str(dummy_brewfile))
    assert 'brewfile_1' in win._open_brewfiles
    
    # Test opening same brewfile again (should focus existing tab)
    win.open_brewfile(str(dummy_brewfile))
    
    # Test close request (saves sizes)
    win._on_close()
