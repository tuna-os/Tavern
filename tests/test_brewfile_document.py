# test_brewfile_document.py
# SPDX-License-Identifier: GPL-3.0-or-later

import hashlib

import pytest

from tavern.brewfile_document import BrewfileDocument


def _write(tmp_path, text='brew "git"\n', name='Brewfile'):
    path = tmp_path / name
    path.write_bytes(text.encode('utf-8'))
    return path


def test_read_records_absolute_path_source_and_digest(tmp_path):
    path = _write(tmp_path, 'brew "git"\n')
    doc = BrewfileDocument.read(path)
    assert doc.path == str(path.absolute())
    assert doc.source == 'brew "git"\n'
    assert doc.digest == hashlib.sha256(b'brew "git"\n').hexdigest()


def test_read_makes_relative_path_absolute(tmp_path, monkeypatch):
    _write(tmp_path)
    monkeypatch.chdir(tmp_path)
    doc = BrewfileDocument.read('Brewfile')
    assert doc.path == str(tmp_path / 'Brewfile')


def test_read_rejects_non_utf8(tmp_path):
    path = tmp_path / 'Brewfile'
    path.write_bytes(b'brew "\xff\xfe"\n')
    with pytest.raises(UnicodeDecodeError):
        BrewfileDocument.read(path)


def test_read_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        BrewfileDocument.read(tmp_path / 'absent')


def test_verify_passes_when_file_unchanged(tmp_path):
    doc = BrewfileDocument.read(_write(tmp_path))
    doc.verify()


def test_verify_rejects_file_changed_after_review(tmp_path):
    path = _write(tmp_path, 'brew "git"\n')
    doc = BrewfileDocument.read(path)
    path.write_text('brew "git"\nbrew "evil"\n')
    with pytest.raises(ValueError, match='changed after review'):
        doc.verify()


def test_verify_rejects_deleted_file(tmp_path):
    path = _write(tmp_path)
    doc = BrewfileDocument.read(path)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        doc.verify()


def test_extra_entries_lists_supported_kinds_in_order(tmp_path):
    source = (
        'brew "git"\n'
        'cargo "ripgrep"\n'
        "  uv 'ruff'\n"
        'npm "typescript"\n'
        'vscode "ms-python.python"\n'
        'vscode_insiders "foo.bar"\n'
        'go "golang.org/x/tools"\n'
        'mas "Xcode", id: 497799835\n'
        'krew "ctx"\n'
        'winget "Git.Git"\n'
    )
    doc = BrewfileDocument.read(_write(tmp_path, source))
    assert doc.extra_entries == (
        ('cargo', 'ripgrep'),
        ('uv', 'ruff'),
        ('npm', 'typescript'),
        ('vscode', 'ms-python.python'),
        ('vscode_insiders', 'foo.bar'),
        ('go', 'golang.org/x/tools'),
        ('mas', 'Xcode'),
        ('krew', 'ctx'),
        ('winget', 'Git.Git'),
    )


def test_extra_entries_ignores_core_comments_and_unquoted(tmp_path):
    source = (
        'brew "git"\n'
        'cask "firefox"\n'
        'tap "homebrew/core"\n'
        '# cargo "commented"\n'
        'cargo ripgrep\n'
        'cargoextra "x"\n'
    )
    doc = BrewfileDocument.read(_write(tmp_path, source))
    assert doc.extra_entries == ()


def test_extra_entries_does_not_evaluate_ruby(tmp_path):
    source = 'cargo "#{name}" if OS.mac?\n'
    doc = BrewfileDocument.read(_write(tmp_path, source))
    assert doc.extra_entries == (('cargo', '#{name}'),)


def test_install_and_deps_args_keep_original_path(tmp_path):
    path = _write(tmp_path)
    doc = BrewfileDocument.read(path)
    assert doc.install_args == (
        'bundle', 'install', '--no-upgrade', '--file', str(path.absolute()))
    assert doc.deps_args == ('deps', '--brewfile=' + str(path.absolute()))


def test_document_is_immutable(tmp_path):
    doc = BrewfileDocument.read(_write(tmp_path))
    with pytest.raises(AttributeError):
        doc.source = 'changed'
