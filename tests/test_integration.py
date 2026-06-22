# test_integration.py - Headless end-to-end integration tests for Tavern
# SPDX-License-Identifier: GPL-3.0-or-later

import sys
import os
import time
import pytest
from gi.repository import Gio, GLib, Gtk, Adw

from tavern.application import TavernApplication
from tavern.backend import BrewBackend

class MockDBusConnection:
    def register_object(self, path, interface, method_call, get_property, set_property):
        return 101
    def unregister_object(self, reg_id):
        pass

def test_application_init_and_actions(monkeypatch, tmp_path):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    app = TavernApplication(version="1.0.0", application_id="org.tunaos.tavern.TestInit")
    assert app.version == "1.0.0"
    
    # Test quitting action
    quit_action = app.lookup_action('quit')
    assert quit_action is not None
    
    # Mock app.quit
    monkeypatch.setattr(app, 'quit', lambda: setattr(app, '_quit_called', True))
    quit_action.activate(None)
    assert getattr(app, '_quit_called', False) is True

def test_application_dbus_registration(monkeypatch, tmp_path):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    # Monkeypatch Gio.Application D-Bus methods to prevent type checking and session bus crashes
    monkeypatch.setattr(Gio.Application, 'do_dbus_register', lambda *args: True)
    monkeypatch.setattr(Gio.Application, 'do_dbus_unregister', lambda *args: None)
    
    app = TavernApplication(version="1.0.0", application_id="org.tunaos.tavern.TestDbus")
    conn = MockDBusConnection()
    
    # Register DBus
    app.do_dbus_register(conn, '/org.tunaos.tavern')
    assert app._search_provider is not None
    assert app._search_provider.registration_id == 101
    
    # Unregister DBus
    app.do_dbus_unregister(conn, '/org.tunaos.tavern')
    assert app._search_provider.registration_id == 0

def test_application_show_package(monkeypatch, tmp_path):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    app = TavernApplication(version="1.0.0", application_id="org.tunaos.tavern.TestShow")
    
    # Mock activate
    monkeypatch.setattr(app, 'activate', lambda: setattr(app, '_activated', True))
    
    # Activate show-package action
    show_pkg_action = app.lookup_action('show-package')
    assert show_pkg_action is not None
    
    show_pkg_action.activate(GLib.Variant('s', 'ripgrep'))
    assert app._package_to_open == 'ripgrep'
    assert getattr(app, '_activated', False) is True

def test_application_command_line_parsing(monkeypatch, tmp_path):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    app = TavernApplication(version="1.0.0", application_id="org.tunaos.tavern.TestCmd")
    monkeypatch.setattr(app, 'activate', lambda: None)
    
    # Test --package and --brewfile parsing
    sys_argv_mock = ["tavern", "--package", "ripgrep", "--brewfile", "/path/to/my.Brewfile"]
    monkeypatch.setattr(sys, "argv", sys_argv_mock)
    
    exit_code = app.do_command_line(None)
    assert exit_code == 0
    assert app._package_to_open == "ripgrep"
    assert app._brewfile_to_open == "/path/to/my.Brewfile"
    
    # Test --package= and --brewfile= format
    app2 = TavernApplication(version="1.0.0", application_id="org.tunaos.tavern.TestCmd2")
    monkeypatch.setattr(app2, 'activate', lambda: None)
    sys_argv_mock2 = ["tavern", "--package=wget", "--brewfile=/another.Brewfile"]
    monkeypatch.setattr(sys, "argv", sys_argv_mock2)
    
    exit_code2 = app2.do_command_line(None)
    assert exit_code2 == 0
    assert app2._package_to_open == "wget"
    assert app2._brewfile_to_open == "/another.Brewfile"

def test_application_activate_and_open(monkeypatch, tmp_path):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    app = TavernApplication(version="1.0.0", application_id="org.tunaos.tavern.TestActivate")
    
    # Register the application so the startup/startup signal emissions occur before window instantiations
    app.register(None)
    
    # Mock TavernWindow
    import tavern.application as app_mod
    class MockTavernWindow(Gtk.Window):
        def __init__(self, *args, **kwargs):
            # Pop custom GObject properties not defined in Gtk.Window
            kwargs.pop('package_to_open', None)
            kwargs.pop('tap_to_open', None)
            kwargs.pop('brewfile_to_open', None)
            super().__init__(*args, **kwargs)
            self.presented = False
            self.opened_brewfile = None
            self.opened_pkg = None
        def present(self):
            self.presented = True
        def open_brewfile(self, path):
            self.opened_brewfile = path
        def open_package_by_name(self, name):
            self.opened_pkg = name
            
    monkeypatch.setattr(app_mod, 'TavernWindow', MockTavernWindow)
    
    # Mock StyleContext.add_provider_for_display
    monkeypatch.setattr(Gtk.StyleContext, 'add_provider_for_display', lambda *args: None)
    
    # First activate (creates window)
    app._package_to_open = 'ripgrep'
    app._brewfile_to_open = '/my.Brewfile'
    app.do_activate()
    
    win = app.props.active_window
    assert win is not None
    assert isinstance(win, MockTavernWindow)
    assert win.presented is True
    assert win.opened_brewfile == '/my.Brewfile'
    
    # Second activate (window already exists)
    app._package_to_open = 'git'
    app.do_activate()
    assert win.opened_pkg == 'git'
    
    # Test do_open
    gfile = Gio.File.new_for_path('/another.Brewfile')
    app.do_open([gfile], 1, '')
    assert win.opened_brewfile == '/another.Brewfile'

def test_application_about_dialog(monkeypatch, tmp_path):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    app = TavernApplication(version="1.0.0", application_id="org.tunaos.tavern.TestAbout")
    
    # Mock active_window properties
    class MockActiveWin:
        pass
    monkeypatch.setattr(app, 'props', type('Props', (), {'active_window': MockActiveWin()}))
    
    # Mock Adw.AboutDialog.present
    monkeypatch.setattr(Adw.AboutDialog, 'present', lambda self, parent: setattr(app, '_about_shown', True))
    
    about_action = app.lookup_action('about')
    assert about_action is not None
    about_action.activate(None)
    
    assert getattr(app, '_about_shown', False) is True
