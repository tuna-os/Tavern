# SPDX-License-Identifier: GPL-3.0-or-later
"""Oracle tests for tools/visual_evidence.py: one positive control per lane
and a negative fixture for each rejection the acceptance contract names."""
import copy
import json

import pytest

from loader import load_module

ve = load_module('tools/visual_evidence.py', 'visual_evidence')

APP = 'org.tunaos.tavern'
SHA = 'a' * 40
BUNDLE = 'b' * 64


def make(tmp_path, lane, scenario='no-homebrew', **over):
    png = tmp_path / 'main-window.png'
    png.write_bytes(ve.PNG_MAGIC + b'frame-bytes')
    candidate = lane == 'candidate-build'
    state = {
        'readback': True, 'window_owner': APP, 'screen': 'main',
        **ve.SCENARIOS[scenario],
    }
    if scenario == 'no-homebrew':
        state['no_homebrew_message'] = True
    receipt = ve.build_receipt(
        lane=lane, scenario=scenario,
        run={'id': '7', 'attempt': '1'},
        artifact={
            'app_id': APP, 'app_commit': 'c0ffee',
            'runtime': 'org.gnome.Platform//50',
            **({'source': 'bundle', 'bundle_sha256': BUNDLE} if candidate
               else {'source': 'remote', 'remote': 'tuna-os'}),
        },
        source=({'binding': 'bundle-built-from-commit', 'commit': SHA}
                if candidate else {'binding': 'unknown'}),
        environment={'capture_action': '4ad379e'},
        state=state, out_dir=tmp_path, cleanup={'completed': True},
    )
    receipt.update(over)
    expect = {
        'lane': lane, 'scenario': scenario, 'run_id': '7',
        'run_attempt': '1', 'app_id': APP,
        'runtime': 'org.gnome.Platform//50',
        'source_sha': SHA, 'bundle_sha256': BUNDLE,
    }
    return receipt, expect


@pytest.mark.parametrize('lane', ve.LANES)
@pytest.mark.parametrize('scenario', sorted(ve.SCENARIOS))
def test_positive_control(tmp_path, lane, scenario):
    receipt, expect = make(tmp_path, lane, scenario)
    assert ve.verify(receipt, tmp_path, expect=expect) == []


def reject(tmp_path, lane, mutate, needle, scenario='no-homebrew'):
    receipt, expect = make(tmp_path, lane, scenario)
    receipt = copy.deepcopy(receipt)
    mutate(receipt, expect)
    failures = ve.verify(receipt, tmp_path, expect=expect)
    assert any(needle in f for f in failures), failures


def test_published_substituted_for_candidate(tmp_path):
    def m(r, e):
        r['artifact']['source'] = 'remote'
    reject(tmp_path, 'candidate-build', m, 'published package substituted')


def test_published_lane_cannot_claim_source(tmp_path):
    def m(r, e):
        r['source'] = {'binding': 'bundle-built-from-commit', 'commit': SHA}
    reject(tmp_path, 'published-artifact', m, 'unknown')


def test_wrong_app(tmp_path):
    reject(tmp_path, 'candidate-build',
           lambda r, e: r['artifact'].update(app_id='org.other.App'),
           'wrong app id')


def test_wrong_runtime(tmp_path):
    reject(tmp_path, 'candidate-build',
           lambda r, e: r['artifact'].update(runtime='org.gnome.Platform//49'),
           'wrong runtime')


def test_wrong_source_digest(tmp_path):
    reject(tmp_path, 'candidate-build',
           lambda r, e: r['source'].update(commit='d' * 40),
           'source digest')


def test_wrong_bundle_digest(tmp_path):
    reject(tmp_path, 'candidate-build',
           lambda r, e: r['artifact'].update(bundle_sha256='e' * 64),
           'bundle digest')


def test_stale_png_modified(tmp_path):
    def m(r, e):
        (tmp_path / 'main-window.png').write_bytes(ve.PNG_MAGIC + b'older')
    reject(tmp_path, 'candidate-build', m, 'stale PNG')


def test_stale_committed_png_present(tmp_path):
    def m(r, e):
        (tmp_path / 'committed-baseline.png').write_bytes(ve.PNG_MAGIC)
    reject(tmp_path, 'candidate-build', m, 'stale or foreign')


def test_receipt_from_another_run(tmp_path):
    reject(tmp_path, 'candidate-build',
           lambda r, e: r['run'].update(id='6'), 'another workflow run')


def test_unrelated_window(tmp_path):
    reject(tmp_path, 'candidate-build',
           lambda r, e: r['state'].update(window_owner='org.gnome.Nautilus'),
           'unrelated window')


@pytest.mark.parametrize('screen', ['loading', 'error'])
def test_frozen_screen(tmp_path, screen):
    reject(tmp_path, 'candidate-build',
           lambda r, e: r['state'].update(screen=screen), 'frozen')


def test_missing_no_homebrew_message(tmp_path):
    reject(tmp_path, 'candidate-build',
           lambda r, e: r['state'].update(no_homebrew_message=False),
           'no-Homebrew message')


def test_visibility_only_without_readback(tmp_path):
    reject(tmp_path, 'candidate-build',
           lambda r, e: r['state'].update(readback=False), 'readback')


def test_missing_capture(tmp_path):
    def m(r, e):
        (tmp_path / 'main-window.png').unlink()
        r['frames'] = {}
    reject(tmp_path, 'candidate-build', m, 'no frames')


def test_non_png_frame(tmp_path):
    def m(r, e):
        p = tmp_path / 'main-window.png'
        p.write_bytes(b'not a png')
        r['frames']['main-window.png'] = ve.sha256_file(p)
    reject(tmp_path, 'candidate-build', m, 'not a PNG')


def test_recorded_failure_and_cleanup(tmp_path):
    reject(tmp_path, 'candidate-build',
           lambda r, e: r.update(failures=['retry 1: timeout']),
           'recorded failures')
    reject(tmp_path, 'candidate-build',
           lambda r, e: r.update(cleanup={}), 'cleanup')


def test_non_allowlisted_key(tmp_path):
    reject(tmp_path, 'candidate-build',
           lambda r, e: r.update(env={'TOKEN': 'x'}), 'non-allowlisted')


def test_cli_roundtrip(tmp_path, capsys):
    receipt, expect = make(tmp_path, 'candidate-build')
    path = tmp_path / 'receipt.json'
    path.write_text(json.dumps(receipt))
    args = ['verify', '--receipt', str(path), '--out-dir', str(tmp_path),
            '--lane', 'candidate-build', '--scenario', 'no-homebrew',
            '--run-id', '7', '--run-attempt', '1', '--runtime',
            'org.gnome.Platform//50', '--source-sha', SHA,
            '--bundle-sha256', BUNDLE]
    assert ve.main(args) == 0
    assert ve.main(args[:-1] + ['f' * 64]) == 1
