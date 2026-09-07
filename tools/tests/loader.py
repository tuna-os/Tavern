# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared module loader for tools/tests/ — kept gi-free on purpose.

tests/conftest.py imports gi at collection time, which this sandbox (and any
host without PyGObject) cannot satisfy. Loading tools/*.py scripts by file
path here avoids depending on that conftest.py entirely.
"""
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_module(relative_path, name):
    path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
