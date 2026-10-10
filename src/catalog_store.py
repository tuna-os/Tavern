# Copyright 2025 Tavern Contributors licensed under the MPL-2.0
"""Thread-safe owner of the backend catalog and package state.

Historically the ``BrewBackend`` facade spread its mutable state across several
mixins (formulae, casks, installed, pinned, outdated, tap data), each guarded by
its own lock and mutated directly from many call sites. :class:`CatalogStore`
collapses that into one independently constructible, thread-safe component that
owns the data behind synchronized methods.

This is stage 1 of tuna-os/Tavern#172: give the shared backend state a single
explicit owner. The store is intentionally free of any ``gi``/GObject dependency
so it can be unit-tested in isolation.
"""

import threading


class CatalogStore:
    """Owns the backend catalog and package state behind synchronized methods.

    All public methods take and hold an internal re-entrant lock, so the store
    is safe to share across the backend's worker threads. Reads return the live
    container (grabbed under the lock); callers that need an immutable snapshot
    must copy it, mirroring the pre-existing behavior at the public API
    boundary.
    """

    def __init__(self):
        # Re-entrant so a caller that already holds the lock (e.g. a mixin
        # ``with self._pinned_lock`` block that then writes through a property
        # setter) can call back into the store without deadlocking.
        self._lock = threading.RLock()
        self._formulae = []
        self._casks = []
        self._installed_formulae = set()
        self._installed_casks = set()
        self._pinned = set()
        self._outdated_formulae = {}
        self._outdated_casks = {}
        self._tap_packages = {}
        self._tap_list = []

    # -- catalog ------------------------------------------------------------

    def set_formulae(self, value):
        with self._lock:
            self._formulae = list(value)

    def get_formulae(self):
        with self._lock:
            return self._formulae

    def set_casks(self, value):
        with self._lock:
            self._casks = list(value)

    def get_casks(self):
        with self._lock:
            return self._casks

    # -- installed ----------------------------------------------------------

    def set_installed(self, formulae, casks):
        with self._lock:
            self._installed_formulae = set(formulae)
            self._installed_casks = set(casks)

    def get_installed_formulae(self):
        with self._lock:
            return self._installed_formulae

    def get_installed_casks(self):
        with self._lock:
            return self._installed_casks

    # -- pinned -------------------------------------------------------------

    def set_pinned(self, value):
        with self._lock:
            self._pinned = set(value)

    def get_pinned(self):
        with self._lock:
            return self._pinned

    def is_pinned(self, name):
        with self._lock:
            return name in self._pinned

    @property
    def pinned_lock(self):
        return self._lock

    # -- outdated -----------------------------------------------------------

    def set_outdated(self, formulae, casks):
        with self._lock:
            self._outdated_formulae = dict(formulae)
            self._outdated_casks = dict(casks)

    def get_outdated_formulae(self):
        with self._lock:
            return self._outdated_formulae

    def get_outdated_casks(self):
        with self._lock:
            return self._outdated_casks

    @property
    def outdated_lock(self):
        return self._lock

    # -- tap data -----------------------------------------------------------

    def set_tap_packages(self, value):
        with self._lock:
            self._tap_packages = {tap: list(pkgs) for tap, pkgs in value.items()}

    def get_tap_packages(self):
        with self._lock:
            return self._tap_packages

    def set_tap_list(self, value):
        with self._lock:
            self._tap_list = list(value)

    def get_tap_list(self):
        with self._lock:
            return self._tap_list
