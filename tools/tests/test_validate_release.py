# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/validate-release.py is a real release gate (tag.yml, release.yml,
tests.yml all invoke its main() for real) but CI only ever runs it against
the current, already-matching repo state — so the error-detection branches
that are the whole point of the script (version drift between meson.build
and the AppStream metainfo, missing/mismatched AppStream release entries, no
--version/--tag given) had never been exercised by unit or e2e coverage.
"""
import sys

import pytest

from loader import load_module

validate_release = load_module('tools/validate-release.py', 'validate_release')


def test_project_version_reads_meson_build():
    import re

    assert re.fullmatch(r'\d+\.\d+\.\d+', validate_release.project_version())


def test_project_version_missing_raises(tmp_path, monkeypatch):
    meson = tmp_path / 'meson.build'
    meson.write_text("project('tavern', 'c')\n")
    monkeypatch.setattr(validate_release, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='could not read project version'):
        validate_release.project_version()


def test_appstream_versions_parses_releases(tmp_path, monkeypatch):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    metainfo = data_dir / 'org.tunaos.tavern.metainfo.xml.in'
    metainfo.write_text(
        '<releases>'
        '<release version="1.2.0" date="2026-01-01"/>'
        '<release version="1.1.0" date="2025-12-01"/>'
        '</releases>'
    )
    monkeypatch.setattr(validate_release, 'ROOT', tmp_path)
    assert validate_release.appstream_versions() == ['1.2.0', '1.1.0']


def test_appstream_versions_empty_when_no_releases(tmp_path, monkeypatch):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    (data_dir / 'org.tunaos.tavern.metainfo.xml.in').write_text('<releases></releases>')
    monkeypatch.setattr(validate_release, 'ROOT', tmp_path)
    assert validate_release.appstream_versions() == []


def _run_main(monkeypatch, argv, meson_version, appstream, capsys):
    monkeypatch.setattr(validate_release, 'project_version', lambda: meson_version)
    monkeypatch.setattr(validate_release, 'appstream_versions', lambda: appstream)
    monkeypatch.setattr(sys, 'argv', ['validate-release.py'] + argv)
    code = validate_release.main()
    return code, capsys.readouterr()


def test_main_succeeds_when_versions_match(monkeypatch, capsys):
    code, out = _run_main(monkeypatch, ['--version', '1.2.0'], '1.2.0', ['1.2.0'], capsys)
    assert code == 0
    assert 'validated' in out.out


def test_main_fails_on_meson_version_mismatch(monkeypatch, capsys):
    code, out = _run_main(monkeypatch, ['--version', '1.2.0'], '1.1.0', ['1.2.0'], capsys)
    assert code == 1
    assert 'requested 1.2.0, but meson.build is 1.1.0' in out.err


def test_main_fails_when_appstream_release_missing(monkeypatch, capsys):
    code, out = _run_main(monkeypatch, ['--version', '1.2.0'], '1.2.0', [], capsys)
    assert code == 1
    assert 'latest AppStream release is missing, expected 1.2.0' in out.err


def test_main_fails_when_appstream_release_mismatched(monkeypatch, capsys):
    code, out = _run_main(monkeypatch, ['--version', '1.2.0'], '1.2.0', ['1.1.0'], capsys)
    assert code == 1
    assert 'latest AppStream release is 1.1.0, expected 1.2.0' in out.err


def test_main_reports_both_errors_together(monkeypatch, capsys):
    code, out = _run_main(monkeypatch, ['--version', '1.2.0'], '1.1.0', ['1.0.0'], capsys)
    assert code == 1
    assert 'meson.build is 1.1.0' in out.err
    assert 'AppStream release is 1.0.0' in out.err


def test_main_tag_strips_leading_v(monkeypatch, capsys):
    code, out = _run_main(monkeypatch, ['--tag', 'v1.2.0'], '1.2.0', ['1.2.0'], capsys)
    assert code == 0
    assert 'Tavern 1.2.0' in out.out


def test_main_tag_without_v_prefix_requires_explicit_version(monkeypatch, capsys):
    monkeypatch.setattr(validate_release, 'project_version', lambda: '1.2.0')
    monkeypatch.setattr(validate_release, 'appstream_versions', lambda: ['1.2.0'])
    monkeypatch.setattr(sys, 'argv', ['validate-release.py', '--tag', '1.2.0'])
    with pytest.raises(SystemExit) as exc:
        validate_release.main()
    assert exc.value.code == 2


def test_main_requires_version_or_tag(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['validate-release.py'])
    with pytest.raises(SystemExit) as exc:
        validate_release.main()
    assert exc.value.code == 2
