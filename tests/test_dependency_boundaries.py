"""Architecture checks for dependency direction between backend modules."""

import ast
from pathlib import Path


BACKEND_LEAVES = (
    'backend_cache.py',
    'backend_remote.py',
    'backend_state.py',
    'backend_ui.py',
    'media.py',
    'taps.py',
)


def test_backend_leaves_do_not_import_composition_root():
    source_dir = Path(__file__).parents[1] / 'src'
    violations = []

    for filename in BACKEND_LEAVES:
        tree = ast.parse((source_dir / filename).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (
                node.module == 'backend'
                or (node.level and any(alias.name == 'backend' for alias in node.names))
            ):
                violations.append(f'{filename}:{node.lineno}')
            elif isinstance(node, ast.Import) and any(
                alias.name in {'backend', 'tavern.backend'} for alias in node.names
            ):
                violations.append(f'{filename}:{node.lineno}')

    assert not violations, 'backend leaf imports composition root: ' + ', '.join(violations)


# docs/ARCHITECTURE.md: the backend is the only layer that uses the network.
# A module that imports Gtk or Adw is a UI module and must not open sockets or
# HTTP connections itself; it calls a backend method instead.
NETWORK_MODULES = {'urllib.request', 'http.client', 'socket'}


def _imports_ui_toolkit(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == 'gi.repository':
            if any(alias.name in {'Gtk', 'Adw'} for alias in node.names):
                return True
    return False


def test_ui_modules_do_not_import_network_libraries():
    source_dir = Path(__file__).parents[1] / 'src'
    violations = []

    for path in sorted(source_dir.glob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        if not _imports_ui_toolkit(tree):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in NETWORK_MODULES:
                violations.append(f'{path.name}:{node.lineno}')
            elif isinstance(node, ast.Import) and any(
                alias.name in NETWORK_MODULES for alias in node.names
            ):
                violations.append(f'{path.name}:{node.lineno}')

    assert not violations, 'UI module imports a network library: ' + ', '.join(violations)


# docs/ARCHITECTURE.md: the backend is the only layer that runs `brew`. A UI
# module that needs a read-only command gets the runner that PageFactory owns
# (a constructor argument, `set_runner`, or `runner=` on show_command). It does
# not import the functions that build or run a brew command line.
BREW_EXECUTION = {
    'brew_commands': {'run_read'},
    'brew_env': {'build_command', 'command_env'},
}


def test_ui_modules_do_not_run_brew():
    source_dir = Path(__file__).parents[1] / 'src'
    violations = []

    for path in sorted(source_dir.glob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        if not _imports_ui_toolkit(tree):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            forbidden = BREW_EXECUTION.get(node.module.rsplit('.', 1)[-1], set())
            for alias in node.names:
                if alias.name in forbidden:
                    violations.append(f'{path.name}:{node.lineno} imports {alias.name}')

    assert not violations, 'UI module runs brew directly: ' + ', '.join(violations)
