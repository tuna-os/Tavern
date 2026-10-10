# Copyright 2025 Tavern Contributors licensed under the MPL-2.0
"""Construction and contract tests for :class:`CatalogStore`.

The store is deliberately free of any ``gi``/GObject dependency so these tests
run under a plain interpreter (no display, no libadwaita). They double as a
standalone script: ``python3 tests/test_catalog_store.py``.
"""

import sys
import threading

from catalog_store import CatalogStore


def test_independently_constructible():
    store = CatalogStore()
    assert isinstance(store, CatalogStore)


def test_defaults_are_empty():
    store = CatalogStore()
    assert store.get_formulae() == []
    assert store.get_casks() == []
    assert store.get_installed_formulae() == set()
    assert store.get_installed_casks() == set()
    assert store.get_pinned() == set()
    assert store.get_outdated_formulae() == {}
    assert store.get_outdated_casks() == {}
    assert store.get_tap_packages() == {}
    assert store.get_tap_list() == []


def test_set_formulae_copies_input_in():
    store = CatalogStore()
    formulae = [{"name": "ripgrep"}, {"name": "fd"}]
    store.set_formulae(formulae)
    # Mutating the caller's list afterwards must not leak into the store.
    formulae.append({"name": "bat"})
    assert [f["name"] for f in store.get_formulae()] == ["ripgrep", "fd"]


def test_set_casks_copies_input_in():
    store = CatalogStore()
    store.set_casks(["git", "wget"])
    assert store.get_casks() == ["git", "wget"]


def test_set_installed_replaces_both_sets():
    store = CatalogStore()
    store.set_installed({"a", "b"}, {"c"})
    assert store.get_installed_formulae() == {"a", "b"}
    assert store.get_installed_casks() == {"c"}
    store.set_installed({"d"}, {"e", "f"})
    assert store.get_installed_formulae() == {"d"}
    assert store.get_installed_casks() == {"e", "f"}


def test_pinned_roundtrip_and_is_pinned():
    store = CatalogStore()
    store.set_pinned({"git", "wget"})
    assert store.is_pinned("git") is True
    assert store.is_pinned("fd") is False
    store.set_pinned({"ripgrep"})
    assert store.is_pinned("ripgrep") is True
    assert store.is_pinned("git") is False


def test_outdated_roundtrip():
    store = CatalogStore()
    store.set_outdated({"ripgrep": {"installed": "1.0", "latest": "2.0"}}, {})
    assert store.get_outdated_formulae()["ripgrep"]["latest"] == "2.0"
    assert store.get_outdated_casks() == {}


def test_tap_packages_and_list():
    store = CatalogStore()
    packages = {"homebrew/core": [{"name": "git"}, {"name": "wget"}]}
    store.set_tap_packages(packages)
    assert store.get_tap_packages()["homebrew/core"] == [{"name": "git"}, {"name": "wget"}]
    store.set_tap_list([{"name": "homebrew/core", "path": "/x"}])
    assert store.get_tap_list() == [{"name": "homebrew/core", "path": "/x"}]


def test_set_tap_packages_copies_inputs_in():
    store = CatalogStore()
    packages = {"homebrew/core": [{"name": "git"}]}
    store.set_tap_packages(packages)
    packages["homebrew/core"].append({"name": "bat"})
    packages["extra"] = [{"name": "wget"}]
    assert list(store.get_tap_packages()) == ["homebrew/core"]
    assert len(store.get_tap_packages()["homebrew/core"]) == 1


def test_pinned_and_outdated_locks_are_the_same_reentrant_lock():
    store = CatalogStore()
    # The store owns a single lock; exposing it under both historical names keeps
    # the mixin ``with self._pinned_lock`` / ``with self._outdated_lock`` blocks
    # synchronized against the store's own methods.
    assert store.pinned_lock is store.outdated_lock
    assert isinstance(store.pinned_lock, type(threading.RLock()))


def test_concurrent_writes_do_not_corrupt_state():
    store = CatalogStore()
    errors = []

    def worker(n):
        try:
            for i in range(200):
                store.set_pinned({"git", "wget", f"pkg-{i % 7}"})
                store.set_outdated({f"pkg-{i % 7}": {"installed": "1"}}, {})
                store.set_formulae([{"name": f"pkg-{i % 7}"}])
        except Exception as exc:  # pragma: no cover - surfaced via assert below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    # Whatever the last writer set, the store must hold a single consistent view.
    formulae = store.get_formulae()
    assert isinstance(formulae, list)
    assert all(isinstance(f, dict) and "name" in f for f in formulae)
    assert isinstance(store.get_pinned(), set)
    assert isinstance(store.get_outdated_formulae(), dict)


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001 - report and continue
            failures += 1
            print(f"FAIL {test.__name__}: {exc!r}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return failures


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)
