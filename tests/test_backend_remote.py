"""Remote catalog and analytics contracts without network access."""

from types import SimpleNamespace

from tavern.backend_remote import RemoteMixin


_VALID_CURATION = {
    'schema_version': 1,
    'sections': [{
        'id': 'featured',
        'title': 'Featured',
        'package_type': 'formula',
        'packages': ['ripgrep', 'fd'],
    }],
}
_NORMALIZED_CURATION = {
    'schema_version': 1,
    'sections': [{
        'id': 'featured',
        'title': 'Featured',
        'package_type': 'formula',
        'packages': ['ripgrep', 'fd'],
        'summary': '',
        'link': '',
        'platforms': [],
        'starts_at': '',
        'ends_at': '',
    }],
}


class RemoteHarness(RemoteMixin):
    def __init__(self, cached=None, stale=True):
        self.cached = cached
        self.stale = stale
        self.saved = []
        self.fetches = []

    def _load_cached(self, name, max_age):
        assert name == 'curation'
        assert max_age == 21600
        return self.cached, self.stale

    def _save_cache(self, name, data):
        self.saved.append((name, data))

    def _fetch_json(self, url, max_bytes=None):
        self.fetches.append((url, max_bytes))
        return self.remote


def test_get_curation_uses_fresh_valid_cache_without_fetching():
    harness = RemoteHarness(cached=_VALID_CURATION, stale=False)
    harness.remote = {'schema_version': 1, 'sections': []}

    result = harness.get_curation()

    assert result == _NORMALIZED_CURATION
    assert harness.fetches == []
    assert harness.saved == [('curation', _NORMALIZED_CURATION)]


def test_get_curation_rejects_invalid_remote_and_uses_cached_fallback():
    harness = RemoteHarness(cached=_VALID_CURATION, stale=True)
    harness.remote = {'schema_version': 99, 'sections': []}

    result = harness.get_curation()

    assert result == _NORMALIZED_CURATION
    assert len(harness.fetches) == 1
    assert harness.saved == [('curation', _NORMALIZED_CURATION)]


def test_get_curation_normalizes_and_caches_valid_remote_data():
    remote = {
        'schema_version': 1,
        'sections': [{
            'id': ' featured ',
            'title': ' Featured packages ',
            'package_type': 'formula',
            'packages': ['ripgrep', 'ripgrep', 'fd'],
        }],
    }
    harness = RemoteHarness(cached=None, stale=True)
    harness.remote = remote

    result = harness.get_curation()

    assert result['sections'][0]['id'] == 'featured'
    assert result['sections'][0]['title'] == 'Featured packages'
    assert result['sections'][0]['packages'] == ['ripgrep', 'fd']
    assert harness.saved == [('curation', result)]


def test_fetch_analytics_data_merges_periods_and_normalizes_counts():
    responses = {
        '30d': {'items': [
            {'formula': 'ripgrep', 'count': '1,234'},
            {'formula': 'fd', 'count': 'not-a-number'},
            {'formula': '', 'count': '99'},
        ]},
        '90d': {'items': [{'formula': 'ripgrep', 'count': '567'}]},
        '365d': {'items': [{'formula': 'fd', 'count': '8'}]},
    }
    harness = SimpleNamespace(saved=[], calls=[])

    def load_cached(name, max_age):
        assert (name, max_age) == ('analytics', 86400)
        return None, True

    def fetch_json(url):
        period = url.rsplit('/', 1)[-1].removesuffix('.json')
        harness.calls.append(period)
        return responses[period]

    def save_cache(name, data):
        harness.saved.append((name, data))

    harness._load_cached = load_cached
    harness._fetch_json = fetch_json
    harness._save_cache = save_cache

    result = RemoteMixin._fetch_analytics_data(harness)

    assert harness.calls == ['30d', '90d', '365d']
    assert result == {
        'ripgrep': {'installs_30d': 1234, 'installs_90d': 567},
        'fd': {'installs_30d': 0, 'installs_365d': 8},
    }
    assert harness.saved == [('analytics', result)]


def test_fetch_analytics_data_returns_fresh_cache_without_network():
    cached = {'ripgrep': {'installs_30d': 42}}
    harness = SimpleNamespace(
        _load_cached=lambda name, max_age: (cached, False),
        _fetch_json=lambda url: (_ for _ in ()).throw(AssertionError('network used')),
    )

    assert RemoteMixin._fetch_analytics_data(harness) is cached
