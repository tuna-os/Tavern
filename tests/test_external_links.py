"""Only checked links reach the desktop launcher."""
import subprocess
from types import SimpleNamespace

import pytest
from gi.repository import Gtk

from tavern import external_links


@pytest.fixture
def launched(monkeypatch):
    uris = []
    monkeypatch.setattr(Gtk.UriLauncher, 'launch',
                        lambda self, parent, *args: uris.append(self.get_uri()))
    return uris


@pytest.fixture
def commands(monkeypatch):
    argv = []
    monkeypatch.setattr(subprocess, 'Popen', lambda args, **kwargs: argv.append(args))
    return argv


@pytest.mark.parametrize('uri', [
    'https://example.com/project',
    'http://example.com',
    'mailto:a@example.com',
])
def test_web_link_is_opened(launched, uri):
    assert external_links.open_web_link(uri) is True
    assert launched == [uri]


@pytest.mark.parametrize('uri', [
    'file:///etc/passwd',
    'smb://host/share',
    'brew://tap/owner/name',
    'appstream://org.example.App',
    'javascript:alert(1)',
    'example.com',
    '',
    None,
])
def test_link_that_is_not_a_web_link_is_not_opened(launched, uri):
    assert external_links.open_web_link(uri) is False
    assert launched == []


def test_link_button_opens_a_web_link(launched):
    button = external_links.web_link_button('https://example.com/docs', 'Open')

    assert button.get_sensitive()
    # True means the default handler, which opens any scheme, did not run.
    assert button.emit('activate-link') is True
    assert launched == ['https://example.com/docs']
    assert button.get_visited()


def test_link_button_does_not_open_other_schemes(launched):
    button = external_links.web_link_button('file:///etc/passwd', 'Open')

    assert not button.get_sensitive()
    assert button.emit('activate-link') is True
    assert launched == []
    assert not button.get_visited()


@pytest.mark.parametrize('app_id', [
    'org.mozilla.firefox',
    'org.gnome.font-viewer',
    'io.github.some-user.App_2',
])
def test_flatpak_app_page_is_opened_for_an_app_id(commands, app_id):
    assert external_links.open_flatpak_app_page(app_id) is True
    assert commands == [['xdg-open', f'appstream://{app_id}']]


@pytest.mark.parametrize('app_id', [
    'fail-flatpak',
    'org.example',
    'org..App',
    'org.example.1App',
    'org.example.App/../../other',
    'org.example.App?x=1',
    'org.example.App#fragment',
    'org.example.App other',
    'org.example.App\n',
    '-org.example.App',
    'org.example.' + 'a' * 250,
    '',
    None,
])
def test_flatpak_app_page_is_not_opened_for_other_text(commands, app_id):
    assert external_links.open_flatpak_app_page(app_id) is False
    assert commands == []


def test_brew_link_keeps_the_brew_scheme(monkeypatch):
    opened = []
    app_info = SimpleNamespace(launch_default_for_uri=lambda uri, context: opened.append(uri))
    monkeypatch.setattr(external_links, 'Gio', SimpleNamespace(AppInfo=app_info))

    external_links.open_brew_link('formula/ripgrep')
    external_links.open_brew_link('file:///etc/passwd')

    assert opened == ['brew://formula/ripgrep', 'brew://file:///etc/passwd']
