# SPDX-License-Identifier: GPL-3.0-or-later
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loader import load_module

check_supply_chain = load_module('tools/check-supply-chain.py', 'check_supply_chain')


def setup(tmp_path, monkeypatch, release_text='', manifest_text='{}'):
    release = tmp_path / 'release.yml'
    manifest = tmp_path / 'org.tunaos.tavern.json'
    release.write_text(release_text)
    manifest.write_text(manifest_text)
    monkeypatch.setattr(check_supply_chain, 'ROOT', tmp_path)
    monkeypatch.setattr(check_supply_chain, 'TARGETS', [release, manifest])
    return release, manifest


def test_passes_on_clean_inputs(tmp_path, monkeypatch, capsys):
    setup(tmp_path, monkeypatch, 'steps: []', '{}')
    assert check_supply_chain.main() == 0
    assert 'passed' in capsys.readouterr().out


def test_flags_continuous_release_download(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, 'curl https://example.com/continuous/app.flatpak')
    assert check_supply_chain.main() == 1


def test_flags_mutable_raw_branch_download(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, 'curl https://raw.githubusercontent.com/org/repo/main/install.sh')
    assert check_supply_chain.main() == 1


def test_allows_pinned_raw_branch_download(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, 'curl https://raw.githubusercontent.com/org/repo/abc123/install.sh')
    assert check_supply_chain.main() == 0


def test_flags_unversioned_pip_install(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, 'run: pip install requests')
    assert check_supply_chain.main() == 1


def test_allows_pinned_pip_install(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, 'run: pip install requests==2.31.0')
    assert check_supply_chain.main() == 0


def test_allows_no_index_pip_install(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, 'run: pip install --no-index ./vendor/pkg.whl')
    assert check_supply_chain.main() == 0


def test_flags_tagged_source_without_commit(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, '', '{"tag": "v0.22.2"}')
    assert check_supply_chain.main() == 1


def test_allows_tagged_source_with_commit(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, '', '{"tag": "v0.22.2", "commit": "abc123"}')
    assert check_supply_chain.main() == 0


def test_allows_untagged_source(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, '', '{"branch": "main"}')
    assert check_supply_chain.main() == 0
