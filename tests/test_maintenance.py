"""UI and queue safety contracts use fake commands, not the host package manager."""
from types import SimpleNamespace
import pytest
from gi.repository import Gtk
from tavern import command_dialog, maintenance_page, brew_commands
from tavern.backend import Package
from tavern.task_manager import TaskManager, TaskStatus


@pytest.fixture
def synchronous(monkeypatch):
    monkeypatch.setattr(command_dialog.threading, 'Thread', lambda **kw:
                        SimpleNamespace(start=kw['target']))
    monkeypatch.setattr(command_dialog.GLib, 'idle_add', lambda fn, *args: fn(*args))


def test_failed_preview_cannot_queue(synchronous):
    commands = []
    dialog = command_dialog.show_command(Gtk.Window(), 'Review', 'Description',
        args=('cleanup', '--dry-run'), confirm=lambda: commands.append('cleanup'),
        runner=lambda args: SimpleNamespace(stdout='', stderr='Permission denied', returncode=1))
    assert not dialog.get_response_enabled('confirm')
    dialog.emit('response', 'confirm')
    assert commands == []


def test_successful_preview_waits_for_confirmation(synchronous):
    commands = []
    dialog = command_dialog.show_command(Gtk.Window(), 'Review', 'Description',
        args=('cleanup', '--dry-run'), confirm=lambda: commands.append('cleanup'),
        runner=lambda args: SimpleNamespace(stdout='Would remove old download', stderr='', returncode=0))
    assert dialog.get_response_enabled('confirm')
    assert not commands
    dialog.emit('response', 'confirm')
    assert commands == ['cleanup']


def test_legacy_install_requires_explicit_different_confirmation(synchronous):
    dialog = command_dialog.show_command(Gtk.Window(), 'Review', 'Description',
        args=('install', '--dry-run', 'hello'), confirm=lambda: None, allow_legacy_install=True,
        runner=lambda args: SimpleNamespace(stdout='', stderr='Error: invalid option: --dry-run', returncode=1))
    assert dialog.get_response_enabled('confirm')
    assert dialog.get_response_label('confirm') == 'Install Without Preview'


def test_install_preview_holds_immutable_qualified_argv(monkeypatch):
    manager = TaskManager(SimpleNamespace())
    started = []
    monkeypatch.setattr(manager, '_maybe_start_next', lambda: started.append(True))
    approvals = []
    manager.install_preview = lambda task, approve: approvals.append(approve)
    package = Package({'name': 'hello'}, 'formula')
    task = manager.install_qualified(package, 'owner/tap/hello')
    assert not manager.tasks and not started
    assert task.command == ('install', '--formula', 'owner/tap/hello')
    package.name = 'other'
    approvals[0]()
    assert manager.tasks == [task]
    assert task.command[-1] == 'owner/tap/hello'


def test_generic_task_has_no_fake_package_and_preflight_failure_never_spawns(monkeypatch):
    manager = TaskManager(SimpleNamespace())
    monkeypatch.setattr(manager, '_maybe_start_next', lambda: None)
    monkeypatch.setattr(command_dialog.GLib, 'idle_add', lambda fn, *args: fn(*args))
    def changed():
        raise ValueError('Brewfile changed')
    task = manager.submit_command(('bundle', 'install'), 'Install Brewfile', preflight=changed)
    assert task.packages == [] and task.package is None
    assert task.title == 'Install Brewfile'
    monkeypatch.setattr('tavern.task_manager.subprocess.Popen', lambda *a, **k: pytest.fail('Must not spawn'))
    manager._run_task(task)
    assert task.status == TaskStatus.FAILED
    assert 'Brewfile changed' in task.error_detail


def test_service_controls_queue_user_command_only_after_confirmation(monkeypatch):
    queued, dialogs = [], []
    task = SimpleNamespace(connect=lambda *a: None)
    manager = SimpleNamespace(submit_command=lambda *a: queued.append(a) or task)
    page = maintenance_page.MaintenancePage(manager)
    monkeypatch.setattr(maintenance_page, 'show_command', lambda *a, **kw: dialogs.append(kw))
    page._show_services(SimpleNamespace(stderr=''), [{'name': 'postgresql@17', 'status': 'started'}])
    page._service_action('postgresql@17', 'stop', 'Stop')
    assert not queued
    dialogs[0]['confirm']()
    assert queued[0][0] == ('services', 'stop', 'postgresql@17')


def test_security_ui_never_hides_incomplete_coverage():
    page = maintenance_page.MaintenancePage(SimpleNamespace())
    page._show_scan(SimpleNamespace(stdout='{}', stderr='Untrusted keg not scanned', returncode=1),
                    {'findings': [], 'skipped_formulae': ['example']})
    assert 'Coverage may be incomplete' in page.security_status.get_label()
    assert 'Untrusted keg not scanned' in page.security_status.get_label()
    assert 'example' in page.security_status.get_label()


def test_read_runner_preserves_streams_and_uses_host_adapter(monkeypatch):
    calls = []
    monkeypatch.setattr('tavern.backend._brew_cmd', lambda args: ['host-brew', *args])
    monkeypatch.setattr(brew_commands.subprocess, 'run', lambda *a, **kw: calls.append((a, kw)))
    brew_commands.run_read(('vulns', '--json'))
    args, options = calls[0]
    assert args[0] == ['host-brew', 'vulns', '--json']
    assert options['capture_output'] is True
    assert options['timeout'] == 120
    assert options['env']['HOMEBREW_NO_AUTO_UPDATE'] == '1'


def test_historical_install_requires_confirmation(monkeypatch):
    queued, dialogs = [], []
    page = maintenance_page.MaintenancePage(SimpleNamespace(submit_command=lambda *a: queued.append(a)))
    monkeypatch.setattr(maintenance_page, 'show_command', lambda *a, **kw: dialogs.append(kw))
    page.formula_entry.set_text('ripgrep')
    page.version_entry.set_text('14.1.0')
    page._version_install(None)
    assert not queued
    dialogs[-1]['confirm']()
    assert queued[0][0] == ('version-install', 'ripgrep', '14.1.0')


def test_completed_read_does_not_reopen_closed_dialog(monkeypatch):
    workers = []
    monkeypatch.setattr(command_dialog.threading, 'Thread', lambda **kw:
                        SimpleNamespace(start=lambda: workers.append(kw['target'])))
    monkeypatch.setattr(command_dialog.GLib, 'idle_add', lambda fn, *args: fn(*args))
    queued, cancelled = [], []
    dialog = command_dialog.show_command(Gtk.Window(), 'Review', 'Description',
        args=('cleanup', '--dry-run'), confirm=lambda: queued.append(True),
        cancelled=lambda: cancelled.append(True),
        runner=lambda args: SimpleNamespace(stdout='Would remove', stderr='', returncode=0))
    dialog.emit('response', 'cancel')
    workers[0]()
    assert cancelled == [True]
    assert not queued
    assert not dialog.get_response_enabled('confirm')
