# test_cache_policy.py
# SPDX-License-Identifier: GPL-3.0-or-later

import json

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
