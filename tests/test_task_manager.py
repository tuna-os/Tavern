# test_task_manager.py - Tests for the task manager
# SPDX-License-Identifier: GPL-3.0-or-later

import threading
import time

import pytest

from gi.repository import GLib, GObject
from tavern.backend import Package, BrewBackend
from tavern.task_manager import (
    Task, TaskStatus, TaskOperation, TaskManager,
    _parse_phase, _PHASE_PATTERNS,
)


# ─── _parse_phase helper ────────────────────────────────────────────────────

class TestParsePhase:
    def test_downloading_detected(self):
        result = _parse_phase('==> Downloading https://example.com/pkg.tar.gz')
        assert result is not None
        label, frac = result
        assert 'Downloading' in label
        assert 0 < frac < 1

    def test_installing_detected(self):
        result = _parse_phase('==> Installing ripgrep')
        assert result is not None
        assert 'Installing' in result[0]

    def test_pouring_detected(self):
        result = _parse_phase('==> Pouring ripgrep--14.1.1.x86_64_linux.bottle.tar.gz')
        assert result is not None

    def test_uninstalling_detected(self):
        result = _parse_phase('==> Uninstalling /home/linuxbrew/.linuxbrew/Cellar/ripgrep/14.1.1')
        assert result is not None
        assert 'Removing' in result[0]

    def test_unknown_line_returns_none(self):
        result = _parse_phase('some random output line')
        assert result is None

    def test_caveats_detected(self):
        result = _parse_phase('==> Caveats')
        assert result is not None
        assert 'Almost' in result[0]

    def test_case_insensitive(self):
        result = _parse_phase('DOWNLOADING something...')
        assert result is not None


# ─── Task object ─────────────────────────────────────────────────────────────

class TestTask:
    @pytest.fixture()
    def pkg(self):
        return Package({'name': 'ripgrep', 'desc': 'rg', 'versions': {}, 'urls': {}}, 'formula')

    def test_title(self, pkg):
        task = Task(pkg, TaskOperation.INSTALL)
        assert 'Installing' in task.title
        assert 'ripgrep' in task.title

    def test_initial_state(self, pkg):
        task = Task(pkg, TaskOperation.INSTALL)
        assert task.status == TaskStatus.PENDING
        assert task.progress == 0.0
        assert task.is_active is True

    def test_set_running(self, pkg):
        task = Task(pkg, TaskOperation.INSTALL)
        task._set_running()
        assert task.status == TaskStatus.RUNNING
        assert task.progress > 0

    def test_set_completed(self, pkg):
        task = Task(pkg, TaskOperation.INSTALL)
        task._set_running()
        # Capture finished signal
        finished_args = []
        task.connect('finished', lambda t, s: finished_args.append(s))
        task._set_completed()
        assert task.status == TaskStatus.COMPLETED
        assert task.progress == 1.0
        assert finished_args == [True]
        assert task.is_active is False

    def test_set_failed(self, pkg):
        task = Task(pkg, TaskOperation.INSTALL)
        task._set_running()
        finished_args = []
        task.connect('finished', lambda t, s: finished_args.append(s))
        task._set_failed('something went wrong')
        assert task.status == TaskStatus.FAILED
        assert task.error_detail == 'something went wrong'
        assert finished_args == [False]
        assert task.is_active is False

    def test_update_phase_only_moves_forward(self, pkg):
        task = Task(pkg, TaskOperation.INSTALL)
        task._set_running()
        task._update_phase('Installing…', 0.5)
        assert task.progress == 0.5
        task._update_phase('Downloading…', 0.1)  # lower → ignored
        assert task.progress == 0.5


# ─── TaskManager ─────────────────────────────────────────────────────────────

class TestTaskManager:
    @pytest.fixture()
    def backend(self, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        return BrewBackend()

    @pytest.fixture()
    def mgr(self, backend):
        return TaskManager(backend)

    @pytest.fixture()
    def pkg(self):
        return Package({'name': 'ripgrep', 'desc': 'rg', 'versions': {}, 'urls': {}}, 'formula')

    def test_submit_adds_task(self, mgr, pkg):
        task = mgr.submit(pkg, TaskOperation.INSTALL)
        assert task in mgr.tasks
        assert task.package is pkg
        assert task.operation == TaskOperation.INSTALL

    def test_install_convenience(self, mgr, pkg):
        task = mgr.install(pkg)
        assert task.operation == TaskOperation.INSTALL

    def test_remove_convenience(self, mgr, pkg):
        task = mgr.remove(pkg)
        assert task.operation == TaskOperation.REMOVE

    def test_upgrade_convenience(self, mgr, pkg):
        task = mgr.upgrade(pkg)
        assert task.operation == TaskOperation.UPGRADE

    def test_get_task_for_package(self, mgr, pkg):
        task = mgr.submit(pkg, TaskOperation.INSTALL)
        found = mgr.get_task_for_package(pkg)
        assert found is task

    def test_get_task_for_unknown_package(self, mgr):
        other = Package({'name': 'unknown', 'desc': '', 'versions': {}, 'urls': {}}, 'formula')
        assert mgr.get_task_for_package(other) is None

    def test_task_added_signal(self, mgr, pkg):
        added = []
        mgr.connect('task-added', lambda m, t: added.append(t))
        task = mgr.submit(pkg, TaskOperation.INSTALL)
        assert task in added

    def test_extract_error_lines(self):
        lines = [
            '==> Downloading ...',
            'Error: No such file or directory',
            'fatal: could not read',
            'some more context',
        ]
        result = TaskManager._extract_error(lines)
        assert 'Error' in result or 'fatal' in result

    def test_extract_error_fallback(self):
        lines = ['line1', 'line2', 'line3', 'line4', 'line5']
        result = TaskManager._extract_error(lines)
        # Fallback: last 4 lines
        assert 'line5' in result

    def test_extract_error_empty(self):
        assert TaskManager._extract_error([]) == 'Unknown error'

    def test_detect_multi_tap_conflict(self):
        lines = [
            "Error: ripgrep was installed from the homebrew/core tap",
            "but you are trying to install it from the custom/tap tap",
        ]
        res = TaskManager._detect_multi_tap_conflict(lines)
        assert res == ("homebrew/core", "custom/tap")
        assert TaskManager._detect_multi_tap_conflict(["no conflict here"]) is None

    def test_detect_ambiguous_taps(self):
        lines = [
            "Error: ripgrep exists in multiple taps:",
            " * homebrew/core/ripgrep",
            " * custom/tap/ripgrep",
        ]
        res = TaskManager._detect_ambiguous_taps(lines)
        assert res == ["homebrew/core/ripgrep", "custom/tap/ripgrep"]
        assert TaskManager._detect_ambiguous_taps(["no ambiguity here"]) is None

    def test_install_qualified(self, mgr, pkg):
        task = mgr.install_qualified(pkg, "custom/tap/ripgrep")
        assert task.qualified_install_name == "custom/tap/ripgrep"
        assert task.operation == TaskOperation.INSTALL

    def test_run_task_success(self, mgr, pkg, monkeypatch):
        class MockStdout:
            def __init__(self):
                self.lines = [
                    "==> Downloading https://example.com/ripgrep",
                    "==> Installing ripgrep",
                    "==> Pouring ripgrep",
                ]
            def __iter__(self):
                return iter(self.lines)

        class MockProcess:
            def __init__(self, *args, **kwargs):
                self.stdout = MockStdout()
                self.returncode = 0
                self.pid = 9999
            def wait(self):
                pass

        monkeypatch.setattr("subprocess.Popen", MockProcess)
        monkeypatch.setattr("tavern.backend._brew_cmd", lambda args: ["brew"] + args)
        
        task = mgr.submit(pkg, TaskOperation.INSTALL)
        
        # Wait for the task thread to complete
        start = time.time()
        while task.is_active and time.time() - start < 2.0:
            GLib.MainContext.default().iteration(False)
            time.sleep(0.01)

        assert task.status == TaskStatus.COMPLETED

    def test_run_task_failure(self, mgr, pkg, monkeypatch):
        class MockStdout:
            def __init__(self):
                self.lines = [
                    "Error: ripgrep exists in multiple taps:",
                    " * homebrew/core/ripgrep",
                    " * custom/tap/ripgrep",
                ]
            def __iter__(self):
                return iter(self.lines)

        class MockProcess:
            def __init__(self, *args, **kwargs):
                self.stdout = MockStdout()
                self.returncode = 1
                self.pid = 9999
            def wait(self):
                pass

        monkeypatch.setattr("subprocess.Popen", MockProcess)
        monkeypatch.setattr("tavern.backend._brew_cmd", lambda args: ["brew"] + args)

        task = mgr.submit(pkg, TaskOperation.INSTALL)

        start = time.time()
        while task.is_active and time.time() - start < 2.0:
            GLib.MainContext.default().iteration(False)
            time.sleep(0.01)

        assert task.status == TaskStatus.FAILED
        assert task.ambiguous_taps == ["homebrew/core/ripgrep", "custom/tap/ripgrep"]



# ─── TaskOperation labels ───────────────────────────────────────────────────

class TestTaskOperation:
    def test_install_label(self):
        assert TaskOperation.label(TaskOperation.INSTALL) == 'Installing'

    def test_remove_label(self):
        assert TaskOperation.label(TaskOperation.REMOVE) == 'Removing'

    def test_upgrade_label(self):
        assert TaskOperation.label(TaskOperation.UPGRADE) == 'Upgrading'

    def test_unknown_label(self):
        assert TaskOperation.label('rebuild') == 'Rebuild'
