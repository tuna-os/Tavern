"""CacheMixin size and clear contracts against a temporary cache directory."""

from tavern.backend_cache import CacheMixin
from tavern.cache_policy import CacheManager


class CacheHarness(CacheMixin):
    def __init__(self, cache_dir):
        self._cache_dir = str(cache_dir)


def test_cache_size_bytes_counts_every_cached_file(tmp_path):
    host = CacheHarness(tmp_path)
    assert host.cache_size_bytes() == len(f"{CacheManager.SCHEMA_VERSION}\n")

    host._save_cache("formulae", [{"name": "git"}])
    (tmp_path / "icons").mkdir()
    (tmp_path / "icons" / "git.png").write_bytes(b"x" * 100)

    expected = sum(p.stat().st_size for p in tmp_path.rglob("*") if p.is_file())
    assert expected > 100
    assert host.cache_size_bytes() == expected


def test_cache_size_bytes_follows_cache_dir_changes(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    host = CacheHarness(first)
    host._save_cache("casks", ["a" * 50])
    first_size = host.cache_size_bytes()

    host._cache_dir = str(second)
    assert host.cache_size_bytes() < first_size
    assert host._cache_manager.root == second.resolve()


def test_clear_cache_removes_entries_and_restores_version_marker(tmp_path):
    host = CacheHarness(tmp_path)
    host._save_cache("formulae", [{"name": "git"}])
    nested = tmp_path / "screenshots" / "git"
    nested.mkdir(parents=True)
    (nested / "shot.png").write_bytes(b"png")

    host.clear_cache()

    assert tmp_path.is_dir()
    remaining = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert remaining == ["CACHE_VERSION"]
    marker = tmp_path / "CACHE_VERSION"
    assert marker.read_text(encoding="utf-8").strip() == str(CacheManager.SCHEMA_VERSION)
    assert host._load_cached("formulae") == (None, True)
    assert host.cache_size_bytes() == marker.stat().st_size


def test_clear_cache_on_empty_cache_is_idempotent(tmp_path):
    host = CacheHarness(tmp_path)
    host.clear_cache()
    host.clear_cache()
    assert [p.name for p in tmp_path.iterdir()] == ["CACHE_VERSION"]
