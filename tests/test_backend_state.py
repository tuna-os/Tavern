"""State discovery contracts with no dependency on the host Homebrew install."""
import subprocess
import threading
from types import SimpleNamespace

import pytest

from tavern import backend_state


@pytest.mark.parametrize('formula_result', [
    subprocess.CompletedProcess([], 0, 'git\npython\ngit\n', ''),
    subprocess.CompletedProcess([], 1, '', 'unavailable'),
    subprocess.TimeoutExpired('brew', 30),
])
def test_installed_discovery_keeps_casks_when_formulae_fail(monkeypatch, formula_result):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        assert kwargs == {'capture_output': True, 'text': True, 'timeout': 30}
        if '--formula' in args:
            if isinstance(formula_result, Exception):
                raise formula_result
            return formula_result
        return subprocess.CompletedProcess(args, 0, 'tavern\n', '')

    monkeypatch.setattr(backend_state, '_brew_cmd', lambda args: ['brew', *args])
    monkeypatch.setattr(backend_state.subprocess, 'run', run)
    formulae, casks = backend_state.StateMixin()._get_installed()
    expected = {'git', 'python'} if getattr(formula_result, 'returncode', None) == 0 else set()
    assert formulae == expected
    assert casks == {'tavern'}
    assert calls == [['brew', 'list', '--formula', '-1'], ['brew', 'list', '--cask', '-1']]


def test_get_pinned_returns_a_snapshot():
    host = SimpleNamespace(_pinned={'git'}, _pinned_lock=threading.Lock())
    snapshot = backend_state.StateMixin.get_pinned(host)
    snapshot.clear()
    assert host._pinned == {'git'}
