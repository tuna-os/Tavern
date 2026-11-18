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


# docs/ARCHITECTURE.md: the modules in the `backend` layer. The UI depends on
# the backend, never the reverse. A rule the UI and the backend both need goes
# in a module without GTK (as flatpak_app_id.py does), not in a UI module.
BACKEND_MODULES = BACKEND_LEAVES + (
    'backend.py',
    'backend_contracts.py',
    'backend_icons.py',
    'catalog_store.py',
    'git_forge.py',
    'url_security.py',
)


def _relative_imports(tree):
    """Yield (line, module) for each `from .x import ...` / `from . import x` in ``tree``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            if node.module:
                yield node.lineno, node.module.split('.')[0]
            else:
                for alias in node.names:
                    yield node.lineno, alias.name


def test_backend_modules_do_not_import_ui_modules():
    source_dir = Path(__file__).parents[1] / 'src'
    ui_modules = {
        path.stem
        for path in source_dir.glob('*.py')
        if _imports_ui_toolkit(ast.parse(path.read_text(encoding='utf-8')))
    }
    violations = []

    for filename in BACKEND_MODULES:
        tree = ast.parse((source_dir / filename).read_text(encoding='utf-8'))
        if _imports_ui_toolkit(tree):
            violations.append(f'{filename} imports Gtk or Adw')
        violations.extend(
            f'{filename}:{line} imports {module}'
            for line, module in _relative_imports(tree)
            if module in ui_modules
        )

    assert not violations, 'backend module depends on the UI: ' + ', '.join(violations)


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


# docs/ARCHITECTURE.md: external_links.py is the only module that gives a URI
# to the desktop. The desktop opens a URI with the application that claims its
# scheme, so text from a README, a tap or a Brewfile must not get there
# unchecked. Each fix of that kind was made at one call site and the next
# finding was a call site the fix did not cover (#351, #357, #367), so no other
# module may name a launcher API at all.
LAUNCHER_MODULE = 'external_links.py'
LAUNCHER_NAMES = {
    'UriLauncher',
    'LinkButton',
    'show_uri',
    'launch_default_for_uri',
    'launch_default_for_uri_async',
    'webbrowser',
}
LAUNCHER_COMMAND = 'xdg-open'


def _launcher_uses(tree):
    """Yield (line, name) for each launcher API or command named in ``tree``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in LAUNCHER_NAMES:
            yield node.lineno, node.attr
        elif isinstance(node, ast.Name) and node.id in LAUNCHER_NAMES:
            yield node.lineno, node.id
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split('.')[0] in LAUNCHER_NAMES:
                    yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            if (node.module or '').split('.')[0] in LAUNCHER_NAMES:
                yield node.lineno, node.module
            for alias in node.names:
                if alias.name in LAUNCHER_NAMES:
                    yield node.lineno, alias.name
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # getattr(Gtk, 'UriLauncher'), or a command line as a list or a string.
            if node.value in LAUNCHER_NAMES or node.value.split()[:1] == [LAUNCHER_COMMAND]:
                yield node.lineno, node.value


def test_only_external_links_module_reaches_the_desktop_launcher():
    source_dir = Path(__file__).parents[1] / 'src'
    violations = []

    for path in sorted(source_dir.glob('*.py')):
        if path.name == LAUNCHER_MODULE:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        violations.extend(f'{path.name}:{line} {name}' for line, name in _launcher_uses(tree))

    # Blueprint can declare a link button without any Python.
    for path in sorted(source_dir.glob('*.blp')):
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if 'LinkButton' in line:
                violations.append(f'{path.name}:{number} LinkButton')

    assert not violations, (
        'launcher API outside external_links.py (call its functions instead): '
        + ', '.join(violations)
    )


def test_launcher_check_reports_each_way_to_reach_a_launcher():
    source = '\n'.join((
        'import webbrowser',
        'from gi.repository.Gtk import UriLauncher',
        'Gtk.UriLauncher.new(uri).launch(None, None, None, None)',
        "getattr(Gtk, 'UriLauncher')",
        "Gtk.LinkButton.new_with_label(uri, 'Open')",
        'Gtk.show_uri(None, uri, 0)',
        'Gio.AppInfo.launch_default_for_uri(uri, None)',
        "subprocess.Popen(['xdg-open', uri])",
        "subprocess.run('xdg-open ' + uri, shell=True)",
    ))
    lines = {line for line, _name in _launcher_uses(ast.parse(source))}
    assert lines == set(range(1, 10))

    harmless = "subprocess.run(['brew', 'doctor'])\nlabel = 'Open the link'\n"
    assert not list(_launcher_uses(ast.parse(harmless)))
