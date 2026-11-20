# test_package_details.py
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from gi.repository import Gtk, GLib, Gdk, GdkPixbuf, Adw
from tavern.package_details import TavernPackageDetails
from tavern.backend import Package, BrewBackend
from tavern.task_manager import Task, TaskManager, TaskStatus, TaskOperation

@pytest.fixture
def pixbuf():
    return GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 32, 32)

def test_package_details_workflows(tmp_path, monkeypatch, pixbuf):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    # Mock launchers and alert dialogs to operate headlessly
    monkeypatch.setattr(Gtk.UriLauncher, 'launch', lambda self, parent, *args: setattr(self, '_launched', True))
    monkeypatch.setattr(Adw.Dialog, 'present', lambda self, parent: setattr(self, '_presented', True))
    monkeypatch.setattr(TavernPackageDetails, 'get_root', lambda self: Gtk.Window())
    
    backend = BrewBackend()
    task_manager = TaskManager(backend)
    
    # Pre-populate backend data for related packages
    pkg_rg = Package({'name': 'ripgrep', 'desc': 'rg'}, 'formula')
    # Using 'ripgrep@14' makes p_base == search_term ('ripgrep'), populating variants
    pkg_rg_base = Package({'name': 'ripgrep@14', 'desc': 'rg-base'}, 'formula')
    pkg_other = Package({'name': 'other-dep', 'desc': 'other'}, 'formula')
    
    backend._formulae = [pkg_rg, pkg_rg_base, pkg_other]
    monkeypatch.setattr(backend, 'search', lambda term: [pkg_rg, pkg_rg_base, pkg_other])
    
    # Instantiation of details page
    details = TavernPackageDetails(package=pkg_rg, backend=backend, task_manager=task_manager)
    assert details is not None
    assert details.get_title() == 'ripgrep'
    
    # Test _load_related_packages
    details._load_related_packages()
    assert details.variants_bin.get_visible() is True
    assert details.related_bin.get_visible() is True
    
    # Test related click and install
    variant_tile = details.variants_flow.get_first_child().get_child()
    
    activated_pkgs = []
    details.connect('package-activated', lambda d, p: activated_pkgs.append(p))
    details._on_related_clicked(variant_tile)
    assert len(activated_pkgs) == 1
    
    details._on_related_install_requested(variant_tile)
    # Check that variant package was queued
    assert task_manager.get_task_for_package(pkg_rg_base) is not None
    
    # Test callbacks: Icon, Screenshot, Info loaded
    details._on_icon_fetched(pkg_rg, pixbuf)
    details._on_screenshot_fetched(pkg_rg, pixbuf)
    assert details.screenshot_bin.get_visible() is True
    
    details._on_info_loaded(pkg_rg, {'analytics': {'install': {'90d': {'ripgrep': 150000}}}})
    assert pkg_rg.name == 'ripgrep'
    assert pkg_rg.description == 'rg'
    assert details.installs_label.get_label() == '150.00K'
    assert details.installs_stack.get_visible_child_name() == 'label'
    
    # Test line 296: _on_readme_fetched
    readme_text = "# Ripgrep\nThis is a cool tool.\n---"
    details._on_readme_fetched(pkg_rg, readme_text)
    assert details.readme_bin.get_visible() is True
    assert 'Ripgrep' not in details.readme_preview_label.get_label() # Header lines are skipped
    
    # Test on_show_readme_clicked
    details.on_show_readme_clicked()
    
    # Test button click actions (install, update, remove)
    details._on_install_clicked(None)
    assert details._task is not None
    assert details._task.operation == TaskOperation.INSTALL
    
    # Update progress
    details._task.progress = 0.6
    details._on_task_progress(details._task, None)
    assert details.detail_progress_bar.get_fraction() == 0.6
    
    # Task finish (success)
    details._on_task_finished(details._task, True)
    assert details._task is None
    assert details.detail_progress_bar.get_visible() is False
    
    # Remove click
    details._on_remove_clicked(None)
    assert details._task.operation == TaskOperation.REMOVE
    
    # Task finish (failed)
    details._task.error_detail = 'Untap error'
    details._on_task_finished(details._task, False)
    assert details.error_label.get_label() == 'Untap error'
    assert details.error_label.get_visible() is True
    
    # Update click
    pkg_rg.installed = True
    details._update_buttons()
    details._on_update_clicked(None)
    assert details._task is not None
    details._on_task_finished(details._task, True)
    
    # Test row activations
    # 1. Version row -> history requested
    hist_reqs = []
    details.connect('package-history-requested', lambda d, p: hist_reqs.append(p))
    details._on_info_row_activated(None, details.version_row)
    assert len(hist_reqs) == 1
    
    # 2. Homepage row -> launch
    details._on_info_row_activated(None, details.homepage_row)
    
    # 3. Installs row -> present stats
    details._on_info_row_activated(None, details.installs_row)
    
    # 4. Screenshot click -> present lightbox
    details._on_screenshot_clicked(None)

def test_package_details_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    details = TavernPackageDetails(package=None, backend=None, task_manager=None)
    assert details is not None


@pytest.mark.parametrize('homepage', [
    'file:///etc/passwd',
    'smb://host/share',
    'brew://tap/owner/name',
    'javascript:alert(1)',
])
def test_homepage_that_is_not_a_web_link_is_never_launched(tmp_path, monkeypatch, homepage):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    launched = []
    monkeypatch.setattr(Gtk.UriLauncher, 'launch',
                        lambda self, parent, *args: launched.append(self.get_uri()))

    # The author of a tap chooses the homepage text of its packages.
    pkg = Package({'name': 'tap-formula', 'desc': 'd', 'homepage': homepage}, 'formula')
    details = TavernPackageDetails(package=pkg, backend=None, task_manager=None)

    assert details.homepage_label.get_label() == homepage
    assert not details.homepage_row.get_sensitive()
    details._on_info_row_activated(None, details.homepage_row)
    details.on_show_readme_clicked()
    assert launched == []


def test_web_homepage_is_launched(tmp_path, monkeypatch):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    launched = []
    monkeypatch.setattr(Gtk.UriLauncher, 'launch',
                        lambda self, parent, *args: launched.append(self.get_uri()))

    homepage = 'https://example.com/project'
    pkg = Package({'name': 'tap-formula', 'desc': 'd', 'homepage': homepage}, 'formula')
    details = TavernPackageDetails(package=pkg, backend=None, task_manager=None)

    assert details.homepage_row.get_sensitive()
    details._on_info_row_activated(None, details.homepage_row)
    details.on_show_readme_clicked()
    assert launched == [homepage, homepage]


def test_readme_navigation_opens_only_a_link_the_user_clicked(monkeypatch):
    from types import SimpleNamespace
    import tavern.package_details as package_details

    navigation = object()
    clicked, other = object(), object()
    monkeypatch.setattr(package_details, 'WebKit', SimpleNamespace(
        PolicyDecisionType=SimpleNamespace(NAVIGATION_ACTION=navigation),
        NavigationType=SimpleNamespace(LINK_CLICKED=clicked, OTHER=other)))
    launched = []
    monkeypatch.setattr(Gtk.UriLauncher, 'launch',
                        lambda self, parent, *args: launched.append(self.get_uri()))

    def navigate(uri, navigation_type):
        ignored = []
        request = SimpleNamespace(get_uri=lambda: uri)
        action = SimpleNamespace(get_request=lambda: request,
                                 get_navigation_type=lambda: navigation_type)
        decision = SimpleNamespace(get_navigation_action=lambda: action,
                                   ignore=lambda: ignored.append(uri))
        details = SimpleNamespace(get_root=lambda: None)
        handled = TavernPackageDetails._on_decide_policy(
            details, None, decision, navigation)
        return handled, ignored

    assert navigate('https://example.com/docs', clicked) == (True, ['https://example.com/docs'])
    assert launched == ['https://example.com/docs']

    # A README can navigate by itself, for example with a refresh in its
    # markup. That navigation is refused and opens nothing.
    assert navigate('https://evil.example/', other) == (True, ['https://evil.example/'])
    assert navigate('mailto:someone@evil.example', other) == (True, ['mailto:someone@evil.example'])
    assert launched == ['https://example.com/docs']

    # A click still opens only a web link.
    assert navigate('file:///etc/passwd', clicked) == (True, ['file:///etc/passwd'])
    assert launched == ['https://example.com/docs']
