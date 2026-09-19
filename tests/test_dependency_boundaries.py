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
