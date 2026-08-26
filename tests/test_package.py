# test_package.py - Unit tests for the Package model (src/package.py)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Package is the central data model shared by the backend, search, and every
# list/detail view in Tavern.  It previously had no direct tests; these cover
# the formula/cask/flatpak API parsing, the installed-set detection, analytics
# extraction (flat and nested Homebrew shapes), and the is_font helper.

import pytest

from tavern.package import Package


# ─── Formula parsing ──────────────────────────────────────────────────────────

class TestFormulaParsing:
    def test_basic_fields(self, sample_formula_data):
        pkg = Package(sample_formula_data, 'formula')
        assert pkg.name == 'ripgrep'
        assert pkg.full_name == 'ripgrep'
        assert pkg.display_name == 'ripgrep'
        assert pkg.description == 'Search tool like grep and The Silver Searcher'
        assert pkg.homepage == 'https://github.com/BurntSushi/ripgrep'
        assert pkg.version == '14.1.1'
        assert pkg.pkg_type == 'formula'
        assert pkg.license_ == 'MIT'
        assert pkg.source_url == 'https://github.com/BurntSushi/ripgrep/archive/14.1.1.tar.gz'

    def test_missing_optional_fields_default(self):
        pkg = Package({'name': 'minimal'}, 'formula')
        assert pkg.name == 'minimal'
        assert pkg.full_name == 'minimal'
        assert pkg.description == ''
        assert pkg.homepage == ''
        assert pkg.version == ''
        assert pkg.license_ == ''
        assert pkg.source_url == ''
        assert pkg.tap == ''

    def test_missing_versions_defaults_to_empty(self):
        pkg = Package({'name': 'x', 'versions': {}}, 'formula')
        assert pkg.version == ''

    def test_full_name_and_tap(self):
        data = {'name': 'hello', 'full_name': 'homebrew/core/hello', 'tap': 'homebrew/core'}
        pkg = Package(data, 'formula')
        assert pkg.full_name == 'homebrew/core/hello'
        assert pkg.tap == 'homebrew/core'

    def test_dependencies_extracted(self):
        data = {'name': 'x', 'dependencies': ['openssl', 'pkg-config', 42, None]}
        pkg = Package(data, 'formula')
        assert pkg.dependencies == ['openssl', 'pkg-config']

    def test_no_dependencies_defaults_empty(self):
        pkg = Package({'name': 'x'}, 'formula')
        assert pkg.dependencies == []

    def test_stable_url_missing_defaults_empty(self):
        pkg = Package({'name': 'x', 'urls': {}}, 'formula')
        assert pkg.source_url == ''


# ─── Cask parsing ─────────────────────────────────────────────────────────────

class TestCaskParsing:
    def test_basic_fields(self, sample_cask_data):
        pkg = Package(sample_cask_data, 'cask')
        assert pkg.name == 'firefox'
        assert pkg.full_name == 'firefox'
        assert pkg.display_name == 'Mozilla Firefox'  # first entry of name list
        assert pkg.description == 'Web browser'
        assert pkg.homepage == 'https://www.mozilla.org/firefox/'
        assert pkg.version == '130.0'
        assert pkg.pkg_type == 'cask'
        assert pkg.source_url == 'https://download.mozilla.org/?product=firefox-130.0'
        assert pkg.license_ == ''  # casks have no license field

    def test_empty_name_list_falls_back_to_token(self):
        data = {'token': 'myapp', 'full_token': 'homebrew/cask/myapp', 'name': []}
        pkg = Package(data, 'cask')
        assert pkg.display_name == 'myapp'

    def test_name_missing_falls_back_to_token(self):
        data = {'token': 'myapp', 'full_token': 'homebrew/cask/myapp'}
        pkg = Package(data, 'cask')
        assert pkg.display_name == 'myapp'

    def test_tap_extracted(self):
        data = {'token': 'x', 'tap': 'homebrew/cask'}
        pkg = Package(data, 'cask')
        assert pkg.tap == 'homebrew/cask'

    def test_supported_platforms_are_authoritative(self):
        pkg = Package({
            'token': 'linux-app',
            'supported_platforms': ['linux'],
            'depends_on': {'macos': {'>=': ['12']}},
        }, 'cask')
        assert pkg.supported_platforms == ['linux']
        assert pkg.compatibility_source == 'supported_platforms'
        assert pkg.supports_platform('linux') is True
        assert pkg.supports_platform('darwin') is False

    def test_legacy_platform_fallback(self):
        pkg = Package({'token': 'old-app', 'depends_on': {'macos': {'>=': ['12']}}}, 'cask')
        assert pkg.compatibility_source == 'legacy-depends-on'
        assert pkg.supports_platform('linux') is False
        assert pkg.supports_platform('darwin') is True


class TestSecurityMetadata:
    def test_open_advisory_with_fix(self, sample_formula_data):
        data = dict(sample_formula_data)
        data['vulnerabilities'] = {
            'open': [{'id': 'CVE-2026-0001'}],
            'patched': [],
            'fixed_count': 1,
        }
        pkg = Package(data, 'formula')
        assert pkg.has_known_vulnerability is True
        assert pkg.vulnerability_fix_available is True
        assert pkg.security_status == 'fix-available'
        assert pkg.advisory_ids == ['CVE-2026-0001']
        assert pkg.advisory_summary == '1 known advisory — fix available'

    def test_open_advisory_without_fix(self, sample_formula_data):
        data = dict(sample_formula_data)
        data['vulnerabilities'] = {'open': [{'id': 'CVE-2026-0002'}]}
        pkg = Package(data, 'formula')
        assert pkg.security_status == 'affected'

    def test_missing_advisory_data_is_normalized(self, sample_formula_data):
        pkg = Package(sample_formula_data, 'formula')
        assert pkg.vulnerabilities == {'open': [], 'patched': [], 'fixed_count': 0}
        assert pkg.security_status == 'no-known-advisories'


# ─── Flatpak parsing ──────────────────────────────────────────────────────────

class TestFlatpakParsing:
    def test_basic_fields(self):
        data = {
            'id': 'org.mozilla.firefox',
            'name': 'Firefox',
            'summary': 'Fast browser',
            'urls': {'homepage': 'https://www.mozilla.org/firefox/'},
            'releases': [{'version': '131.0'}],
            'icon': 'https://example.com/icon.png',
        }
        pkg = Package(data, 'flatpak')
        assert pkg.name == 'org.mozilla.firefox'
        assert pkg.full_name == 'org.mozilla.firefox'
        assert pkg.display_name == 'Firefox'
        assert pkg.description == 'Fast browser'
        assert pkg.homepage == 'https://www.mozilla.org/firefox/'
        assert pkg.version == '131.0'
        assert pkg.pkg_type == 'flatpak'
        assert pkg.source_url == pkg.homepage
        assert pkg.icon_url == 'https://example.com/icon.png'

    def test_missing_releases_version_empty(self):
        pkg = Package({'id': 'org.example.app', 'name': 'App'}, 'flatpak')
        assert pkg.version == ''

    def test_empty_releases_list(self):
        pkg = Package({'id': 'org.example.app', 'releases': []}, 'flatpak')
        assert pkg.version == ''

    def test_missing_urls_homepage_empty(self):
        pkg = Package({'id': 'org.example.app'}, 'flatpak')
        assert pkg.homepage == ''


# ─── Installed detection ──────────────────────────────────────────────────────

class TestInstalledDetection:
    def test_installed_by_name(self, sample_formula_data, installed_set):
        pkg = Package(sample_formula_data, 'formula', installed_set)
        assert pkg.installed is True

    def test_installed_by_full_name(self, installed_set):
        data = {'name': 'rg2', 'full_name': 'ripgrep'}
        pkg = Package(data, 'formula', installed_set)
        assert pkg.installed is True

    def test_not_installed_when_absent(self, sample_formula_data):
        pkg = Package(sample_formula_data, 'formula', {'wget'})
        assert pkg.installed is False

    def test_no_installed_set_means_not_installed(self, sample_formula_data):
        pkg = Package(sample_formula_data, 'formula')
        assert pkg.installed is False


# ─── kwargs override ──────────────────────────────────────────────────────────

class TestKwargsOverride:
    def test_kwargs_take_precedence(self, sample_formula_data):
        pkg = Package(sample_formula_data, 'formula', homepage='https://override.example')
        assert pkg.homepage == 'https://override.example'
        assert pkg.name == 'ripgrep'  # non-overridden fields keep parsed values

    def test_kwargs_add_new_attributes(self, sample_formula_data):
        pkg = Package(sample_formula_data, 'formula', custom_flag=True)
        assert pkg.custom_flag is True


# ─── is_font helper ───────────────────────────────────────────────────────────

class TestIsFont:
    def test_font_cask(self):
        pkg = Package({'token': 'font-fira-code', 'name': ['Fira Code']}, 'cask')
        assert pkg.is_font is True

    def test_regular_cask_is_not_font(self, sample_cask_data):
        pkg = Package(sample_cask_data, 'cask')
        assert pkg.is_font is False

    def test_formula_is_never_font(self, sample_formula_data):
        pkg = Package(sample_formula_data, 'formula')
        assert pkg.is_font is False


# ─── Analytics parsing ────────────────────────────────────────────────────────

class TestAnalytics:
    def test_empty_analytics_are_zero(self, sample_formula_data):
        pkg = Package(sample_formula_data, 'formula')
        assert pkg.installs_30d == 0
        assert pkg.installs_90d == 0
        assert pkg.installs_365d == 0

    def test_flat_format(self, sample_formula_data):
        data = dict(sample_formula_data)
        data['analytics'] = {'installs_30d': 100, 'installs_90d': 250, 'installs_365d': 1000}
        pkg = Package(data, 'formula')
        assert pkg.installs_30d == 100
        assert pkg.installs_90d == 250
        assert pkg.installs_365d == 1000

    def test_flat_format_missing_keys_zero(self, sample_formula_data):
        data = dict(sample_formula_data)
        data['analytics'] = {'installs_30d': 5}
        pkg = Package(data, 'formula')
        assert pkg.installs_30d == 5
        assert pkg.installs_90d == 0
        assert pkg.installs_365d == 0

    def test_nested_install_on_request(self, sample_formula_data):
        data = dict(sample_formula_data)
        data['analytics'] = {
            'install_on_request': {'30d': {'1.0': 10, '1.1': 20}, '90d': {'1.0': 30}, '365d': {'1.0': 40}},
        }
        pkg = Package(data, 'formula')
        assert pkg.installs_30d == 30
        assert pkg.installs_90d == 30
        assert pkg.installs_365d == 40

    def test_nested_install_fallback(self, sample_formula_data):
        data = dict(sample_formula_data)
        data['analytics'] = {'install': {'30d': {'1.0': 7}, '90d': {}, '365d': {'1.0': 9}}}
        pkg = Package(data, 'formula')
        assert pkg.installs_30d == 7
        assert pkg.installs_90d == 0
        assert pkg.installs_365d == 9

    def test_parsed_only_once(self, sample_formula_data):
        data = dict(sample_formula_data)
        data['analytics'] = {'installs_30d': 1, 'installs_90d': 2, 'installs_365d': 3}
        pkg = Package(data, 'formula')
        assert pkg.installs_30d == 1
        # Mutating the raw store afterwards must not change cached results
        pkg._raw_analytics['installs_30d'] = 999
        assert pkg.installs_30d == 1

    def test_cask_analytics_flat(self, sample_cask_data):
        data = dict(sample_cask_data)
        data['analytics'] = {'installs_30d': 55, 'installs_90d': 66, 'installs_365d': 77}
        pkg = Package(data, 'cask')
        assert pkg.installs_30d == 55
        assert pkg.installs_90d == 66
        assert pkg.installs_365d == 77


# ─── Raw analytics bookkeeping ────────────────────────────────────────────────

class TestRawAnalytics:
    def test_raw_analytics_stored(self, sample_formula_data):
        data = dict(sample_formula_data)
        data['analytics'] = {'installs_30d': 1}
        pkg = Package(data, 'formula')
        assert pkg._raw_analytics == {'installs_30d': 1}

    def test_raw_analytics_defaults_empty(self, sample_formula_data):
        pkg = Package(sample_formula_data, 'formula')
        assert pkg._raw_analytics == {}
