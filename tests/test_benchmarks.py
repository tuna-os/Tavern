# test_benchmarks.py - Performance benchmarks for Tavern
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Run with: pytest tests/test_benchmarks.py --benchmark-enable -v
# (pytest-benchmark disables benchmarks by default in normal runs)

import json
import os
import time

import pytest

from gi.repository import GLib
from tavern.backend import Package, BrewBackend
from tavern.logging_util import init_logging, get_logger, profile, log_timing


# ─── Package construction ────────────────────────────────────────────────────

class TestPackageBenchmarks:
    def test_formula_construction_500(self, benchmark, large_formula_list):
        """Benchmark creating 500 Package objects from formula data."""
        def create_all():
            return [Package(d, 'formula') for d in large_formula_list]
        result = benchmark(create_all)
        assert len(result) == 500

    def test_cask_construction_500(self, benchmark, large_cask_list):
        """Benchmark creating 500 Package objects from cask data."""
        def create_all():
            return [Package(d, 'cask') for d in large_cask_list]
        result = benchmark(create_all)
        assert len(result) == 500

    def test_formula_construction_with_installed_check(self, benchmark, large_formula_list):
        """Benchmark Package creation with installed-set lookups."""
        installed = {f'pkg-{i:04d}' for i in range(0, 500, 3)}  # every 3rd
        def create_all():
            return [Package(d, 'formula', installed) for d in large_formula_list]
        result = benchmark(create_all)
        installed_count = sum(1 for p in result if p.installed)
        assert installed_count > 0


# ─── Search ──────────────────────────────────────────────────────────────────

class TestSearchBenchmarks:
    @pytest.fixture()
    def loaded_backend(self, tmp_path, monkeypatch, large_formula_list, large_cask_list):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        backend._formulae = [Package(d, 'formula') for d in large_formula_list]
        backend._casks = [Package(d, 'cask') for d in large_cask_list]
        return backend

    def test_search_short_query(self, benchmark, loaded_backend):
        """Benchmark search with a short common query across 1000 packages."""
        result = benchmark(loaded_backend.search, 'pkg')
        assert len(result) > 0

    def test_search_no_results(self, benchmark, loaded_backend):
        """Benchmark search that yields zero results."""
        result = benchmark(loaded_backend.search, 'zzzznonexistent')
        assert len(result) == 0

    def test_search_description_match(self, benchmark, loaded_backend):
        """Benchmark search matching description text."""
        result = benchmark(loaded_backend.search, 'Test package number 42')
        assert len(result) >= 1

    def test_search_formula_filter(self, benchmark, loaded_backend):
        """Benchmark search with type filter."""
        result = benchmark(loaded_backend.search, 'pkg', 'formula')
        assert all(r.pkg_type == 'formula' for r in result)


# ─── Cache I/O ───────────────────────────────────────────────────────────────

class TestCacheBenchmarks:
    def test_cache_write_500_items(self, benchmark, tmp_path, monkeypatch, large_formula_list):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        benchmark(backend._save_cache, 'bench_formulae', large_formula_list)

    def test_cache_read_500_items(self, benchmark, tmp_path, monkeypatch, large_formula_list):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        backend._save_cache('bench_formulae', large_formula_list)
        def load():
            return backend._load_cached('bench_formulae')
        data, stale = benchmark(load)
        assert data is not None
        assert len(data) == 500


# ─── Brewfile parsing ────────────────────────────────────────────────────────

class TestBrewfileBenchmarks:
    def test_parse_large_brewfile(self, benchmark, tmp_path, monkeypatch):
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        lines = ['tap "homebrew/core"\n']
        for i in range(200):
            lines.append(f'brew "formula-{i}"\n')
        for i in range(100):
            lines.append(f'cask "cask-{i}"\n')
        bf = tmp_path / 'big.Brewfile'
        bf.write_text(''.join(lines))
        result = benchmark(backend.parse_brewfile, str(bf))
        assert len(result['formulae']) == 200
        assert len(result['casks']) == 100


# ─── Logging overhead ───────────────────────────────────────────────────────

class TestLoggingOverhead:
    """Measure the overhead of logging calls when logging is *disabled*
    (the default state) — these should be essentially free."""

    def test_disabled_logger_info_call(self, benchmark, monkeypatch):
        """Calling logger.info() 1000× with logging off."""
        monkeypatch.delenv('TAVERN_LOG', raising=False)
        monkeypatch.delenv('TAVERN_PROFILE', raising=False)
        import tavern.logging_util as lu
        lu._initialized = False
        lu._profiling_enabled = False
        import logging
        root = logging.getLogger('Tavern')
        root.handlers.clear()
        root.setLevel(logging.WARNING)
        init_logging()
        log = get_logger('bench')

        def many_logs():
            for i in range(1000):
                log.info('message %d with %s', i, 'args')

        benchmark(many_logs)

    def test_profile_decorator_disabled(self, benchmark, monkeypatch):
        """Calling a @profile-decorated function 1000× with profiling off."""
        monkeypatch.delenv('TAVERN_PROFILE', raising=False)
        monkeypatch.delenv('TAVERN_LOG', raising=False)
        import tavern.logging_util as lu
        lu._initialized = False
        lu._profiling_enabled = False

        @profile
        def noop():
            return 1

        def many_calls():
            for _ in range(1000):
                noop()

        benchmark(many_calls)

    def test_log_timing_disabled(self, benchmark, monkeypatch):
        """Using log_timing context manager 1000× with profiling off."""
        monkeypatch.delenv('TAVERN_PROFILE', raising=False)
        monkeypatch.delenv('TAVERN_LOG', raising=False)
        import tavern.logging_util as lu
        lu._initialized = False
        lu._profiling_enabled = False

        def many_timings():
            for _ in range(1000):
                with log_timing('bench'):
                    pass

        benchmark(many_timings)


# ─── .rb file parsing ───────────────────────────────────────────────────────

class TestRbParsingBenchmarks:
    def test_parse_formula_rb_50_files(self, benchmark, tmp_path, monkeypatch):
        """Benchmark parsing 50 .rb formula files."""
        monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
        backend = BrewBackend()
        # Create 50 .rb files
        rb_dir = tmp_path / 'Formula'
        rb_dir.mkdir()
        for i in range(50):
            (rb_dir / f'pkg{i}.rb').write_text(f'''\
class Pkg{i} < Formula
  desc "Package number {i}"
  homepage "https://example.com/pkg{i}"
  version "{i}.0.0"
  license "MIT"
  url "https://example.com/pkg{i}-{i}.0.0.tar.gz"
end
''')
        paths = [str(rb_dir / f'pkg{i}.rb') for i in range(50)]

        def parse_all():
            results = []
            for p in paths:
                name = os.path.basename(p)[:-3]
                results.append(backend._minimal_formula_data_from_rb(p, 'test/tap', name))
            return results

        result = benchmark(parse_all)
        assert all(r is not None for r in result)
        assert len(result) == 50
