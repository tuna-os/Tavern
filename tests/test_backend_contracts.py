# test_backend_contracts.py - Contract tests for backend_contracts.py
# SPDX-License-Identifier: GPL-3.0-or-later
# Verifies each mixin's public method set matches its declared contract and that
# the composed BrewBackend satisfies every contract (tuna-os/Tavern#240).
import ast
import pathlib
import threading
from types import SimpleNamespace

import pytest

import tavern.backend_contracts as contracts

# Source path for each mixin, keyed by the mixin name used in the registry.
_MIXIN_FILES = {
    "StateMixin": "backend_state.py",
    "CacheMixin": "backend_cache.py",
    "RemoteMixin": "backend_remote.py",
    "UiMixin": "backend_ui.py",
    "TapsMixin": "taps.py",
    "MediaMixin": "media.py",
}


def _source_path(name):
    return pathlib.Path(__file__).parent.parent / "src" / _MIXIN_FILES[name]


def _public_methods(source_path):
    """Public (non-underscore) method names declared on a mixin class."""
    tree = ast.parse(source_path.read_text())
    methods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.add(item.name)
    return {m for m in methods if not m.startswith("_")}


# ── Pure-source contract coverage (no GObject, no brew) ──────────────────────

@pytest.mark.parametrize("name", sorted(contracts.MIXIN_CONTRACTS))
def test_public_methods_match_contract(name):
    """The contract names exactly the mixin's public methods — no more, no less.

    A mixin that gains a public method without its contract updating, or a
    contract that names a method the mixin no longer defines, both fail here.
    """
    declared = set(contracts._protocol_members(contracts.MIXIN_CONTRACTS[name]))
    actual = _public_methods(_source_path(name))
    missing = declared - actual  # contract names a method the mixin lacks
    extra = actual - declared  # mixin has a public method no contract names
    assert not missing, f"{name} contract names methods the mixin does not define: {sorted(missing)}"
    assert not extra, f"{name} has public methods no contract names: {sorted(extra)}"


def test_dependency_names_are_real_collaborators():
    for name, deps in contracts.MIXIN_DEPENDENCIES.items():
        for dep in deps:
            assert dep in contracts._COLLABORATOR_NAMES, (
                f"{name} depends on unknown collaborator {dep!r}"
            )


def test_dependency_table_covers_every_composed_mixin():
    assert set(contracts.MIXIN_DEPENDENCIES) == set(contracts.MIXIN_CONTRACTS)


def test_no_mixin_depends_on_itself():
    for name, deps in contracts.MIXIN_DEPENDENCIES.items():
        assert name not in deps, f"{name} lists itself as a dependency"


def test_dependency_map_records_every_cross_mixin_method_call():
    """Every ``self.<method>`` call that resolves to another mixin is recorded.

    Guards the coupling the issue makes explicit: a mixin calling a private
    helper in another mixin must list that mixin as a collaborator, so the
    dependency is visible instead of hidden inside ``self._fetch_json``.
    """
    owner = {}  # method name -> set of mixins that define it (any nesting)
    for name in contracts.MIXIN_CONTRACTS:
        for node in ast.walk(ast.parse(_source_path(name).read_text())):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                owner.setdefault(node.name, set()).add(name)
    for name in contracts.MIXIN_CONTRACTS:
        tree = ast.parse(_source_path(name).read_text())
        called = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        }
        required = {
            owner_mixin
            for attr in called
            for owner_mixin in owner.get(attr, ())
            if owner_mixin != name
        }
        missing = required - set(contracts.MIXIN_DEPENDENCIES[name])
        assert not missing, (
            f"{name} calls {sorted(required)} from other mixins but records "
            f"{sorted(contracts.MIXIN_DEPENDENCIES[name])}"
        )


# ── Composition: BrewBackend wires every contract ────────────────────────────

def test_brewbackend_satisfies_its_contract(tmp_path, monkeypatch):
    """A real BrewBackend implements its declared contract, proving the
    interface holds at runtime, not just in the type stubs."""
    from gi.repository import GLib
    from tavern.backend import BrewBackend

    monkeypatch.setattr(GLib, "get_user_cache_dir", lambda: str(tmp_path))
    backend = BrewBackend()
    contracts.assert_backend_satisfies_contracts(backend)


# ── Isolation: a mixin runs with injected collaborators ──────────────────────

def test_state_mixin_runs_with_a_fake_host():
    """A mixin's core method works against an injected host, no BrewBackend."""
    from tavern.backend_state import StateMixin

    host = SimpleNamespace(_pinned={"git"}, _pinned_lock=threading.Lock())
    snapshot = StateMixin.get_pinned(host)
    snapshot.clear()
    assert host._pinned == {"git"}  # get_pinned returned a defensive copy
