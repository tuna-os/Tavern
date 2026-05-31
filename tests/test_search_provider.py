# test_search_provider.py - Tests for GNOME Shell Search Provider
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import pytest

from gi.repository import Gio, GLib

from tavern.backend import Package
from tavern.search_provider import TavernSearchProvider


def test_build_search_provider_cache(tmp_path, fresh_logging, monkeypatch):
    """Test that the backend correctly builds the search provider cache."""
    from tavern.backend import BrewBackend
    
    # Mock system platform to test linux filtering
    monkeypatch.setattr('sys.platform', 'linux')
    
    backend = BrewBackend()
    backend._cache_dir = str(tmp_path)
    
    # Add some mock packages
    backend._formulae = [
        Package({
            'name': 'ripgrep',
            'desc': 'Fast grep alternative',
            'versions': {'stable': '14.1'}
        }, 'formula')
    ]
    
    backend._casks = [
        Package({
            'token': 'firefox',
            'name': ['Mozilla Firefox'],
            'desc': 'Web browser'
        }, 'cask'),
        # Casks that are macOS only should not be in the cache if filtered properly
    ]
    
    # Build cache
    backend._build_search_provider_cache()
    
    cache_path = os.path.join(str(tmp_path), 'linux_packages.json')
    assert os.path.exists(cache_path)
    
    with open(cache_path, 'r') as f:
        data = json.load(f)
        
    assert len(data) == 2
    
    rg = next(p for p in data if p['name'] == 'ripgrep')
    assert rg['pkg_type'] == 'formula'
    assert rg['description'] == 'Fast grep alternative'
    
    ff = next(p for p in data if p['name'] == 'firefox')
    assert ff['pkg_type'] == 'cask'
    assert ff['display_name'] == 'Mozilla Firefox'


def test_search_provider_logic(tmp_path, fresh_logging):
    """Test the search logic of the SearchProvider."""
    # Write a mock cache file
    cache_dir = os.path.join(GLib.get_user_cache_dir(), 'tavern')
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, 'linux_packages.json')
    
    test_data = [
        {'name': 'ripgrep', 'display_name': 'ripgrep', 'description': 'Search tool', 'pkg_type': 'formula'},
        {'name': 'grep', 'display_name': 'grep', 'description': 'Standard grep', 'pkg_type': 'formula'},
        {'name': 'postgresql', 'display_name': 'postgresql', 'description': 'Relational database', 'pkg_type': 'formula'},
        {'name': 'firefox', 'display_name': 'Mozilla Firefox', 'description': 'Web browser', 'pkg_type': 'cask'},
    ]
    
    with open(cache_path, 'w') as f:
        json.dump(test_data, f)
        
    # Create provider (mock application)
    class MockApp:
        def __init__(self):
            self.actions = []
        def activate_action(self, name, param):
            self.actions.append((name, param.get_string()))
            
    app = MockApp()
    provider = TavernSearchProvider(app)
    
    # Test search
    results = provider._search(["grep"])
    # "grep" exact match should be first, then "ripgrep"
    assert results == ["grep", "ripgrep"]
    
    results = provider._search(["fire"])
    assert results == ["firefox"]
    
    results = provider._search(["SQL"])
    assert results == ["postgresql"]
    
    # Cleanup
    if os.path.exists(cache_path):
        os.remove(cache_path)


def test_search_provider_dbus_methods(tmp_path, monkeypatch):
    """Test the _handle_method_call dispatcher of TavernSearchProvider."""
    # Write a mock cache file in a temporary location
    cache_dir = os.path.join(str(tmp_path), 'tavern')
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, 'linux_packages.json')
    
    test_data = [
        {'name': 'ripgrep', 'display_name': 'ripgrep', 'description': 'Search tool', 'pkg_type': 'formula'},
        {'name': 'firefox', 'display_name': 'Mozilla Firefox', 'description': 'Web browser', 'pkg_type': 'cask'},
    ]
    with open(cache_path, 'w') as f:
        json.dump(test_data, f)
        
    # Mock GLib.get_user_cache_dir
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))

    class MockApp:
        def __init__(self):
            self.actions = []
            self.activated = False
        def activate_action(self, name, param):
            self.actions.append((name, param.get_string()))
        def activate(self):
            self.activated = True

    class MockInvocation:
        def __init__(self):
            self.returned = None
            self.error = None
        def return_value(self, variant):
            self.returned = variant
        def return_error_literal(self, code, message):
            self.error = (code, message)

    app = MockApp()
    provider = TavernSearchProvider(app)

    # 1. GetInitialResultSet
    inv = MockInvocation()
    params = GLib.Variant("(as)", (["firefox"],))
    provider._handle_method_call(None, None, None, None, "GetInitialResultSet", params, inv)
    assert inv.returned is not None
    assert inv.returned.unpack() == (["firefox"],)

    # 2. GetSubsearchResultSet
    inv = MockInvocation()
    params = GLib.Variant("(asas)", ([], ["ripgrep"]))
    provider._handle_method_call(None, None, None, None, "GetSubsearchResultSet", params, inv)
    assert inv.returned is not None
    assert inv.returned.unpack() == (["ripgrep"],)

    # 3. GetResultMetas
    inv = MockInvocation()
    params = GLib.Variant("(as)", (["firefox", "unknown"],))
    provider._handle_method_call(None, None, None, None, "GetResultMetas", params, inv)
    assert inv.returned is not None
    metas = inv.returned.unpack()[0]
    assert len(metas) == 1
    assert metas[0]["name"] == "Mozilla Firefox"
    assert metas[0]["description"] == "Web browser"

    # Write a mock icon for firefox to exercise icon path loading
    icon_path = os.path.join(cache_dir, 'icon_firefox.png')
    with open(icon_path, 'w') as f:
        f.write('')
    inv = MockInvocation()
    provider._handle_method_call(None, None, None, None, "GetResultMetas", params, inv)
    metas = inv.returned.unpack()[0]
    assert len(metas) == 1

    # 4. ActivateResult
    inv = MockInvocation()
    params = GLib.Variant("(as)", (["firefox"],))
    # Wait, parameters for ActivateResult: (s, as, u) -> (Result, Terms, Timestamp)
    params = GLib.Variant("(sasu)", ("firefox", [], 0))
    provider._handle_method_call(None, None, None, None, "ActivateResult", params, inv)
    assert app.actions == [("show-package", "firefox")]

    # 5. LaunchSearch
    inv = MockInvocation()
    params = GLib.Variant("(asu)", (["firefox"], 0))
    provider._handle_method_call(None, None, None, None, "LaunchSearch", params, inv)
    assert app.activated is True

    # 6. Unknown method
    inv = MockInvocation()
    provider._handle_method_call(None, None, None, None, "UnknownMethod", None, inv)
    assert inv.error is not None


def test_search_provider_export():
    class MockConnection:
        def __init__(self):
            self.registered = []
        def register_object(self, path, interface, method_call, get_property, set_property):
            self.registered.append(path)
            return 123
        def unregister_object(self, reg_id):
            pass

    provider = TavernSearchProvider(None)
    conn = MockConnection()
    
    # Export first time
    provider.export(conn)
    assert provider.registration_id == 123
    assert "/dev/hanthor/Tavern/SearchProvider" in conn.registered

    # Export again (should be no-op)
    provider.export(conn)
    
    # Unexport
    provider.unexport()
    assert provider.registration_id == 0

