# test_cache_policy.py
# SPDX-License-Identifier: GPL-3.0-or-later

import ast
import json
import os
from pathlib import Path

import pytest

from tavern.cache_policy import CacheManager, cache_manager_for


def test_atomic_json_roundtrip(tmp_path):
    manager = CacheManager(tmp_path)
    path = tmp_path / 'catalog.json'
    manager.atomic_write_json(path, {'packages': ['git']})
    assert json.loads(path.read_text()) == {'packages': ['git']}


def test_quota_evicts_oldest_file(tmp_path):
    manager = CacheManager(tmp_path, max_bytes=12)
    old = tmp_path / 'old.bin'
    new = tmp_path / 'new.bin'
    manager.atomic_write_bytes(old, b'12345678')
    manager.atomic_write_bytes(new, b'abcdefgh')
    assert new.exists()
    assert not old.exists()


def test_clear_preserves_root(tmp_path):
    manager = CacheManager(tmp_path)
    manager.atomic_write_bytes(tmp_path / 'icon.png', b'png')
    manager.clear()
    assert tmp_path.exists()
    assert list(tmp_path.iterdir()) == []


def test_path_escape_is_rejected(tmp_path):
    manager = CacheManager(tmp_path / 'cache')
    with pytest.raises(ValueError):
        manager.atomic_write_bytes(tmp_path / 'outside', b'nope')


def test_manager_rebinds_when_owner_cache_directory_changes(tmp_path):
    class Owner:
        pass

    owner = Owner()
    owner._cache_dir = str(tmp_path / 'first')
    first = cache_manager_for(owner)
    owner._cache_dir = str(tmp_path / 'second')
    second = cache_manager_for(owner)
    assert first is not second
    assert second.root == (tmp_path / 'second').resolve()


def test_read_json_reports_stale_and_updates_access_time(tmp_path):
    manager = CacheManager(tmp_path)
    path = tmp_path / 'catalog.json'
    manager.atomic_write_json(path, {'packages': ['git']})
    assert manager.read_json(path, 60, now=path.stat().st_mtime + 30) == (
        {'packages': ['git']}, False,
    )
    assert manager.read_json(path, 60, now=path.stat().st_mtime + 90)[1] is True


def test_read_json_removes_corrupt_entry(tmp_path):
    manager = CacheManager(tmp_path)
    path = tmp_path / 'catalog.json'
    path.write_text('{broken', encoding='utf-8')
    assert manager.read_json(path, 60) == (None, True)
    assert not path.exists()


def test_reads_do_not_renew_download_freshness(tmp_path):
    manager = CacheManager(tmp_path)
    path = tmp_path / 'catalog.json'
    manager.atomic_write_json(path, {'packages': ['git']})
    os.utime(path, (1000, 1000))
    written_ns = path.stat().st_mtime_ns
    assert manager.read_json(path, 60, now=1050)[1] is False
    assert path.stat().st_atime > 1000
    assert path.stat().st_mtime_ns == written_ns
    assert manager.read_json(path, 60, now=1070)[1] is True
    assert path.stat().st_mtime_ns == written_ns


def test_cache_lifetimes_match_cache_md():
    from tavern import cache_policy

    # docs/CACHE.md states these numbers; a change here is a change there.
    assert cache_policy.CATALOG_TTL == 12 * 60 * 60
    assert cache_policy.CATALOG_BACKGROUND_REFRESH_AGE == 4 * 60 * 60
    assert cache_policy.CURATION_TTL == 6 * 60 * 60
    assert cache_policy.ANALYTICS_TTL == 24 * 60 * 60
    assert cache_policy.POPULAR_TAPS_TTL == 24 * 60 * 60
    assert cache_policy.VERSION_HISTORY_TTL == 24 * 60 * 60


def _numeric_cache_ages(tree):
    """Yield the line of each ``max_age=`` argument that is a number, not a name."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != 'max_age':
                continue
            literals = [
                n for n in ast.walk(keyword.value)
                if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
            ]
            names = [n for n in ast.walk(keyword.value) if isinstance(n, (ast.Name, ast.Attribute))]
            if literals and not names:
                yield keyword.value.lineno


def test_cache_reads_use_a_named_lifetime():
    # Each catalog lifetime was once a literal repeated at several call sites,
    # and docs/CACHE.md described only one of them. A cache read names its
    # lifetime from cache_policy.py so that one place holds each rule.
    source_dir = Path(__file__).parents[1] / 'src'
    violations = []
    for path in sorted(source_dir.glob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        violations.extend(f'{path.name}:{line}' for line in _numeric_cache_ages(tree))

    assert not violations, (
        'max_age= is a number (name it in cache_policy.py): ' + ', '.join(violations)
    )


def test_numeric_cache_age_check_reports_literals_only():
    source = '\n'.join((
        "load('a', max_age=43200)",
        "load('b', max_age=12 * 60 * 60)",
        "load('c', max_age=CATALOG_TTL)",
        "load('d', max_age=2 * HOUR)",
        "load('e', max_age=cache_policy.CURATION_TTL)",
    ))
    assert list(_numeric_cache_ages(ast.parse(source))) == [1, 2]
