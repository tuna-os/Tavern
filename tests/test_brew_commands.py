# test_brew_commands.py - Tests for the Homebrew command boundary (src/brew_commands.py)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# brew_commands validates every package name and version before it reaches a
# brew argv, and checks the shape of the JSON reports the maintenance page
# renders. Until now only run_read had a direct test; the validators and the
# report parsers were reached only through UI tests that never feed them a
# malformed value. These tests need no Homebrew install and no display.

from types import SimpleNamespace

import pytest

from tavern import brew_commands as bc


def _result(stdout='', stderr='', returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def _package(name='ripgrep', full_name='', pkg_type='formula'):
    return SimpleNamespace(name=name, full_name=full_name, pkg_type=pkg_type)


class TestValidateName:
    @pytest.mark.parametrize('name', [
        'ripgrep', 'python@3.12', 'g++', 'node_exec', 'a.b-c',
        'homebrew/core/ripgrep', 'tuna-os/tap/tavern',
    ])
    def test_accepts_homebrew_names(self, name):
        assert bc.validate_name(name) == name

    @pytest.mark.parametrize('name', [
        '', '-rf', '--cask', '.hidden', '/abs', 'trailing/', 'a//b',
        'a b', 'a;b', 'a$(x)', 'a\nb', 'a|b', '../etc', None, 42, ['a'],
    ])
    def test_rejects_option_like_and_shell_shaped_names(self, name):
        with pytest.raises(ValueError, match='Invalid Homebrew package name'):
            bc.validate_name(name)


class TestPackageArgs:
    def test_formula_uses_full_name(self):
        pkg = _package(name='ripgrep', full_name='homebrew/core/ripgrep')
        assert bc.package_args('install', pkg) == (
            'install', '--formula', 'homebrew/core/ripgrep')

    def test_falls_back_to_short_name(self):
        assert bc.package_args('upgrade', _package(name='ripgrep')) == (
            'upgrade', '--formula', 'ripgrep')

    def test_cask_flag(self):
        pkg = _package(name='firefox', pkg_type='cask')
        assert bc.package_args('install', pkg) == ('install', '--cask', 'firefox')

    def test_qualified_name_wins_over_package_names(self):
        pkg = _package(name='ripgrep', full_name='homebrew/core/ripgrep')
        assert bc.package_args('install', pkg, qualified='tuna-os/tap/rg') == (
            'install', '--formula', 'tuna-os/tap/rg')

    def test_invalid_name_never_reaches_argv(self):
        with pytest.raises(ValueError):
            bc.package_args('install', _package(name='--force'))
        with pytest.raises(ValueError):
            bc.package_args('install', _package(name='ok'), qualified='a b')


class TestVersionInstallArgs:
    def test_plain_formula(self):
        assert bc.version_install_args('ripgrep', '14.1.0') == (
            'version-install', 'ripgrep', '14.1.0')

    def test_versioned_formula_suffix_must_match(self):
        assert bc.version_install_args('python@3.12', '3.12') == (
            'version-install', 'python@3.12', '3.12')
        with pytest.raises(ValueError, match='must match'):
            bc.version_install_args('python@3.12', '3.13')

    @pytest.mark.parametrize('version', ['', 'v1.0', '-1', '1 0', '1;rm', '1\n2', 'latest'])
    def test_rejects_versions_not_starting_with_a_digit(self, version):
        with pytest.raises(ValueError, match='starts with a number'):
            bc.version_install_args('ripgrep', version)

    def test_rejects_invalid_formula(self):
        with pytest.raises(ValueError, match='Invalid Homebrew package name'):
            bc.version_install_args('--cask', '1.0')


class TestTranscript:
    def test_joins_stripped_streams(self):
        assert bc.transcript(_result(' out \n', '\nerr ')) == 'out\nerr'

    def test_skips_empty_streams(self):
        assert bc.transcript(_result('out', '')) == 'out'
        assert bc.transcript(_result('', 'err')) == 'err'
        assert bc.transcript(_result()) == ''

    def test_none_streams_are_ignored(self):
        assert bc.transcript(_result(None, 'err')) == 'err'


class TestParseServices:
    def test_valid_list_is_returned(self):
        out = '[{"name": "postgresql@16", "status": "started"}]'
        assert bc.parse_services(_result(out)) == [
            {'name': 'postgresql@16', 'status': 'started'}]

    def test_empty_list_is_valid(self):
        assert bc.parse_services(_result('[]')) == []

    def test_nonzero_exit_reports_transcript(self):
        with pytest.raises(ValueError, match='boom'):
            bc.parse_services(_result('', 'boom', 1))

    def test_nonzero_exit_without_output_has_default_message(self):
        with pytest.raises(ValueError, match='Could not list user services'):
            bc.parse_services(_result('', '', 1))

    def test_non_json_includes_transcript(self):
        with pytest.raises(ValueError, match='did not return a JSON report') as info:
            bc.parse_services(_result('Warning: not json'))
        assert 'Warning: not json' in str(info.value)

    def test_none_stdout_is_not_json(self):
        with pytest.raises(ValueError, match='did not return a JSON report'):
            bc.parse_services(_result(None))

    @pytest.mark.parametrize('out', ['{}', '"x"', 'null'])
    def test_non_list_rejected(self, out):
        with pytest.raises(ValueError, match='Unexpected Homebrew services'):
            bc.parse_services(_result(out))

    @pytest.mark.parametrize('out', [
        '["x"]', '[{"name": "a"}]', '[{"name": "a", "status": 1}]',
    ])
    def test_bad_record_rejected(self, out):
        with pytest.raises(ValueError, match='Invalid Homebrew service record'):
            bc.parse_services(_result(out))

    @pytest.mark.parametrize('name', ['--all', 'a b', '', None])
    def test_bad_service_name_rejected(self, name):
        import json
        out = json.dumps([{'name': name, 'status': 'started'}])
        with pytest.raises(ValueError, match='Invalid Homebrew package name'):
            bc.parse_services(_result(out))


def _report(**overrides):
    report = {
        'findings': [{
            'formula': 'openssl@3', 'version': '3.0.1',
            'vulnerabilities': [{'id': 'CVE-1', 'fixed_versions': ['3.0.2']}],
            'patched': [],
        }],
        'skipped_formulae': [],
    }
    report.update(overrides)
    import json
    return json.dumps(report)


class TestParseVulns:
    @pytest.mark.parametrize('code', [0, 1])
    def test_exit_0_and_1_are_valid_reports(self, code):
        data = bc.parse_vulns(_result(_report(), returncode=code))
        assert data['findings'][0]['formula'] == 'openssl@3'

    def test_exit_1_is_incomplete_coverage_not_a_crash(self):
        data = bc.parse_vulns(_result(_report(findings=[], skipped_formulae=['x']),
                                      'Untrusted keg', 1))
        assert data['skipped_formulae'] == ['x']

    def test_exit_2_is_a_failure_with_transcript(self):
        with pytest.raises(ValueError, match='scanner crashed'):
            bc.parse_vulns(_result('', 'scanner crashed', 2))

    def test_exit_2_without_output_has_default_message(self):
        with pytest.raises(ValueError, match='Security scan failed'):
            bc.parse_vulns(_result('', '', 2))

    def test_non_json_rejected(self):
        with pytest.raises(ValueError, match='did not return a JSON report'):
            bc.parse_vulns(_result('nope'))

    @pytest.mark.parametrize('out', ['[]', '{}', '{"findings": {}}'])
    def test_missing_or_wrong_findings_rejected(self, out):
        with pytest.raises(ValueError, match='Unexpected Homebrew vulnerability'):
            bc.parse_vulns(_result(out))

    @pytest.mark.parametrize('skipped', [None, 'x', [1], ['a', None]])
    def test_bad_skipped_list_rejected(self, skipped):
        with pytest.raises(ValueError, match='Invalid skipped-package list'):
            bc.parse_vulns(_result(_report(skipped_formulae=skipped)))

    def test_missing_skipped_list_rejected(self):
        with pytest.raises(ValueError, match='Invalid skipped-package list'):
            bc.parse_vulns(_result('{"findings": []}'))

    def test_non_dict_finding_rejected(self):
        with pytest.raises(ValueError, match='Invalid vulnerability finding'):
            bc.parse_vulns(_result(_report(findings=['x'])))

    @pytest.mark.parametrize('key', ['formula', 'version'])
    def test_finding_identity_must_be_strings(self, key):
        finding = {'formula': 'a', 'version': '1', 'vulnerabilities': [], 'patched': []}
        finding[key] = 3
        with pytest.raises(ValueError, match='Invalid vulnerability package identity'):
            bc.parse_vulns(_result(_report(findings=[finding])))

    @pytest.mark.parametrize('key', ['vulnerabilities', 'patched'])
    def test_vulnerability_lists_must_be_lists(self, key):
        finding = {'formula': 'a', 'version': '1', 'vulnerabilities': [], 'patched': []}
        finding[key] = 'CVE-1'
        with pytest.raises(ValueError, match='Invalid vulnerability list'):
            bc.parse_vulns(_result(_report(findings=[finding])))

    @pytest.mark.parametrize('key', ['vulnerabilities', 'patched'])
    @pytest.mark.parametrize('vuln', ['CVE-1', {'id': 7}, {}])
    def test_vulnerability_record_needs_string_id(self, key, vuln):
        finding = {'formula': 'a', 'version': '1', 'vulnerabilities': [], 'patched': []}
        finding[key] = [vuln]
        with pytest.raises(ValueError, match='Invalid vulnerability record'):
            bc.parse_vulns(_result(_report(findings=[finding])))

    @pytest.mark.parametrize('fixed', [None, '3.0.2', [3], ['3.0.2', None]])
    def test_fixed_versions_must_be_string_list(self, fixed):
        finding = {'formula': 'a', 'version': '1', 'patched': [],
                   'vulnerabilities': [{'id': 'CVE-1', 'fixed_versions': fixed}]}
        with pytest.raises(ValueError, match='Invalid fixed-version list'):
            bc.parse_vulns(_result(_report(findings=[finding])))

    def test_missing_fixed_versions_rejected(self):
        finding = {'formula': 'a', 'version': '1', 'patched': [],
                   'vulnerabilities': [{'id': 'CVE-1'}]}
        with pytest.raises(ValueError, match='Invalid fixed-version list'):
            bc.parse_vulns(_result(_report(findings=[finding])))
