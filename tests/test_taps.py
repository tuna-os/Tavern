# test_taps.py - Unit tests for tap scanning, parsing, and trust (src/taps.py)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# TapsMixin previously had no direct tests.  These cover the two .rb metadata
# parsers, the filesystem tap scan (core-tap skip, dedupe, macos filtering),
# the GitHub popular-taps fetch, and the brew trust/tap/untrust command paths —
# all without a Homebrew install, a display server, or real network access.

import json
import os

import pytest

import tavern.taps as taps_mod
from tavern.taps import TapsMixin
from tavern.package import Package
from gi.repository import GObject


class MockCompletedProcess:
    def __init__(self, returncode, stdout, stderr=''):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _Host(GObject.Object, TapsMixin):
    """Minimal host that mixes in TapsMixin the way BrewBackend does."""

    # TapsMixin emits these on the host; BrewBackend declares them in its own
    # __gsignals__. Without them here, GObject raises
    # "unknown signal name: taps-loaded" the moment a scan finishes, so every
    # test that reaches _apply_tap_scan_results fails. Keep in sync with the
    # corresponding entries in src/backend.py.
    __gsignals__ = {
        'formulae-loaded': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'casks-loaded': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'taps-loaded': (GObject.SignalFlags.RUN_LAST, None, (object,)),
    }

    def __init__(self):
        super().__init__()
        self._formulae = []
        self._casks = []
        self._installed_formulae = set()
        self._installed_casks = set()
        self._tap_packages = {}
        self._tap_list = []
        self._cache = {}

    def _load_cached(self, key, max_age=0):
        if key in self._cache:
            return (self._cache[key], False)
        return (None, False)

    def _save_cache(self, key, value):
        self._cache[key] = value


@pytest.fixture
def host():
    return _Host()


@pytest.fixture(autouse=True)
def no_backend_import(monkeypatch):
    """Every taps test avoids importing the full backend: _brew_cmd() lazily
    imports tavern.backend (which pulls in the whole GI stack).  Stub it out
    so only the command list matters."""
    monkeypatch.setattr(taps_mod, '_brew_cmd', lambda args: ['brew'] + args)


@pytest.fixture
def idle(monkeypatch):
    """Capture GLib.idle_add invocations instead of scheduling them."""
    calls = []
    monkeypatch.setattr(taps_mod.GLib, 'idle_add', lambda fn, *a, **k: calls.append((fn, a, k)) or 1)
    return calls


@pytest.fixture
def fake_thread(monkeypatch):
    """Fake threading.Thread that records targets without running them."""
    started = []

    class FakeThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
            self.target = target
            self.args = args
            self.kwargs = kwargs or {}
            self.daemon = daemon

        def start(self):
            started.append(self)

    monkeypatch.setattr(taps_mod.threading, 'Thread', FakeThread)
    return started


# ─── .rb metadata parsers ─────────────────────────────────────────────────────

class TestMinimalFormulaParser:
    def test_extracts_all_fields(self, host, tmp_path):
        rb = tmp_path / 'hello.rb'
        rb.write_text('''\
class Hello < Formula
  desc "Say hello to the world"
  homepage "https://github.com/example/hello"
  version "1.2.3"
  url "https://github.com/example/hello/archive/1.2.3.tar.gz"
  license "MIT"
end
''')
        data = host._minimal_formula_data_from_rb(str(rb), 'user1/hello', 'hello')
        assert data == {
            'name': 'hello',
            'full_name': 'user1/hello/hello',
            'desc': 'Say hello to the world',
            'homepage': 'https://github.com/example/hello',
            'versions': {'stable': '1.2.3'},
            'license': 'MIT',
            'urls': {'stable': {'url': 'https://github.com/example/hello/archive/1.2.3.tar.gz'}},
        }

    def test_missing_fields_default_to_empty(self, host, tmp_path):
        rb = tmp_path / 'minimal.rb'
        rb.write_text('class Minimal < Formula\nend\n')
        data = host._minimal_formula_data_from_rb(str(rb), 'u/t', 'minimal')
        assert data['name'] == 'minimal'
        assert data['full_name'] == 'u/t/minimal'
        assert data['desc'] == ''
        assert data['homepage'] == ''
        assert data['versions'] == {'stable': ''}
        assert data['license'] == ''
        assert data['urls'] == {'stable': {'url': ''}}

    def test_version_from_tag_when_no_version_key(self, host, tmp_path):
        rb = tmp_path / 'tagged.rb'
        rb.write_text('class Tagged < Formula\n  url "https://example.com/tagged.tar.gz", tag: "v2.5.0"\nend\n')
        data = host._minimal_formula_data_from_rb(str(rb), 'u/t', 'tagged')
        assert data['versions'] == {'stable': '2.5.0'}

    def test_quotes_and_single_quotes_accepted(self, host, tmp_path):
        rb = tmp_path / 'q.rb'
        rb.write_text("class Q < Formula\n  desc 'single quoted desc'\nend\n")
        data = host._minimal_formula_data_from_rb(str(rb), 'u/t', 'q')
        assert data['desc'] == 'single quoted desc'

    def test_unreadable_file_returns_none(self, host, tmp_path):
        assert host._minimal_formula_data_from_rb(str(tmp_path / 'missing.rb'), 'u/t', 'x') is None

    def test_binary_garbage_does_not_crash(self, host, tmp_path):
        rb = tmp_path / 'garbage.rb'
        rb.write_bytes(b'\x00\x01\x02\xff' * 100)
        data = host._minimal_formula_data_from_rb(str(rb), 'u/t', 'garbage')
        assert data is not None


class TestMinimalCaskParser:
    def test_extracts_all_fields(self, host, tmp_path):
        rb = tmp_path / 'firefox.rb'
        rb.write_text('''\
cask "firefox" do
  version "130.0"
  name "Mozilla Firefox"
  desc "Web browser"
  homepage "https://www.mozilla.org/firefox/"
  url "https://download.mozilla.org/?product=firefox-130.0"
end
''')
        data = host._minimal_cask_data_from_rb(str(rb), 'homebrew/cask', 'firefox')
        assert data == {
            'token': 'firefox',
            'full_token': 'homebrew/cask/firefox',
            'name': ['Mozilla Firefox'],
            'desc': 'Web browser',
            'homepage': 'https://www.mozilla.org/firefox/',
            'version': '130.0',
            'url': 'https://download.mozilla.org/?product=firefox-130.0',
            'depends_on': {},
        }

    def test_macos_dependency_detected(self, host, tmp_path):
        rb = tmp_path / 'maconly.rb'
        rb.write_text('''\
cask "maconly" do
  version "1.0"
  depends_on macos: ">= :mojave"
end
''')
        data = host._minimal_cask_data_from_rb(str(rb), 'u/t', 'maconly')
        assert data['depends_on'] == {'macos': True}

    def test_no_name_uses_desc_then_token(self, host, tmp_path):
        rb = tmp_path / 't.rb'
        rb.write_text('cask "t" do\n  version "1.0"\n  desc "Fallback Name"\nend\n')
        data = host._minimal_cask_data_from_rb(str(rb), 'u/t', 't')
        assert data['name'] == ['Fallback Name']

    def test_missing_token_falls_back_to_filename(self, host, tmp_path):
        rb = tmp_path / 'weird.rb'
        rb.write_text('cask :v1 do\nend\n')
        data = host._minimal_cask_data_from_rb(str(rb), 'u/t', 'weird')
        assert data['token'] == 'weird'
        assert data['name'] == ['weird']

    def test_unreadable_file_returns_none(self, host, tmp_path):
        assert host._minimal_cask_data_from_rb(str(tmp_path / 'nope.rb'), 'u/t', 'nope') is None


# ─── filesystem tap scan ──────────────────────────────────────────────────────

@pytest.fixture
def fake_taps_root(tmp_path, monkeypatch):
    """Redirect the hardcoded Homebrew taps root to a tmp_path-backed tree."""
    real_isdir = os.path.isdir
    real_listdir = os.listdir
    FAKE_ROOT = '/home/linuxbrew/.linuxbrew/Homebrew'
    FAKE_TAPS = os.path.join(FAKE_ROOT, 'Library', 'Taps')

    def _real(p):
        if p == FAKE_ROOT or p == FAKE_TAPS or p.startswith(FAKE_TAPS + os.sep):
            rel = p[len(FAKE_TAPS):].lstrip(os.sep)
            return os.path.join(str(tmp_path), rel)
        return p

    monkeypatch.setattr(os.path, 'isdir', lambda p: real_isdir(_real(p)))
    monkeypatch.setattr(os, 'listdir', lambda p: real_listdir(_real(p)))
    return tmp_path


@pytest.fixture
def canned_parsers(monkeypatch):
    """Make the filesystem scan produce deterministic Packages without real
    .rb files (paths inside the scan are virtual).  The regex parsers
    themselves are covered separately on real files above."""

    def fake_formula(self, rb_path, tap_name, pkg_name):
        return {'name': pkg_name, 'full_name': f'{tap_name}/{pkg_name}',
                'desc': f'{pkg_name} desc', 'homepage': '',
                'versions': {'stable': '1.0'}, 'license': '',
                'urls': {'stable': {'url': ''}}}

    def fake_cask(self, rb_path, tap_name, pkg_name):
        dep = {'macos': True} if pkg_name == 'maconly' else {}
        return {'token': pkg_name, 'full_token': f'{tap_name}/{pkg_name}',
                'name': [pkg_name], 'desc': '', 'homepage': '',
                'version': '1.0', 'url': '', 'depends_on': dep}

    monkeypatch.setattr(TapsMixin, '_minimal_formula_data_from_rb', fake_formula)
    monkeypatch.setattr(TapsMixin, '_minimal_cask_data_from_rb', fake_cask)


class TestLoadTapPackages:
    def _make_tap(self, root, user, repo, formulae=(), casks=()):
        tap = root / user / f'homebrew-{repo}'
        if formulae:
            (tap / 'Formula').mkdir(parents=True)
            for name in formulae:
                (tap / 'Formula' / f'{name}.rb').write_text(f'class {name} < Formula\nend\n')
        if casks:
            (tap / 'Casks').mkdir(parents=True)
            for name in casks:
                (tap / 'Casks' / f'{name}.rb').write_text(f'cask "{name}" do\nend\n')
        return tap

    def _last_scan(self, idle, host):
        """Run the tap scan, then invoke the captured _apply_tap_scan_results
        call synchronously and return its arguments."""
        # _apply_tap_scan_results kicks off a REAL daemon thread for trust
        # status (src/taps.py::_load_tap_trust_status). Left alone it outlives
        # the test, then calls the patched GLib.idle_add and appends a late
        # 'taps-loaded' emit into whichever test happens to be running at that
        # moment — order-dependent, timing-dependent cross-test pollution.
        # Trust has its own coverage in TestTapTrust, so stub it out here.
        host._load_tap_trust_status = lambda: None
        host._load_tap_packages()
        assert idle, 'expected a scheduled tap scan'
        fn, args, _ = idle[-1]
        assert fn.__name__ == '_apply_tap_scan_results'
        host._apply_tap_scan_results(*args)
        return args

    def test_scan_finds_formulae_and_casks(self, host, idle, fake_taps_root, canned_parsers):
        self._make_tap(fake_taps_root, 'user1', 'foo', formulae=['alpha', 'beta'], casks=['gamma'])
        self._make_tap(fake_taps_root, 'user2', 'bar', formulae=['delta'])
        (fake_taps_root / 'user1' / 'homebrew-foo' / 'Formula' / 'README.md').write_text('not a formula')

        tap_packages, non_core, new_formulae, new_casks, f_changed, c_changed = self._last_scan(idle, host)

        assert set(tap_packages) == {'user1/foo', 'user2/bar'}
        assert sorted(p.name for p in tap_packages['user1/foo']) == ['alpha', 'beta', 'gamma']
        assert sorted(p.name for p in tap_packages['user2/bar']) == ['delta']
        # os.listdir() order is arbitrary, so the scan's output order is too —
        # sort before comparing rather than encoding one filesystem's ordering.
        assert sorted(t['name'] for t in non_core) == ['user1/foo', 'user2/bar']
        assert f_changed is True and c_changed is True

    def test_core_taps_skipped(self, host, idle, fake_taps_root, canned_parsers):
        self._make_tap(fake_taps_root, 'homebrew', 'core', formulae=['git'])
        self._make_tap(fake_taps_root, 'homebrew', 'cask', casks=['firefox'])
        self._make_tap(fake_taps_root, 'user1', 'real', formulae=['x'])

        tap_packages, non_core, *_ = self._last_scan(idle, host)
        assert list(tap_packages) == ['user1/real']
        assert [t['name'] for t in non_core] == ['user1/real']

    def test_non_homebrew_dirs_skipped(self, host, idle, fake_taps_root, canned_parsers):
        self._make_tap(fake_taps_root, 'user1', 'real', formulae=['x'])
        (fake_taps_root / 'user1' / 'not-a-tap').mkdir(parents=True)

        tap_packages, non_core, *_ = self._last_scan(idle, host)
        assert list(tap_packages) == ['user1/real']

    def test_existing_packages_deduplicated(self, host, idle, fake_taps_root, canned_parsers):
        self._make_tap(fake_taps_root, 'user1', 'foo', formulae=['alpha', 'dup'])
        host._formulae = [Package({'name': 'dup', 'full_name': 'dup'}, 'formula')]
        host._installed_formulae = {'dup'}

        tap_packages, _, new_formulae, _, f_changed, _ = self._last_scan(idle, host)
        assert sorted(p.name for p in tap_packages['user1/foo']) == ['alpha']
        assert sorted(p.name for p in new_formulae) == ['alpha', 'dup']
        assert f_changed is True

    def test_no_new_packages_means_no_change(self, host, idle, fake_taps_root, canned_parsers):
        self._make_tap(fake_taps_root, 'user1', 'foo', formulae=['alpha'])
        host._formulae = [Package({'name': 'alpha', 'full_name': 'alpha'}, 'formula')]
        host._installed_formulae = {'alpha'}

        tap_packages, _, _, _, f_changed, c_changed = self._last_scan(idle, host)
        assert f_changed is False and c_changed is False
        assert tap_packages == {}  # nothing NEW from the tap

    def test_macos_only_casks_skipped_on_linux(self, host, idle, fake_taps_root, canned_parsers, monkeypatch):
        self._make_tap(fake_taps_root, 'user1', 'foo', casks=['maconly', 'portable'])
        mac = fake_taps_root / 'user1' / 'homebrew-foo' / 'Casks' / 'maconly.rb'
        mac.write_text('cask "maconly" do\n  depends_on macos: ">= :ventura"\nend\n')
        monkeypatch.setattr(taps_mod.sys, 'platform', 'linux')

        tap_packages, *_ = self._last_scan(idle, host)
        assert sorted(p.name for p in tap_packages['user1/foo']) == ['portable']

    def test_macos_casks_included_on_macos(self, host, idle, fake_taps_root, canned_parsers, monkeypatch):
        self._make_tap(fake_taps_root, 'user1', 'foo', casks=['maconly'])
        mac = fake_taps_root / 'user1' / 'homebrew-foo' / 'Casks' / 'maconly.rb'
        mac.write_text('cask "maconly" do\n  depends_on macos: ">= :ventura"\nend\n')
        monkeypatch.setattr(taps_mod.sys, 'platform', 'darwin')

        tap_packages, *_ = self._last_scan(idle, host)
        assert sorted(p.name for p in tap_packages['user1/foo']) == ['maconly']

    def test_no_taps_dir_returns_silently(self, host, idle, fake_taps_root, monkeypatch):
        # Make every hardcoded candidate root a miss so the scan bails early.
        real_isdir = os.path.isdir
        roots = [
            '/home/linuxbrew/.linuxbrew/Homebrew',
            '/var/home/linuxbrew/.linuxbrew/Homebrew',
            '/opt/homebrew',
            '/usr/local/Homebrew',
        ]
        # Reject the candidate roots (and their Library/Taps joins).
        monkeypatch.setattr(
            os.path, 'isdir',
            lambda p: False if p in roots or p.startswith(roots[0]) else real_isdir(p),
        )
        assert host._load_tap_packages() is None
        assert idle == []

    def test_empty_taps_tree_schedules_empty_scan(self, host, idle, fake_taps_root):
        (fake_taps_root / 'unrelated').mkdir()
        host._load_tap_packages()
        fn, args, _ = idle[-1]
        assert args[0] == {}  # no tap packages
        assert args[1] == []  # no non-core taps


# ─── tap scan result application ──────────────────────────────────────────────

class TestApplyTapScanResults:
    def test_updates_state_and_emits(self, host, idle, monkeypatch):
        events = []
        host.connect('taps-loaded', lambda h, pkgs: events.append(('taps', pkgs)))
        host.connect('formulae-loaded', lambda h, f: events.append(('formulae', f)))
        host.connect('casks-loaded', lambda h, c: events.append(('casks', c)))
        trust_calls = []
        monkeypatch.setattr(host, '_load_tap_trust_status', lambda: trust_calls.append(1))

        pkgs = {'u/t': [Package({'name': 'x', 'full_name': 'u/t/x'}, 'formula')]}
        formulae = [Package({'name': 'x'}, 'formula')]
        casks = [Package({'token': 'c'}, 'cask')]
        host._apply_tap_scan_results(pkgs, [{'name': 'u/t', 'path': '/tmp'}],
                                     formulae, casks, True, True)

        assert host._tap_packages == pkgs
        assert host._tap_list == [{'name': 'u/t', 'path': '/tmp'}]
        assert host._formulae == formulae
        assert host._casks == casks
        assert events[0][0] == 'taps' and events[0][1] == pkgs
        assert events[1][0] == 'formulae'
        assert events[2][0] == 'casks'
        assert trust_calls == [1]

    def test_no_signal_when_nothing_changed(self, host, idle, monkeypatch):
        events = []
        host.connect('taps-loaded', lambda h, p: events.append('taps'))
        host.connect('formulae-loaded', lambda h, f: events.append('formulae'))
        monkeypatch.setattr(host, '_load_tap_trust_status', lambda: None)

        host._apply_tap_scan_results({}, [], [], [], False, False)
        assert events == ['taps']  # only taps-loaded re-emitted


# ─── popular taps fetch ───────────────────────────────────────────────────────

class TestFetchPopularTaps:
    def _mocked_urlopen(self, payload):
        class _Resp:
            def __init__(self, data):
                self._data = data

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return self._data

            def decode(self, enc):
                return self._data.decode(enc)

        return lambda req, timeout=None: _Resp(json.dumps(payload).encode())

    def test_parses_github_search_items(self, host, idle, monkeypatch):
        payload = {'items': [
            {'full_name': 'user1/homebrew-alpha', 'description': 'Alpha tools'},
            {'full_name': 'user2/homebrew-beta', 'description': None},
            {'full_name': 'user3/not-a-tap', 'description': 'ignored'},
            {'full_name': 'homebrew/homebrew-core', 'description': 'core'},
        ]}
        monkeypatch.setattr(taps_mod, 'urlopen', self._mocked_urlopen(payload))
        results = []
        host._fetch_popular_taps_thread(results.append)

        fn, args, _ = idle[-1]
        assert args[0] == [
            {'name': 'user1/alpha', 'gh_user': 'user1', 'desc': 'Alpha tools'},
            {'name': 'user2/beta', 'gh_user': 'user2', 'desc': ''},
        ]
        fn(*args)  # delivery is deferred through GLib.idle_add
        assert results == [args[0]]

    def test_cache_hit_skips_network(self, host, idle, monkeypatch):
        host._save_cache('popular_taps', [{'name': 'u/t', 'gh_user': 'u', 'desc': 'd'}])
        calls = []
        monkeypatch.setattr(taps_mod, 'urlopen', lambda *a, **k: calls.append(1))
        results = []
        host._fetch_popular_taps_thread(results.append)

        assert results == []
        fn, args, _ = idle[-1]
        assert args[0] == [{'name': 'u/t', 'gh_user': 'u', 'desc': 'd'}]
        assert calls == []

    def test_network_error_falls_back_to_stale_cache(self, host, idle, monkeypatch):
        host._save_cache('popular_taps', [{'name': 'stale/tap', 'gh_user': 'stale', 'desc': ''}])

        def boom(*a, **k):
            raise OSError('network down')

        monkeypatch.setattr(taps_mod, 'urlopen', boom)
        results = []
        host._fetch_popular_taps_thread(results.append)

        fn, args, _ = idle[-1]
        assert args[0] == [{'name': 'stale/tap', 'gh_user': 'stale', 'desc': ''}]

    def test_no_results_and_no_cache_yields_empty(self, host, idle, monkeypatch):
        monkeypatch.setattr(taps_mod, 'urlopen', self._mocked_urlopen({'items': []}))
        results = []
        host._fetch_popular_taps_thread(results.append)
        fn, args, _ = idle[-1]
        assert args[0] == []


# ─── tap trust ────────────────────────────────────────────────────────────────

@pytest.fixture
def brew_cmd(monkeypatch):
    monkeypatch.setattr(taps_mod, '_brew_cmd', lambda args: ['brew'] + args)
    return taps_mod._brew_cmd


class TestTapTrust:
    def test_trusted_tap_reports_true(self, host, idle, monkeypatch):
        monkeypatch.setattr(taps_mod.subprocess, 'run',
                            lambda *a, **k: MockCompletedProcess(0, json.dumps({'taps': ['u/t', 'other']})))
        results = []
        host._check_tap_trust_thread('u/t', results.append)
        fn, args, _ = idle[-1]
        fn(*args)
        assert results == [True]

    def test_untrusted_tap_reports_false(self, host, idle, monkeypatch):
        monkeypatch.setattr(taps_mod.subprocess, 'run',
                            lambda *a, **k: MockCompletedProcess(0, json.dumps({'taps': ['other']})))
        results = []
        host._check_tap_trust_thread('u/t', results.append)
        fn, args, _ = idle[-1]
        fn(*args)
        assert results == [False]

    def test_nonzero_rc_reports_none(self, host, idle, monkeypatch):
        monkeypatch.setattr(taps_mod.subprocess, 'run',
                            lambda *a, **k: MockCompletedProcess(1, ''))
        results = []
        host._check_tap_trust_thread('u/t', results.append)
        fn, args, _ = idle[-1]
        fn(*args)
        assert results == [None]

    def test_missing_brew_reports_none(self, host, idle, monkeypatch):
        def raise_fnf(*a, **k):
            raise FileNotFoundError('brew')

        monkeypatch.setattr(taps_mod.subprocess, 'run', raise_fnf)
        results = []
        host._check_tap_trust_thread('u/t', results.append)
        fn, args, _ = idle[-1]
        fn(*args)
        assert results == [None]

    def test_trust_tap_success(self, host, idle, fake_thread, monkeypatch):
        monkeypatch.setattr(taps_mod.subprocess, 'run',
                            lambda *a, **k: MockCompletedProcess(0, 'trusted ok'))
        monkeypatch.setattr(host, '_load_tap_packages', lambda: None)
        results = []
        host._trust_tap_thread('u/t', lambda ok, msg: results.append((ok, msg)))
        fn, args, _ = idle[-1]
        fn(*args)
        assert results == [(True, 'trusted ok')]

    def test_trust_tap_failure_message(self, host, idle, monkeypatch):
        monkeypatch.setattr(taps_mod.subprocess, 'run',
                            lambda *a, **k: MockCompletedProcess(1, '', 'denied'))
        results = []
        host._trust_tap_thread('u/t', lambda ok, msg: results.append((ok, msg)))
        fn, args, _ = idle[-1]
        fn(*args)
        assert results == [(False, 'denied')]

    def test_trust_tap_exception(self, host, idle, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError('bad')

        monkeypatch.setattr(taps_mod.subprocess, 'run', boom)
        results = []
        host._trust_tap_thread('u/t', lambda ok, msg: results.append((ok, msg)))
        fn, args, _ = idle[-1]
        fn(*args)
        assert results == [(False, 'bad')]

    def test_untrust_tap_success(self, host, idle, monkeypatch):
        monkeypatch.setattr(taps_mod.subprocess, 'run',
                            lambda *a, **k: MockCompletedProcess(0, 'removed'))
        results = []
        host._untrust_tap_thread('u/t', lambda ok, msg: results.append((ok, msg)))
        fn, args, _ = idle[-1]
        fn(*args)
        assert results == [(True, 'removed')]

    def test_load_trust_status_uses_tap_info(self, host, idle, monkeypatch):
        host._tap_list = [{'name': 'u/t', 'path': '/x'}, {'name': 'q/r', 'path': '/y'}]
        results = [
            MockCompletedProcess(0, json.dumps({'taps': ['v/w']})),       # trust --json
            MockCompletedProcess(0, json.dumps([{'trusted': True}])),     # tap-info u/t
            MockCompletedProcess(1, ''),                                   # tap-info q/r fails
        ]

        def fake_run(*a, **k):
            return results.pop(0)

        monkeypatch.setattr(taps_mod.subprocess, 'run', fake_run)
        host._load_tap_trust_status_thread()
        assert host._tap_list[0]['trusted'] is True   # from tap-info
        assert host._tap_list[1]['trusted'] is False  # not in trusted set
        assert len(idle) == 1  # taps-loaded re-emitted

    def test_load_trust_status_trust_failure_leaves_none(self, host, idle, monkeypatch):
        host._tap_list = [{'name': 'u/t', 'path': '/x'}]

        def fake_run(*a, **k):
            return MockCompletedProcess(1, '')

        monkeypatch.setattr(taps_mod.subprocess, 'run', fake_run)
        host._load_tap_trust_status_thread()
        assert host._tap_list[0]['trusted'] is None


# ─── tap add / remove ─────────────────────────────────────────────────────────

class TestTapOperations:
    def test_tap_success_reloads_packages(self, host, idle, fake_thread, monkeypatch):
        monkeypatch.setattr(taps_mod.subprocess, 'run',
                            lambda *a, **k: MockCompletedProcess(0, 'Tapped 1 formula'))
        results = []
        host._run_tap_operation('tap', 'u/t', lambda ok, msg: results.append((ok, msg)))
        fn, args, _ = idle[-1]
        fn(*args)
        assert results == [(True, 'Tapped 1 formula')]
        assert any(t.target == host._load_tap_packages for t in fake_thread)

    def test_tap_failure_no_reload(self, host, idle, fake_thread, monkeypatch):
        monkeypatch.setattr(taps_mod.subprocess, 'run',
                            lambda *a, **k: MockCompletedProcess(1, '', 'not found'))
        results = []
        host._run_tap_operation('tap', 'u/t', lambda ok, msg: results.append((ok, msg)))
        fn, args, _ = idle[-1]
        fn(*args)
        assert results == [(False, 'not found')]
        assert fake_thread == []

    def test_tap_exception(self, host, idle, monkeypatch):
        def boom(*a, **k):
            raise OSError('timeout')

        monkeypatch.setattr(taps_mod.subprocess, 'run', boom)
        results = []
        host._run_tap_operation('untap', 'u/t', lambda ok, msg: results.append((ok, msg)))
        fn, args, _ = idle[-1]
        fn(*args)
        assert results == [(False, 'timeout')]

    def test_untap_success(self, host, idle, fake_thread, monkeypatch):
        monkeypatch.setattr(taps_mod.subprocess, 'run',
                            lambda *a, **k: MockCompletedProcess(0, 'Untapped'))
        results = []
        host._run_tap_operation('untap', 'u/t', lambda ok, msg: results.append((ok, msg)))
        fn, args, _ = idle[-1]
        fn(*args)
        assert results == [(True, 'Untapped')]


# ─── tap metadata & update ────────────────────────────────────────────────────

class TestTapMetadata:
    def test_returns_git_metadata(self, host, tmp_path, monkeypatch):
        tap_path = tmp_path / 'tap'
        (tap_path / '.git').mkdir(parents=True)
        host._tap_list = [{'name': 'u/t', 'path': str(tap_path)}]
        git_results = [
            MockCompletedProcess(0, 'https://github.com/u/t.git\n'),
            MockCompletedProcess(0, 'abc1234\n'),
            MockCompletedProcess(0, '2026-01-01T00:00:00+00:00\n'),
        ]

        def fake_run(cmd, *a, **k):
            return git_results.pop(0)

        monkeypatch.setattr(taps_mod.subprocess, 'run', fake_run)
        meta = host.get_tap_metadata('u/t')
        assert meta == {
            'remote_url': 'https://github.com/u/t.git',
            'head_rev': 'abc1234',
            'last_commit_date': '2026-01-01T00:00:00+00:00',
        }

    def test_unknown_tap_returns_empty(self, host):
        assert host.get_tap_metadata('nope/tap') == {}

    def test_tap_without_git_dir_returns_empty(self, host, tmp_path):
        tap_path = tmp_path / 'tap'
        tap_path.mkdir()  # no .git subdir
        host._tap_list = [{'name': 'u/t', 'path': str(tap_path)}]
        assert host.get_tap_metadata('u/t') == {}

    def test_update_pulls_tap(self, host, idle, monkeypatch):
        host._tap_list = [{'name': 'u/t', 'path': '/somewhere'}]
        monkeypatch.setattr(taps_mod.subprocess, 'run',
                            lambda *a, **k: MockCompletedProcess(0, 'Already up to date.'))
        results = []
        host._run_tap_update('u/t', lambda ok, msg: results.append((ok, msg)))
        fn, args, _ = idle[-1]
        fn(*args)
        assert results == [(True, 'Already up to date.')]

    def test_update_unknown_tap_fails(self, host, idle):
        results = []
        host._run_tap_update('nope/tap', lambda ok, msg: results.append((ok, msg)))
        fn, args, _ = idle[-1]
        fn(*args)
        assert results == [(False, 'Tap nope/tap not installed')]
