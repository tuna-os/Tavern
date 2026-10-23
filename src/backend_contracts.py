# backend_contracts.py - Explicit contracts between backend collaborators
# SPDX-License-Identifier: GPL-3.0-or-later
"""Protocols for collaborators that cross the backend boundary.

The backend is composed from mixins, but operations such as package tasks also
need a small part of its state API. Keeping that contract here prevents callers
from reaching into BrewBackend's private CatalogStore-backed fields.
"""

from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    from .package import Package


class PackageStateBackend(Protocol):
    """The backend state operation required by :class:`TaskManager`."""

    def set_package_installed(self, package: "Package", installed: bool) -> None:
        """Record package state in both the model and backend catalog."""


# ─── Mixin public contracts ─────────────────────────────────────────────────
# BrewBackend is one GObject composed from six mixins, so callers see only
# BrewBackend. These Protocols name each mixin's *public* surface — the methods
# the UI, TaskManager, and Brewfile loader actually call — so the contract is
# explicit instead of inferred from ``self.<method>`` calls scattered across six
# modules (tuna-os/Tavern#240). The ``MIXIN_DEPENDENCIES`` table below is the
# explicit form of the rest of that finding: the cross-mixin coupling that used
# to be invisible inside those same ``self._fetch_json`` / ``self._load_cached``
# / ``self._formulae`` references.

class StateContract(Protocol):
    """Public surface of :class:`tavern.backend_state.StateMixin`."""

    def installed_names(self, pkg_type: str) -> frozenset[str]: ...
    def get_installed_packages(self) -> list["Package"]: ...
    def is_pinned(self, name: str) -> bool: ...
    def get_pinned(self) -> set[str]: ...
    def pin_async(self, package: "Package", callback=None) -> None: ...
    def unpin_async(self, package: "Package", callback=None) -> None: ...


class CacheContract(Protocol):
    """Public surface of :class:`tavern.backend_cache.CacheMixin`."""

    def parse_brewfile(self, path: str) -> dict: ...
    def refresh_cache_files(self) -> None: ...
    def cache_size_bytes(self) -> int: ...
    def clear_cache(self) -> None: ...


class RemoteContract(Protocol):
    """Public surface of :class:`tavern.backend_remote.RemoteMixin`."""

    def get_curation(self) -> dict: ...
    def get_curation_async(self, callback) -> None: ...
    def get_flatpak_info(self, app_id: str) -> dict | None: ...
    def get_version_history(self, package_name: str, pkg_type: str = "formula") -> list: ...
    def get_package_info(self, name: str, pkg_type: str = "formula") -> dict | None: ...
    def get_package_info_async(self, package, callback) -> None: ...
    def get_related_packages(self, package, limit: int = 6) -> list["Package"]: ...
    def get_variants(self, package, limit: int = 6) -> list["Package"]: ...


class UiContract(Protocol):
    """Public surface of :class:`tavern.backend_ui.UiMixin`."""

    def load_all_async(self) -> None: ...
    def refresh_installed_async(self) -> None: ...
    def search_async(self, query: str, pkg_type, callback) -> None: ...
    def search(self, query: str, pkg_type=None) -> list["Package"]: ...


class TapsContract(Protocol):
    """Public surface of :class:`tavern.taps.TapsMixin`."""

    def fetch_popular_taps_async(self, callback) -> None: ...
    def check_tap_trust_async(self, tap_name: str, callback) -> None: ...
    def trust_tap_async(self, tap_name: str, callback=None) -> None: ...
    def untrust_tap_async(self, tap_name: str, callback=None) -> None: ...
    def tap_async(self, tap_name: str, callback=None) -> None: ...
    def untap_async(self, tap_name: str, callback=None) -> None: ...
    def get_tap_metadata(self, tap_name: str) -> dict | None: ...
    def update_tap_async(self, tap_name: str, callback=None) -> None: ...


class MediaContract(Protocol):
    """Public surface of :class:`tavern.media.MediaMixin`."""

    def fetch_icon_async(self, package, callback) -> None: ...
    def fetch_screenshot_async(self, package, callback) -> None: ...
    def fetch_readme_async(self, package, callback) -> None: ...


# ─── Registry ────────────────────────────────────────────────────────────────
# Maps each composed mixin to its public contract and to the collaborators it
# depends on. Collaborator names live in this fixed universe: the other mixins,
# the single CatalogStore that owns the shared catalog state, and BrewBackend
# itself for the GObject plumbing (``emit``, ``_cache_dir``, executors,
# properties) that no mixin can own in isolation.

MIXIN_MODULES: Final[dict[str, str]] = {
    "StateMixin": "tavern.backend_state",
    "CacheMixin": "tavern.backend_cache",
    "RemoteMixin": "tavern.backend_remote",
    "UiMixin": "tavern.backend_ui",
    "TapsMixin": "tavern.taps",
    "MediaMixin": "tavern.media",
}

MIXIN_CONTRACTS: Final[dict[str, type[Protocol]]] = {
    "StateMixin": StateContract,
    "CacheMixin": CacheContract,
    "RemoteMixin": RemoteContract,
    "UiMixin": UiContract,
    "TapsMixin": TapsContract,
    "MediaMixin": MediaContract,
}

MIXIN_DEPENDENCIES: Final[dict[str, tuple[str, ...]]] = {
    "StateMixin": ("CatalogStore",),
    "CacheMixin": ("CatalogStore", "RemoteMixin", "UiMixin"),
    "RemoteMixin": ("CacheMixin", "CatalogStore", "UiMixin"),
    "UiMixin": ("CacheMixin", "CatalogStore", "RemoteMixin", "StateMixin", "TapsMixin"),
    "TapsMixin": ("CacheMixin", "CatalogStore"),
    "MediaMixin": ("BrewBackend", "CatalogStore"),
}

_MIXIN_NAMES = frozenset(MIXIN_CONTRACTS)
_COLLABORATOR_NAMES = frozenset({"BrewBackend", "CatalogStore", *_MIXIN_NAMES})


def mixin_contracts() -> dict[str, type[Protocol]]:
    """Return a copy of the mixin → public-contract registry."""
    return dict(MIXIN_CONTRACTS)


def mixin_dependencies() -> dict[str, tuple[str, ...]]:
    """Return a copy of the mixin → collaborator dependency table."""
    return dict(MIXIN_DEPENDENCIES)


_PROTOCOL_INTERNALS = frozenset({
    "_is_protocol", "_is_runtime_protocol", "_abc_impl",
    "__abstractmethods__", "__protocol_attrs__",
})


def _protocol_members(proto: type[Protocol]) -> list[str]:
    """Public member names declared on a Protocol, version-agnostic.

    ``typing.Protocol`` exposes ``__protocol_attrs__`` from CPython 3.13; fall
    back to scanning ``__mro__`` for older interpreters.
    """
    attrs = getattr(proto, "__protocol_attrs__", None)
    if attrs:
        return sorted(attrs)
    names: set[str] = set()
    for cls in proto.__mro__:
        names.update(vars(cls))
    return sorted(n for n in names if not n.startswith("__") and n not in _PROTOCOL_INTERNALS)


def assert_backend_satisfies_contracts(backend) -> None:
    """Runtime check that ``backend`` exposes every mixin's public contract.

    Structural only — no ``gi`` import — so it runs wherever the composed object
    exists. Catches a mixin dropping a public method or a composition forgetting
    to wire it in, which is the silent-coupling failure tuna-os/Tavern#240
    reports.
    """
    failures = []
    for name, contract in MIXIN_CONTRACTS.items():
        missing = [m for m in _protocol_members(contract) if not hasattr(backend, m)]
        if missing:
            failures.append(f"{name}: backend missing {missing}")
    if failures:
        raise AssertionError(
            "BrewBackend does not satisfy mixin contracts:\n  " + "\n  ".join(failures)
        )
