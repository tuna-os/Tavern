"""Homebrew 7 response contracts; never contacts Homebrew or OSV."""
import json
from types import SimpleNamespace
import pytest
from loader import load_module

commands = load_module('src/brew_commands.py', 'brew_commands')
documents = load_module('src/brewfile_document.py', 'brewfile_document')


def result(data, code=0, stderr=''):
    return SimpleNamespace(stdout=json.dumps(data), stderr=stderr, returncode=code)


def test_vulnerability_findings_keep_patches_skips_and_stderr():
    data = {'findings': [{'formula': 'openssl@3', 'version': '3.4.0',
                         'vulnerabilities': [{'id': 'TEST-1', 'severity': 'HIGH',
                                              'fixed_versions': ['3.4.1']}],
                         'patched': [{'id': 'TEST-2', 'fixed_versions': []}]}],
            'skipped_formulae': ['third-party']}
    response = result(data, 1, 'Installed source unknown; current version scanned')
    assert commands.parse_vulns(response) == data
    assert response.stderr in commands.transcript(response)


@pytest.mark.parametrize('data', [[], {}, {'findings': []},
    {'findings': [{}], 'skipped_formulae': []},
    {'findings': [], 'skipped_formulae': [None]}])
def test_malformed_security_report_is_not_a_clean_scan(data):
    with pytest.raises(ValueError):
        commands.parse_vulns(result(data))


def test_security_command_failure():
    with pytest.raises(ValueError, match='failure'):
        commands.parse_vulns(result({'findings': [], 'skipped_formulae': []}, 2, 'failure'))


def test_user_service_records():
    data = [{'name': 'postgresql@17', 'status': 'started', 'user': 'test',
             'file': '/user/service.plist', 'exit_code': 0}]
    assert commands.parse_services(result(data)) == data
    assert commands.parse_services(result([])) == []


@pytest.mark.parametrize('name', ['--all', '-x', 'foo;touch /tmp/no', 'foo bar', 'foo/../bar', '', None])
def test_invalid_service_names_cannot_become_options_or_shell_code(name):
    with pytest.raises(ValueError):
        commands.parse_services(result([{'name': name, 'status': 'stopped'}]))


def test_install_argv_keeps_type_and_tap():
    package = SimpleNamespace(name='example', full_name='owner/tap/example', pkg_type='cask')
    assert commands.package_args('install', package) == ('install', '--cask', 'owner/tap/example')
    assert commands.package_args('install', package, 'other/tap/example')[-1] == 'other/tap/example'


def test_brewfile_preserves_source_and_detects_changes(tmp_path):
    path = tmp_path / 'File with spaces.Brewfile'
    source = '# Keep this\ncargo "ripgrep", args: ["--locked"]\nuv "ruff"\n' \
             'npm "typescript"\nvscode "vendor.extension"\nbrew "git", link: false\n' \
             'custom_manager "future" if OS.mac?\n'
    path.write_text(source)
    document = documents.BrewfileDocument.read(path)
    assert document.source == source
    assert document.extra_entries == (('cargo', 'ripgrep'), ('uv', 'ruff'),
                                      ('npm', 'typescript'), ('vscode', 'vendor.extension'))
    assert document.install_args == ('bundle', 'install', '--no-upgrade', '--file', str(path))
    assert document.deps_args == ('deps', '--brewfile=' + str(path))
    document.verify()
    path.write_text(source + 'brew "new-package"\n')
    with pytest.raises(ValueError, match='changed after review'):
        document.verify()


def test_version_install_is_explicit_and_cannot_accept_options():
    assert commands.version_install_args('ripgrep', '14.1.0') == ('version-install', 'ripgrep', '14.1.0')
    for name, version in [('ripgrep', '--help'), ('--help', '14'), ('openssl@3', '1.0'), ('ripgrep', '1;exit')]:
        with pytest.raises(ValueError):
            commands.version_install_args(name, version)
