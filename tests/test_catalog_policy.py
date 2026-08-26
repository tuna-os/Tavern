# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from tavern.catalog_policy import (
    CatalogFilters, curation_section, curated_packages, filter_packages, search_rank,
    sort_packages, validate_curation,
)
from tavern.package import Package


def package(name, pkg_type='formula', **kwargs):
    return Package(name=name, full_name=name, display_name=name, pkg_type=pkg_type, **kwargs)


def test_filters_compose_query_type_installed_and_security():
    affected = package('secure-tool', installed=True)
    affected.vulnerabilities = {'open': ['CVE-2026-1'], 'patched': [], 'fixed_count': 0}
    other = package('secure-app', pkg_type='cask', installed=True)
    filters = CatalogFilters(
        query='secure', package_types=frozenset({'formula'}),
        installed_only=True, vulnerable_only=True,
    )
    assert filter_packages([other, affected], filters) == [affected]


def test_sort_updates_first_is_stable():
    packages = [package('zebra'), package('alpha'), package('middle')]
    result = sort_packages(packages, 'updates', outdated={'middle'})
    assert [item.name for item in result] == ['middle', 'alpha', 'zebra']


def test_search_rank_prefers_exact_then_prefix_then_description():
    exact = package('git')
    prefix = package('git-lfs')
    description = package('tool', description='A git helper')
    assert sorted([description, prefix, exact], key=lambda p: search_rank(p, 'git')) == [
        exact, prefix, description,
    ]


def test_validate_and_resolve_curation():
    data = validate_curation({
        'schema_version': 1,
        'sections': [{
            'id': 'essentials', 'title': 'Essentials',
            'package_type': 'formula', 'packages': ['git', 'missing'],
        }],
    })
    assert curation_section(data, 'essentials')['title'] == 'Essentials'
    assert curated_packages([package('git')], data['sections'][0]['packages'])[0].name == 'git'


def test_curation_constraints_and_safe_editorial_metadata():
    data = validate_curation({
        'schema_version': 1,
        'sections': [{
            'id': 'seasonal', 'title': 'Seasonal', 'package_type': 'cask',
            'packages': ['firefox', 'firefox'], 'summary': 'A timely pick.',
            'link': 'https://example.com/picks', 'platforms': ['linux'],
            'starts_at': '2026-08-01', 'ends_at': '2026-08-31',
        }],
    })
    section = curation_section(
        data, 'seasonal', platform='linux', today='2026-08-15')
    assert section['packages'] == ['firefox']
    assert curation_section(
        data, 'seasonal', platform='darwin', today='2026-08-15') is None
    assert curation_section(
        data, 'seasonal', platform='linux', today='2026-09-01') is None


@pytest.mark.parametrize('field,value', [
    ('link', 'javascript:alert(1)'),
    ('platforms', ['windows']),
    ('starts_at', 'tomorrow'),
])
def test_unsafe_curation_metadata_is_rejected(field, value):
    section = {
        'id': 'bad', 'title': 'Bad', 'package_type': 'formula',
        'packages': ['git'], field: value,
    }
    with pytest.raises(ValueError):
        validate_curation({'schema_version': 1, 'sections': [section]})


@pytest.mark.parametrize('data', [{}, {'schema_version': 2, 'sections': []}, {'schema_version': 1}])
def test_invalid_curation_is_rejected(data):
    with pytest.raises(ValueError):
        validate_curation(data)
