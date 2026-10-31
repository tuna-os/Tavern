# test_page_factory.py - PageFactory dependency-injection contracts
# SPDX-License-Identifier: GPL-3.0-or-later

"""The factory is the single place that wires pages/dialogs to the shared
backend and task_manager. These tests inject fake page modules so they exercise
the factory's wiring logic without constructing real GTK widgets (no display
required), which is the whole point of the extraction in #244."""

import sys
import types

import pytest

from tavern.page_factory import PageFactory


def _inject_fake_page(monkeypatch, modname, clsname):
    """Replace ``tavern.<modname>`` with a module whose ``<clsname>`` records
    how it was constructed, so we can assert the factory passed the right
    dependencies."""
    mod = types.ModuleType(f'tavern.{modname}')

    class FakePage:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    setattr(mod, clsname, FakePage)
    monkeypatch.setitem(sys.modules, f'tavern.{modname}', mod)
    return FakePage


def test_factory_stores_shared_dependencies():
    backend = object()
    task_manager = object()
    factory = PageFactory(backend, task_manager)
    assert factory.backend is backend
    assert factory.task_manager is task_manager


def test_wire_pages_calls_the_right_setter_on_each_page():
    factory = PageFactory('BACKEND', 'TM')
    calls = []

    class Browse:
        def set_backend(self, backend):
            calls.append(('browse', backend))

    class Search:
        def set_backend(self, backend):
            calls.append(('search', backend))

    class Installed:
        def set_backend_and_manager(self, backend, task_manager):
            calls.append(('installed', backend, task_manager))

    class Tap:
        def set_backend(self, backend):
            calls.append(('tap', backend))

    class Doctor:
        def set_task_manager(self, task_manager):
            calls.append(('doctor', task_manager))

    factory.wire_pages(Browse(), Search(), Installed(), Tap(), Doctor())
    assert calls == [
        ('browse', 'BACKEND'),
        ('search', 'BACKEND'),
        ('installed', 'BACKEND', 'TM'),
        ('tap', 'BACKEND'),
        ('doctor', 'TM'),
    ]


def test_create_package_details_injects_backend_and_manager(monkeypatch):
    FakePD = _inject_fake_page(monkeypatch, 'package_details', 'TavernPackageDetails')
    pkg = object()
    factory = PageFactory('BACKEND', 'TM')

    dialog = factory.create_package_details(pkg)

    assert isinstance(dialog, FakePD)
    assert dialog.args == ()
    assert dialog.kwargs == {
        'package': pkg,
        'backend': 'BACKEND',
        'task_manager': 'TM',
    }


def test_create_version_history_injects_backend_only(monkeypatch):
    FakeVH = _inject_fake_page(
        monkeypatch, 'version_history_dialog', 'TavernVersionHistoryDialog')
    pkg = object()
    factory = PageFactory('BACKEND', 'TM')

    dialog = factory.create_version_history(pkg)

    assert isinstance(dialog, FakeVH)
    assert dialog.kwargs == {'package': pkg, 'backend': 'BACKEND'}


def test_create_brewfile_page_wires_backend_and_manager(monkeypatch):
    FakeBF = _inject_fake_page(monkeypatch, 'brewfile_page', 'TavernBrewfilePage')
    FakeBF.set_backend_and_manager = (
        lambda self, backend, task_manager: setattr(self, 'wired', (backend, task_manager)))
    factory = PageFactory('BACKEND', 'TM')

    page = factory.create_brewfile_page()

    assert isinstance(page, FakeBF)
    assert page.args == ()
    assert page.kwargs == {}
    assert page.wired == ('BACKEND', 'TM')


def test_create_maintenance_page_passes_task_manager(monkeypatch):
    FakeMP = _inject_fake_page(monkeypatch, 'maintenance_page', 'MaintenancePage')
    factory = PageFactory('BACKEND', 'TM')

    page = factory.create_maintenance_page()

    assert isinstance(page, FakeMP)
    # MaintenancePage(self, manager, ...) is constructed positionally.
    assert page.args == ('TM',)
    assert page.kwargs == {}
