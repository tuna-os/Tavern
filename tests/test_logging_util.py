# test_logging_util.py - Tests for the logging & profiling module
# SPDX-License-Identifier: GPL-3.0-or-later

import io
import logging
import os
import time

import pytest

import tavern.logging_util as lu
from tavern.logging_util import get_logger, init_logging, is_profiling, profile, log_timing


# ─── get_logger ──────────────────────────────────────────────────────────────

class TestGetLogger:
    def test_returns_namespaced_logger(self):
        log = get_logger('backend')
        assert log.name == 'Tavern.backend'

    def test_returns_same_instance_for_same_name(self):
        a = get_logger('foo')
        b = get_logger('foo')
        assert a is b

    def test_child_of_root_tavern_logger(self):
        log = get_logger('window')
        assert log.parent.name == 'Tavern'


# ─── init_logging ────────────────────────────────────────────────────────────

class TestInitLogging:
    def test_default_is_warning_level(self, fresh_logging, monkeypatch):
        monkeypatch.delenv('TAVERN_LOG', raising=False)
        monkeypatch.delenv('TAVERN_PROFILE', raising=False)
        fresh_logging._initialized = False
        init_logging()
        root = logging.getLogger('Tavern')
        assert root.level == logging.WARNING

    def test_tavern_log_1_sets_info(self, fresh_logging, monkeypatch):
        monkeypatch.setenv('TAVERN_LOG', '1')
        monkeypatch.delenv('TAVERN_PROFILE', raising=False)
        init_logging()
        root = logging.getLogger('Tavern')
        assert root.level == logging.INFO

    def test_tavern_log_debug_sets_debug(self, fresh_logging, monkeypatch):
        monkeypatch.setenv('TAVERN_LOG', 'debug')
        monkeypatch.delenv('TAVERN_PROFILE', raising=False)
        init_logging()
        root = logging.getLogger('Tavern')
        assert root.level == logging.DEBUG

    def test_profile_only_sets_info(self, fresh_logging, monkeypatch):
        monkeypatch.delenv('TAVERN_LOG', raising=False)
        monkeypatch.setenv('TAVERN_PROFILE', '1')
        init_logging()
        root = logging.getLogger('Tavern')
        assert root.level == logging.INFO

    def test_idempotent(self, fresh_logging, monkeypatch):
        monkeypatch.setenv('TAVERN_LOG', '1')
        monkeypatch.delenv('TAVERN_PROFILE', raising=False)
        init_logging()
        handlers_after_first = len(logging.getLogger('Tavern').handlers)
        init_logging()  # second call
        assert len(logging.getLogger('Tavern').handlers) == handlers_after_first

    def test_file_handler_created(self, fresh_logging, monkeypatch, tmp_path):
        log_file = str(tmp_path / 'test.log')
        monkeypatch.setenv('TAVERN_LOG', '1')
        monkeypatch.setenv('TAVERN_LOG_FILE', log_file)
        monkeypatch.delenv('TAVERN_PROFILE', raising=False)
        init_logging()
        root = logging.getLogger('Tavern')
        # Should have console + file handler
        assert len(root.handlers) >= 2
        # Write a message and check the file
        get_logger('test').info('hello file')
        for h in root.handlers:
            h.flush()
        with open(log_file) as f:
            contents = f.read()
        assert 'hello file' in contents

    def test_startup_banner_emitted(self, fresh_logging, monkeypatch, capsys):
        monkeypatch.setenv('TAVERN_LOG', 'info')
        monkeypatch.delenv('TAVERN_PROFILE', raising=False)
        monkeypatch.delenv('TAVERN_LOG_FILE', raising=False)
        init_logging()
        # Banner goes to stderr via StreamHandler
        captured = capsys.readouterr()
        assert 'Logging initialised' in captured.err


# ─── is_profiling ────────────────────────────────────────────────────────────

class TestIsProfiling:
    def test_false_by_default(self, fresh_logging, monkeypatch):
        monkeypatch.delenv('TAVERN_LOG', raising=False)
        monkeypatch.delenv('TAVERN_PROFILE', raising=False)
        init_logging()
        assert is_profiling() is False

    def test_true_when_env_set(self, fresh_logging, monkeypatch):
        monkeypatch.setenv('TAVERN_PROFILE', '1')
        monkeypatch.delenv('TAVERN_LOG', raising=False)
        init_logging()
        assert is_profiling() is True


# ─── @profile decorator ─────────────────────────────────────────────────────

class TestProfileDecorator:
    def test_passthrough_when_disabled(self, fresh_logging, monkeypatch):
        monkeypatch.delenv('TAVERN_PROFILE', raising=False)
        monkeypatch.delenv('TAVERN_LOG', raising=False)
        init_logging()

        @profile
        def add(a, b):
            return a + b

        assert add(2, 3) == 5

    def test_logs_when_enabled(self, fresh_logging, monkeypatch, capfd):
        monkeypatch.setenv('TAVERN_PROFILE', '1')
        monkeypatch.setenv('TAVERN_LOG', '1')
        init_logging()

        @profile
        def slow():
            time.sleep(0.02)
            return 42

        result = slow()
        assert result == 42
        captured = capfd.readouterr()
        assert 'slow' in captured.err
        assert 'took' in captured.err

    def test_threshold_filters_fast_calls(self, fresh_logging, monkeypatch, capfd):
        monkeypatch.setenv('TAVERN_PROFILE', '1')
        monkeypatch.setenv('TAVERN_LOG', '1')
        init_logging()

        @profile(threshold_ms=5000)
        def fast_fn():
            return 1

        fast_fn()
        captured = capfd.readouterr()
        # Should NOT appear — execution is well under 5000 ms
        assert 'fast_fn' not in captured.err

    def test_preserves_function_metadata(self):
        @profile
        def documented():
            """My docstring."""
            pass

        assert documented.__name__ == 'documented'
        assert documented.__doc__ == 'My docstring.'

    def test_exceptions_propagate(self, fresh_logging, monkeypatch):
        monkeypatch.setenv('TAVERN_PROFILE', '1')
        monkeypatch.setenv('TAVERN_LOG', '1')
        init_logging()

        @profile
        def boom():
            raise ValueError('kaboom')

        with pytest.raises(ValueError, match='kaboom'):
            boom()


# ─── log_timing context manager ─────────────────────────────────────────────

class TestLogTiming:
    def test_no_output_when_disabled(self, fresh_logging, monkeypatch, capfd):
        monkeypatch.delenv('TAVERN_PROFILE', raising=False)
        monkeypatch.delenv('TAVERN_LOG', raising=False)
        init_logging()

        with log_timing('some operation'):
            pass
        captured = capfd.readouterr()
        assert 'some operation' not in captured.err

    def test_logs_when_profiling(self, fresh_logging, monkeypatch, capfd):
        monkeypatch.setenv('TAVERN_PROFILE', '1')
        monkeypatch.setenv('TAVERN_LOG', '1')
        init_logging()

        with log_timing('my block'):
            time.sleep(0.01)
        captured = capfd.readouterr()
        assert 'my block' in captured.err
        assert 'took' in captured.err

    def test_does_not_suppress_exceptions(self, fresh_logging, monkeypatch):
        monkeypatch.setenv('TAVERN_PROFILE', '1')
        monkeypatch.setenv('TAVERN_LOG', '1')
        init_logging()

        with pytest.raises(RuntimeError):
            with log_timing('failing block'):
                raise RuntimeError('oops')
