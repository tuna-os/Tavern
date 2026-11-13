# test_package_details_components.py
# SPDX-License-Identifier: GPL-3.0-or-later

from tavern.asset_loader import AssetLoaderController
from tavern.package import Package
from tavern.readme_renderer import ReadmeRenderer
from tavern.task_binding import PackageTaskBinder
from tavern.task_manager import Task, TaskOperation


class DeferredAssetBackend:
    def __init__(self):
        self.icon_callbacks = {}
        self.screenshot_callbacks = {}

    def fetch_icon_async(self, package, callback):
        self.icon_callbacks[package] = callback

    def fetch_screenshot_async(self, package, callback):
        self.screenshot_callbacks[package] = callback


def test_asset_loader_discards_results_for_previous_package():
    backend = DeferredAssetBackend()
    loader = AssetLoaderController(backend)
    first = Package({'name': 'first'}, 'formula')
    second = Package({'name': 'second'}, 'formula')
    icons = []
    screenshots = []

    loader.load(first, lambda package, pixbuf: icons.append((package, pixbuf)),
                lambda package, pixbuf: screenshots.append((package, pixbuf)))
    loader.load(second, lambda package, pixbuf: icons.append((package, pixbuf)),
                lambda package, pixbuf: screenshots.append((package, pixbuf)))

    backend.icon_callbacks[first](first, 'stale-icon')
    backend.screenshot_callbacks[first](first, 'stale-screenshot')
    backend.icon_callbacks[second](second, 'current-icon')
    backend.screenshot_callbacks[second](second, 'current-screenshot')

    assert icons == [(second, 'current-icon')]
    assert screenshots == [(second, 'current-screenshot')]


def test_readme_renderer_preserves_preview_and_uri_contract():
    renderer = ReadmeRenderer()
    text = '# Heading\n\n![badge](badge.svg)\n* First line\n- Second line'

    assert renderer.preview(text) == 'First line\nSecond line'
    assert renderer.preview('### only heading') == '### only heading'
    assert renderer.base_uri(
        'https://github.com/example/project/archive/v1.tar.gz'
    ) == 'https://raw.githubusercontent.com/example/project/HEAD/'
    assert renderer.base_uri('https://example.com/archive/v1.tar.gz') is None


def test_readme_renderer_formats_document_and_counts():
    renderer = ReadmeRenderer()

    html = renderer.html('## Title\n\nA [link](https://example.com).', is_dark=True)

    assert '<body>' in html
    assert '#e4e4e4' in html
    assert 'Title' in html
    assert renderer.format_install_count(0) == ''
    assert renderer.format_install_count(999) == '999'
    assert renderer.format_install_count(1_500) == '1.50K'
    assert renderer.format_install_count(1_500_000) == '1.50M'


def test_readme_document_limits_what_untrusted_html_can_load():
    html = ReadmeRenderer().html('<iframe src="https://example.com/"></iframe>')

    head = html.split('<body>', 1)[0]
    assert 'http-equiv="Content-Security-Policy"' in head
    for directive in ("default-src 'none'", 'img-src https: data:', 'media-src https:',
                      "form-action 'none'", "base-uri 'none'"):
        assert directive in head


def test_readme_navigation_policy_opens_only_clicked_web_links():
    policy = ReadmeRenderer().navigation_policy
    document = 'https://raw.githubusercontent.com/example/project/HEAD/'

    # The rendered document itself, with and without a base URI.
    assert policy(document, link_clicked=False, document_uri=document) == 'load'
    assert policy('about:blank', link_clicked=False) == 'load'

    # A README cannot navigate without a click, for example by meta refresh.
    assert policy('https://example.com/', link_clicked=False, document_uri=document) == 'block'
    assert policy('brew://formula/wget', link_clicked=False, document_uri=document) == 'block'
    assert policy(None, link_clicked=False) == 'block'

    # A clicked link leaves the app only for web and mail schemes.
    assert policy('https://example.com/docs', link_clicked=True, document_uri=document) == 'open'
    assert policy('HTTP://example.com/', link_clicked=True) == 'open'
    assert policy('mailto:dev@example.com', link_clicked=True) == 'open'
    for uri in ('file:///etc/passwd', 'javascript:alert(1)', 'brew://tap/x/y',
                'appstream://org.example.App', '', None):
        assert policy(uri, link_clicked=True, document_uri=document) == 'block'


def test_task_binder_replaces_connections_and_cleans_up():
    package = Package({'name': 'ripgrep'}, 'formula')
    first = Task(package, TaskOperation.INSTALL)
    second = Task(package, TaskOperation.REMOVE)
    progress = []
    finished = []
    binder = PackageTaskBinder(
        lambda task, _pspec: progress.append(task),
        lambda task, success: finished.append((task, success)),
    )

    binder.bind(first)
    first.progress = 0.4
    binder.bind(second)
    first.progress = 0.8
    second.progress = 0.6
    second._set_failed('failed')

    assert progress == [first, second]
    assert finished == [(second, False)]
    assert binder.task is None
