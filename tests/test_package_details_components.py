# test_package_details_components.py
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

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


def test_asset_loader_cancel_discards_in_flight_results():
    backend = DeferredAssetBackend()
    loader = AssetLoaderController(backend)
    package = Package({'name': 'first'}, 'formula')
    delivered = []

    loader.load(package, lambda *args: delivered.append(args),
                lambda *args: delivered.append(args))
    loader.cancel()
    backend.icon_callbacks[package](package, 'late-icon')
    backend.screenshot_callbacks[package](package, 'late-screenshot')

    assert delivered == []


def test_asset_loader_set_backend_cancels_requests_to_old_backend():
    old_backend = DeferredAssetBackend()
    new_backend = DeferredAssetBackend()
    loader = AssetLoaderController(old_backend)
    package = Package({'name': 'first'}, 'formula')
    delivered = []

    loader.load(package, lambda *args: delivered.append(args),
                lambda *args: delivered.append(args))
    loader.set_backend(new_backend)
    old_backend.icon_callbacks[package](package, 'old-icon')
    loader.load(package, lambda *args: delivered.append(args),
                lambda *args: delivered.append(args))
    new_backend.icon_callbacks[package](package, 'new-icon')

    assert delivered == [(package, 'new-icon')]


def test_asset_loader_ignores_a_result_for_another_package():
    backend = DeferredAssetBackend()
    loader = AssetLoaderController(backend)
    shown = Package({'name': 'shown'}, 'formula')
    other = Package({'name': 'other'}, 'formula')
    delivered = []

    loader.load(shown, lambda *args: delivered.append(args),
                lambda *args: delivered.append(args))
    backend.icon_callbacks[shown](other, 'wrong-package')

    assert delivered == []


def test_asset_loader_load_without_backend_or_package_requests_nothing():
    backend = DeferredAssetBackend()
    package = Package({'name': 'first'}, 'formula')

    AssetLoaderController().load(package, lambda *a: None, lambda *a: None)
    AssetLoaderController(backend).load(None, lambda *a: None, lambda *a: None)

    assert backend.icon_callbacks == {}
    assert backend.screenshot_callbacks == {}


def test_asset_loader_load_without_package_invalidates_earlier_request():
    backend = DeferredAssetBackend()
    loader = AssetLoaderController(backend)
    package = Package({'name': 'first'}, 'formula')
    delivered = []

    loader.load(package, lambda *args: delivered.append(args),
                lambda *args: delivered.append(args))
    loader.load(None, lambda *a: None, lambda *a: None)
    backend.icon_callbacks[package](package, 'late-icon')

    assert delivered == []


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


def test_readme_html_has_csp_and_strips_active_elements():
    from tavern.readme_renderer import is_external_link_allowed

    renderer = ReadmeRenderer()
    text = (
        '# Hi\n\n<iframe src="https://evil.example"></iframe>\n'
        '<form action="https://evil.example"><input name="x"></form>\n'
        '<meta http-equiv="refresh" content="0;url=https://evil.example">\n'
        '<link rel="stylesheet" href="https://evil.example/x.css">\n'
        '<script>alert(1)</script>\n\nSafe **bold** text.'
    )

    html = renderer.html(text)
    body = html.split('<body>', 1)[1]

    assert "default-src 'none'" in html
    assert "form-action 'none'" in html
    # Raw active tags must never reach the WebView. Without python-markdown the
    # fallback escapes the whole README, so only tag openings are checked here.
    for needle in ('<iframe', '<form', '<input', '<meta', '<link', '<script'):
        assert needle not in body
    try:
        import markdown  # noqa: F401
    except ImportError:
        # Fallback path: text is escaped and shown verbatim, not rendered.
        assert 'Safe **bold** text.' in body
    else:
        assert '<strong>bold</strong>' in body
    assert is_external_link_allowed('https://example.com')
    assert is_external_link_allowed('mailto:a@example.com')
    assert not is_external_link_allowed('file:///etc/passwd')
    assert not is_external_link_allowed('javascript:alert(1)')


def test_strip_unsafe_html_does_not_join_text_into_a_new_tag():
    from tavern.readme_renderer import strip_unsafe_html

    # Each line hides one blocked tag in the name of a second one. Python-Markdown
    # keeps the content of a raw HTML block such as <p align="center"> as it is.
    html = (
        '<p align="center">'
        '<me<meta>ta http-equiv="refresh" content="0;url=https://evil.example">'
        '<sty<link>le>body { display: none }</sty<link>le>'
        '<ifr<base>ame src="https://evil.example"></ifr<base>ame>'
        '<fo<input>rm action="https://evil.example"><inp<meta>ut name="x"></fo<input>rm>'
        '<scr<meta>ipt>alert(1)</scr<meta>ipt>'
        'Safe text.</p>'
    )

    stripped = strip_unsafe_html(html)

    for needle in ('<meta', '<style', '<iframe', '<form', '<input', '<script',
                   '</style', '</iframe', '</form', '</script'):
        assert needle not in stripped
    assert 'Safe text.' in stripped


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


class FakeTask:
    """Records signal handlers the way ``GObject.connect``/``disconnect`` do."""

    def __init__(self, disconnect_error=None):
        self.handlers = {}
        self.disconnected = []
        self._next_id = 1
        self._disconnect_error = disconnect_error

    def connect(self, signal, callback):
        handler_id = self._next_id
        self._next_id += 1
        self.handlers[handler_id] = (signal, callback)
        return handler_id

    def disconnect(self, handler_id):
        if self._disconnect_error is not None:
            raise self._disconnect_error
        self.disconnected.append(handler_id)
        del self.handlers[handler_id]

    def emit(self, signal, *args):
        for sig, callback in list(self.handlers.values()):
            if sig == signal:
                callback(self, *args)


def test_task_binder_bind_none_unbinds_the_previous_task():
    task = FakeTask()
    binder = PackageTaskBinder(lambda *a: None, lambda *a: None)

    binder.bind(task)
    binder.bind(None)

    assert binder.task is None
    assert task.handlers == {}


def test_task_binder_unbind_without_a_task_and_twice_is_harmless():
    task = FakeTask()
    binder = PackageTaskBinder(lambda *a: None, lambda *a: None)

    binder.unbind()
    binder.bind(task)
    binder.unbind()
    binder.unbind()

    assert task.disconnected == [1, 2]
    assert binder.task is None


@pytest.mark.parametrize('error', [TypeError('gone'), ValueError('gone')])
def test_task_binder_unbind_ignores_handlers_gobject_already_removed(error):
    task = FakeTask(disconnect_error=error)
    binder = PackageTaskBinder(lambda *a: None, lambda *a: None)

    binder.bind(task)
    binder.unbind()

    assert binder.task is None


def test_task_binder_finished_callback_can_bind_a_replacement_task():
    first = FakeTask()
    second = FakeTask()
    finished = []
    binder = PackageTaskBinder(lambda *a: None, None)

    def on_finished(task, success):
        finished.append((task, success))
        binder.bind(second)

    binder._on_finished_callback = on_finished
    binder.bind(first)
    first.emit('finished', True)

    assert finished == [(first, True)]
    assert first.handlers == {}
    assert binder.task is second
    assert len(second.handlers) == 2
