# test_application.py
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
import sys
from gi.repository import GLib, Gio
from tavern.application import TavernApplication

def test_application_parse_argument_uri(tmp_path, monkeypatch):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    app = TavernApplication(version="1.0.0", application_id="dev.hanthor.Tavern.TestApp")
    
    # Test brew:// URIs
    t_type, t_val = app._parse_argument_uri("brew://formula/ripgrep")
    assert t_type == "package"
    assert t_val == "ripgrep"
    
    t_type, t_val = app._parse_argument_uri("brew://formulae/ripgrep")
    assert t_type == "package"
    assert t_val == "ripgrep"

    t_type, t_val = app._parse_argument_uri("brew://cask/firefox")
    assert t_type == "package"
    assert t_val == "firefox"

    t_type, t_val = app._parse_argument_uri("brew://casks/firefox")
    assert t_type == "package"
    assert t_val == "firefox"

    t_type, t_val = app._parse_argument_uri("brew://tap/hanthor/tap")
    assert t_type == "tap"
    assert t_val == "hanthor/tap"

    t_type, t_val = app._parse_argument_uri("brew://ripgrep")
    assert t_type == "package"
    assert t_val == "ripgrep"

    # Test web URLs
    t_type, t_val = app._parse_argument_uri("https://formulae.brew.sh/formula/ripgrep")
    assert t_type == "package"
    assert t_val == "ripgrep"

    t_type, t_val = app._parse_argument_uri("https://formulae.brew.sh/cask/firefox")
    assert t_type == "package"
    assert t_val == "firefox"

    # Test non-matching URLs
    t_type, t_val = app._parse_argument_uri("https://google.com")
    assert t_type is None
    assert t_val is None

    t_type, t_val = app._parse_argument_uri("")
    assert t_type is None
    assert t_val is None

def test_application_command_line(tmp_path, monkeypatch):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    app = TavernApplication(version="1.0.0", application_id="dev.hanthor.Tavern.TestApp")
    
    # Mock activate
    activated = []
    monkeypatch.setattr(app, 'activate', lambda: activated.append(True))
    
    # Test --package and --brewfile and brew:// tap URI
    monkeypatch.setattr(sys, 'argv', ['tavern', '--package', 'ripgrep', '--brewfile', 'my.Brewfile', 'brew://tap/hanthor/tap'])
    app.do_command_line(None)
    
    assert app._package_to_open == "ripgrep"
    assert app._brewfile_to_open == "my.Brewfile"
    assert app._tap_to_open == "hanthor/tap"
    assert len(activated) == 1
