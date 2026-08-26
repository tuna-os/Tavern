# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_validator():
    path = ROOT / 'tools' / 'validate-release.py'
    spec = importlib.util.spec_from_file_location('validate_release', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_appstream_latest_release_matches_project_version():
    validator = load_validator()
    assert validator.appstream_versions()[0] == validator.project_version()


def test_search_provider_runs_as_separate_lightweight_service():
    service = (ROOT / 'data' / 'org.tunaos.tavern.SearchProvider.service.in').read_text()
    assert 'Name=@APPLICATION_ID@.SearchProvider' in service
    assert 'tavern-search-provider' in service
    application = (ROOT / 'src' / 'application.py').read_text()
    assert 'from .search_provider import' not in application
