# SPDX-License-Identifier: GPL-3.0-or-later
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loader import load_module

update_index = load_module('.github/scripts/update-index.py', 'update_index')


def write_oci_layout(oci_dir, architecture='amd64', os_='linux', labels=None):
    labels = labels if labels is not None else {
        'org.flatpak.ref': 'app/org.tunaos.tavern/amd64/stable',
        'org.flatpak.metadata': '[Application]\n',
        'org.freedesktop.appstream.id': 'org.tunaos.tavern',
    }
    blobs = oci_dir / 'blobs' / 'sha256'
    blobs.mkdir(parents=True)

    config = {'architecture': architecture, 'os': os_, 'config': {'Labels': labels}}
    config_bytes = json.dumps(config).encode()
    config_hash = 'c' * 64
    (blobs / config_hash).write_bytes(config_bytes)

    manifest = {'config': {'digest': f'sha256:{config_hash}'}}
    manifest_bytes = json.dumps(manifest).encode()
    manifest_hash = 'm' * 64
    (blobs / manifest_hash).write_bytes(manifest_bytes)

    index = {'manifests': [{'digest': f'sha256:{manifest_hash}'}]}
    (oci_dir / 'index.json').write_text(json.dumps(index))


def run_main(monkeypatch, argv):
    monkeypatch.setattr(sys, 'argv', ['update-index.py'] + argv)
    update_index.main()


def test_raises_when_oci_layout_missing_index(tmp_path, monkeypatch):
    oci_dir = tmp_path / 'oci'
    oci_dir.mkdir()
    index_file = tmp_path / 'index' / 'static'
    with pytest.raises(FileNotFoundError):
        run_main(monkeypatch, [
            '--oci-dir', str(oci_dir), '--index-file', str(index_file),
            '--repo-name', 'tuna-os/tavern',
        ])


def test_raises_when_no_manifests_listed(tmp_path, monkeypatch):
    oci_dir = tmp_path / 'oci'
    oci_dir.mkdir()
    (oci_dir / 'index.json').write_text(json.dumps({'manifests': []}))
    index_file = tmp_path / 'index' / 'static'
    with pytest.raises(ValueError, match='No manifests'):
        run_main(monkeypatch, [
            '--oci-dir', str(oci_dir), '--index-file', str(index_file),
            '--repo-name', 'tuna-os/tavern',
        ])


def test_raises_when_required_flatpak_label_missing(tmp_path, monkeypatch):
    oci_dir = tmp_path / 'oci'
    write_oci_layout(oci_dir, labels={'org.flatpak.ref': 'app/org.tunaos.tavern/amd64/stable'})
    index_file = tmp_path / 'index' / 'static'
    with pytest.raises(ValueError, match='org.flatpak.metadata'):
        run_main(monkeypatch, [
            '--oci-dir', str(oci_dir), '--index-file', str(index_file),
            '--repo-name', 'tuna-os/tavern',
        ])


def test_creates_new_index_with_entry(tmp_path, monkeypatch):
    oci_dir = tmp_path / 'oci'
    write_oci_layout(oci_dir)
    index_file = tmp_path / 'index' / 'static'
    run_main(monkeypatch, [
        '--oci-dir', str(oci_dir), '--index-file', str(index_file),
        '--repo-name', 'tuna-os/tavern', '--registry', 'ghcr.io', '--tags', 'v1.0',
    ])
    data = json.loads(index_file.read_text())
    assert data['Registry'] == 'https://ghcr.io'
    result = data['Results'][0]
    assert result['Name'] == 'tuna-os/tavern'
    image = result['Images'][0]
    assert image['Architecture'] == 'amd64'
    assert image['Tags'] == ['v1.0']
    assert image['Labels'] == {
        'org.flatpak.ref': 'app/org.tunaos.tavern/amd64/stable',
        'org.flatpak.metadata': '[Application]\n',
        'org.freedesktop.appstream.id': 'org.tunaos.tavern',
    }


def test_replaces_existing_architecture_entry(tmp_path, monkeypatch):
    index_file = tmp_path / 'index' / 'static'
    index_file.parent.mkdir(parents=True)
    index_file.write_text(json.dumps({
        'Registry': 'https://ghcr.io',
        'Results': [{
            'Name': 'tuna-os/tavern',
            'Images': [{
                'Digest': 'sha256:old', 'MediaType': 'application/vnd.oci.image.manifest.v1+json',
                'OS': 'linux', 'Architecture': 'amd64', 'Tags': ['latest'], 'Labels': {},
            }],
        }],
    }))
    oci_dir = tmp_path / 'oci'
    write_oci_layout(oci_dir, architecture='amd64')
    run_main(monkeypatch, [
        '--oci-dir', str(oci_dir), '--index-file', str(index_file),
        '--repo-name', 'tuna-os/tavern',
    ])
    data = json.loads(index_file.read_text())
    images = data['Results'][0]['Images']
    assert len(images) == 1
    assert images[0]['Digest'] == f'sha256:{"m" * 64}'


def test_appends_new_architecture_for_existing_repo(tmp_path, monkeypatch):
    index_file = tmp_path / 'index' / 'static'
    index_file.parent.mkdir(parents=True)
    index_file.write_text(json.dumps({
        'Registry': 'https://ghcr.io',
        'Results': [{
            'Name': 'tuna-os/tavern',
            'Images': [{
                'Digest': 'sha256:old', 'MediaType': 'application/vnd.oci.image.manifest.v1+json',
                'OS': 'linux', 'Architecture': 'arm64', 'Tags': ['latest'], 'Labels': {},
            }],
        }],
    }))
    oci_dir = tmp_path / 'oci'
    write_oci_layout(oci_dir, architecture='amd64')
    run_main(monkeypatch, [
        '--oci-dir', str(oci_dir), '--index-file', str(index_file),
        '--repo-name', 'tuna-os/tavern',
    ])
    data = json.loads(index_file.read_text())
    images = data['Results'][0]['Images']
    assert {img['Architecture'] for img in images} == {'arm64', 'amd64'}


def test_default_tags_and_registry(tmp_path, monkeypatch):
    oci_dir = tmp_path / 'oci'
    write_oci_layout(oci_dir)
    index_file = tmp_path / 'index' / 'static'
    run_main(monkeypatch, [
        '--oci-dir', str(oci_dir), '--index-file', str(index_file),
        '--repo-name', 'tuna-os/tavern',
    ])
    data = json.loads(index_file.read_text())
    assert data['Registry'] == 'https://ghcr.io'
    assert data['Results'][0]['Images'][0]['Tags'] == ['latest']
