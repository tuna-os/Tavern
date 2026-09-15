"""The org cask owns all structure; releases may change three values only."""
from pathlib import Path

import pytest

from loader import REPO_ROOT, load_module

updater = load_module('tools/update-homebrew-cask.py', 'update_homebrew_cask')
SOURCE = (Path(__file__).parent / 'fixtures' / 'tavern.rb').read_text()


def test_only_release_fields_change():
    updated = updater.update_cask(SOURCE, '0.2.0', 'a' * 64, 'b' * 64)
    old_hashes = updater.re.findall(r'(?m)^    sha256 "([0-9a-f]{64})"$', SOURCE)
    expected = SOURCE.replace('version "0.1.9"', 'version "0.2.0"')
    expected = expected.replace(old_hashes[0], 'a' * 64).replace(old_hashes[1], 'b' * 64)
    assert updated == expected
    assert updater.update_cask(updated, '0.2.0', 'a' * 64, 'b' * 64) == updated


@pytest.mark.parametrize('version,macos,linux', [
    ('../bad', 'a' * 64, 'b' * 64),
    ('0.1.8', 'a' * 64, 'b' * 64),
    ('0.2.0', 'bad', 'b' * 64),
    ('0.2.0', 'a' * 64, 'z' * 64),
])
def test_invalid_release_rejected(version, macos, linux):
    with pytest.raises(ValueError):
        updater.update_cask(SOURCE, version, macos, linux)


@pytest.mark.parametrize('source', [
    SOURCE.replace('on_linux do', 'on_arm do'),
    SOURCE + '\n  version "0.1.9"\n',
    SOURCE + '\n  sha256 "' + 'c' * 64 + '"\n',
])
def test_unknown_cask_shape_rejected(source):
    with pytest.raises(ValueError):
        updater.update_cask(source, '0.2.0', 'a' * 64, 'b' * 64)


def test_cli_updates_actual_file(tmp_path, monkeypatch):
    cask = tmp_path / 'tavern.rb'
    cask.write_text(SOURCE)
    artifact = tmp_path / 'artifact'
    artifact.write_bytes(b'release artifact')
    monkeypatch.setattr('sys.argv', [
        'update-homebrew-cask.py', str(cask), '--version', '0.2.0',
        '--macos', str(artifact), '--linux', str(artifact),
    ])
    updater.main()
    digest = updater.checksum(artifact)
    assert cask.read_text() == updater.update_cask(SOURCE, '0.2.0', digest, digest)


def test_documentation_publisher_and_verifier_use_org_tap():
    for path in ['README.md', '.github/workflows/update-homebrew-tap.yml',
                 '.github/workflows/verify-tap-install.yml']:
        text = (REPO_ROOT / path).read_text()
        assert 'tuna-os/homebrew-tap' in text
        assert 'hanthor/homebrew-tap' not in text
