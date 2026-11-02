# SPDX-License-Identifier: GPL-3.0-or-later

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tavern.deeplink_router import DeepLinkRouter


@pytest.fixture
def ctx():
    backend = SimpleNamespace(formulae=[], casks=[])
    view = SimpleNamespace(
        show_package=Mock(), select_tap=Mock(return_value=False),
        show_message=Mock(), open_brewfile=Mock(), show_tap_choice=Mock(),
        install_qualified=Mock(),
    )
    router = DeepLinkRouter(backend, **vars(view))
    return SimpleNamespace(router=router, backend=backend, view=view)


def package(name, display_name=None):
    return SimpleNamespace(name=name, display_name=display_name)


@pytest.mark.parametrize('target', ['ripgrep', ' RIPGREP ', 'Search Tool'])
def test_package_lookup_normalizes_name_and_display_name(ctx, target):
    pkg = package('ripgrep', 'Search Tool')
    ctx.backend.formulae = [pkg]
    assert ctx.router.open_package_by_name(target)
    ctx.view.show_package.assert_called_once_with(pkg)
    ctx.view.show_message.assert_not_called()


def test_formula_precedes_cask_and_lookup_reads_current_catalog(ctx):
    formula = package('same')
    cask = package('same', 'Cask App')
    ctx.backend.formulae = [formula]
    ctx.backend.casks = [cask]
    assert ctx.router.find_package_by_name('same') is formula
    assert ctx.router.find_package_by_name('cask app') is cask
    ctx.backend.formulae = []
    assert ctx.router.find_package_by_name('same') is cask


@pytest.mark.parametrize('target', [None, '', '  ', 'missing'])
def test_package_miss_can_be_silent(ctx, target):
    assert not ctx.router.open_package_by_name(target, show_not_found=False)
    ctx.view.show_package.assert_not_called()
    ctx.view.show_message.assert_not_called()
    assert not ctx.router.open_package_by_name(target)
    ctx.view.show_message.assert_called_once()


def test_pending_package_waits_for_casks_and_opens_once(ctx):
    ctx.router.package_to_open = 'firefox'
    ctx.router.check_pending()
    assert ctx.router.package_to_open == 'firefox'
    ctx.view.show_message.assert_not_called()
    cask = package('firefox', 'Firefox')
    ctx.backend.casks = [cask]
    ctx.router.check_pending()
    ctx.router.check_pending(final=True)
    ctx.router.check_pending(final=True)
    ctx.view.show_package.assert_called_once_with(cask)
    assert ctx.router.package_to_open is None


def test_pending_tap_retries_silently_and_opens_once(ctx):
    ctx.router.tap_to_open = 'user/tap'
    ctx.router.check_pending()
    assert ctx.router.tap_to_open == 'user/tap'
    ctx.view.show_message.assert_not_called()
    ctx.view.select_tap.return_value = True
    ctx.router.check_pending()
    ctx.router.check_pending(final=True)
    assert ctx.view.select_tap.call_count == 2
    assert ctx.router.tap_to_open is None


def test_final_load_reports_each_miss_once_and_opens_brewfile_once(ctx):
    ctx.router.package_to_open = 'missing-pkg'
    ctx.router.tap_to_open = 'missing/tap'
    ctx.router.brewfile_to_open = '/tmp/Brewfile'
    ctx.router.check_pending()
    ctx.router.check_pending()
    ctx.view.show_message.assert_not_called()
    ctx.view.open_brewfile.assert_not_called()
    ctx.router.check_pending(final=True)
    assert [call.args[0] for call in ctx.view.show_message.call_args_list] == [
        'Package "missing-pkg" not found', 'Tap "missing/tap" not found',
    ]
    ctx.view.open_brewfile.assert_called_once_with('/tmp/Brewfile')
    ctx.router.check_pending(final=True)
    assert ctx.view.show_message.call_count == 2
    assert ctx.view.open_brewfile.call_count == 1
    assert ctx.router.package_to_open is None
    assert ctx.router.tap_to_open is None
    assert ctx.router.brewfile_to_open is None


def test_direct_tap_open_reports_miss_and_returns_selection_result(ctx):
    assert not ctx.router.open_tap_by_name('user/tap')
    ctx.view.select_tap.assert_called_once_with('user/tap')
    ctx.view.show_message.assert_called_once_with('Tap "user/tap" not found')
    ctx.view.select_tap.return_value = True
    assert ctx.router.open_tap_by_name('user/tap')
    assert ctx.view.show_message.call_count == 1


def test_ambiguous_choice_only_installs_the_chosen_offered_target(ctx):
    pkg = package('tool')
    task = SimpleNamespace(package=pkg, ambiguous_taps=['a/tap/tool', 'b/tap/tool'])
    ctx.router.offer_ambiguous_tap_choice(task)
    shown_pkg, options, select = ctx.view.show_tap_choice.call_args.args
    assert shown_pkg is pkg
    assert options == ('a/tap/tool', 'b/tap/tool')
    ctx.view.install_qualified.assert_not_called()  # including cancellation
    select(None)
    select('unoffered/tap/tool')
    ctx.view.install_qualified.assert_not_called()
    # A later task mutation must not change the options for this dialog.
    task.ambiguous_taps.clear()
    select('b/tap/tool')
    ctx.view.install_qualified.assert_called_once_with(pkg, 'b/tap/tool')


def test_empty_ambiguous_choices_do_not_present_a_dialog(ctx):
    ctx.router.offer_ambiguous_tap_choice(SimpleNamespace(package=package('tool'), ambiguous_taps=[]))
    ctx.view.show_tap_choice.assert_not_called()


def test_router_has_no_widget_dependencies():
    source = Path(__file__).parents[1] / 'src' / 'deeplink_router.py'
    tree = ast.parse(source.read_text())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module)
    assert set(imports) <= {'gettext', 'logging_util'}
