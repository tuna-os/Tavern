#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build and verify artifact-bound visual evidence receipts (#315).

Two lanes produce screenshots and they must never be confused:

``published-artifact``
    Today's published ``org.tunaos.tavern`` Flatpak. Its source binding is
    always ``unknown``: the checked-out PR is not what was installed.
``candidate-build``
    A bundle built from the checked-out source. Its bundle digest is bound
    to the source commit and the workflow run.

A receipt is allowlisted JSON (no environment dump, no paths outside the
output directory). ``verify`` is the acceptance oracle: it returns a list of
failures, and an empty list is the only passing outcome.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

SCHEMA_VERSION = 1
LANES = ('published-artifact', 'candidate-build')
SCENARIOS = {
    # scenario -> state assertions the app readback must contain
    'no-homebrew': {'brew_available': False, 'brew_missing_banner_revealed': True},
    'populated-fixture': {'brew_available': True, 'fixture_loaded': True},
}
PNG_MAGIC = b'\x89PNG\r\n\x1a\n'
UNKNOWN = 'unknown'
ALLOWED_KEYS = {
    'schema_version', 'lane', 'scenario', 'run', 'artifact', 'source',
    'environment', 'state', 'frames', 'failures', 'cleanup',
}


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b''):
            digest.update(chunk)
    return digest.hexdigest()


def build_receipt(*, lane, scenario, run, artifact, source, environment,
                  state, out_dir, failures=(), cleanup=None):
    """Hash every PNG in ``out_dir`` into a receipt dict."""
    out_dir = Path(out_dir)
    frames = {p.name: sha256_file(p) for p in sorted(out_dir.glob('*.png'))}
    return {
        'schema_version': SCHEMA_VERSION,
        'lane': lane,
        'scenario': scenario,
        'run': dict(run),
        'artifact': dict(artifact),
        'source': dict(source),
        'environment': dict(environment),
        'state': dict(state),
        'frames': frames,
        'failures': list(failures),
        'cleanup': dict(cleanup or {}),
    }


def verify(receipt, out_dir, *, expect):
    """Return failure strings; empty means the receipt is acceptable.

    ``expect`` carries what this run must have produced: ``lane``,
    ``scenario``, ``run_id``, ``run_attempt``, ``app_id``, ``runtime``
    (expected runtime ref/commit), and for the candidate lane
    ``source_sha`` and ``bundle_sha256``. All of these are required: an
    expectation that is missing or empty fails the receipt, so an absent
    digest can never match an absent digest.
    """
    out_dir = Path(out_dir)
    bad = []
    required = ['lane', 'scenario', 'run_id', 'run_attempt', 'app_id',
                'runtime']
    if expect.get('lane') == 'candidate-build':
        required += ['source_sha', 'bundle_sha256']
    for key in required:
        if not expect.get(key):
            bad.append(f'expectation {key!r} not supplied')
    if bad:
        return bad
    if not isinstance(receipt, dict):
        return ['receipt is not an object']
    extra = set(receipt) - ALLOWED_KEYS
    if extra:
        bad.append(f'non-allowlisted receipt keys: {sorted(extra)}')
    if receipt.get('schema_version') != SCHEMA_VERSION:
        bad.append('unsupported schema_version')

    lane = receipt.get('lane')
    if lane not in LANES:
        bad.append(f'unknown lane {lane!r}')
    if lane != expect['lane']:
        bad.append(f'lane {lane!r} is not the expected {expect["lane"]!r}')
    if receipt.get('scenario') != expect['scenario']:
        bad.append('scenario does not match the one under review')
    if receipt.get('scenario') not in SCENARIOS:
        bad.append('unknown scenario')

    run = receipt.get('run') or {}
    if str(run.get('id')) != str(expect['run_id']) or \
            str(run.get('attempt')) != str(expect['run_attempt']):
        bad.append('receipt is from another workflow run (stale)')

    artifact = receipt.get('artifact') or {}
    source = receipt.get('source') or {}
    if artifact.get('app_id') != expect['app_id']:
        bad.append('wrong app id')
    if artifact.get('runtime') != expect['runtime']:
        bad.append('wrong runtime')
    if not artifact.get('app_commit') or artifact.get('app_commit') == UNKNOWN:
        bad.append('app commit/digest not recorded')

    if expect['lane'] == 'published-artifact':
        # Never infer source from the checked-out PR.
        if source.get('binding') != UNKNOWN:
            bad.append('published lane must record source binding as unknown')
    else:
        if artifact.get('source') != 'bundle':
            bad.append('candidate lane did not install the built bundle '
                       '(published package substituted?)')
        if artifact.get('bundle_sha256') != expect['bundle_sha256']:
            bad.append('bundle digest does not match the built candidate')
        if source.get('commit') != expect['source_sha']:
            bad.append('source digest does not match the candidate commit')
        if source.get('binding') != 'bundle-built-from-commit':
            bad.append('candidate source binding missing')

    state = receipt.get('state') or {}
    want = SCENARIOS.get(receipt.get('scenario'), {})
    if not state.get('readback'):
        bad.append('no app-state readback (window visibility is not enough)')
    if state.get('screen') in ('loading', 'error'):
        bad.append(f'app frozen on {state["screen"]} screen')
    if state.get('window_owner') != expect['app_id']:
        bad.append('window owner is not the target app (unrelated window)')
    for key, value in want.items():
        if state.get(key) != value:
            bad.append(f'state assertion failed: {key} != {value!r}')
    if receipt.get('scenario') == 'no-homebrew' and \
            not state.get('no_homebrew_message'):
        bad.append('expected no-Homebrew message missing')

    frames = receipt.get('frames') or {}
    if not frames:
        bad.append('missing capture: no frames')
    on_disk = {p.name for p in out_dir.glob('*.png')}
    if on_disk != set(frames):
        bad.append('frames on disk differ from the receipt manifest '
                   f'(stale or foreign images: {sorted(on_disk ^ set(frames))})')
    for name, digest in frames.items():
        path = out_dir / name
        if not path.is_file():
            continue
        with open(path, 'rb') as handle:
            if handle.read(8) != PNG_MAGIC:
                bad.append(f'{name} is not a PNG')
        if sha256_file(path) != digest:
            bad.append(f'{name} hash differs from receipt (stale PNG)')

    if receipt.get('failures'):
        bad.append(f'recorded failures: {receipt["failures"]}')
    if not (receipt.get('cleanup') or {}).get('completed'):
        bad.append('owned-cleanup result missing or incomplete')
    return bad


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='cmd', required=True)
    v = sub.add_parser('verify', help='verify a receipt against expectations')
    v.add_argument('--receipt', required=True)
    v.add_argument('--out-dir', required=True)
    v.add_argument('--lane', required=True, choices=LANES)
    v.add_argument('--scenario', required=True, choices=sorted(SCENARIOS))
    v.add_argument('--run-id', required=True)
    v.add_argument('--run-attempt', required=True)
    v.add_argument('--app-id', default='org.tunaos.tavern')
    v.add_argument('--runtime', required=True)
    v.add_argument('--source-sha')
    v.add_argument('--bundle-sha256')
    args = parser.parse_args(argv)
    receipt = json.loads(Path(args.receipt).read_text())
    expect = {
        'lane': args.lane, 'scenario': args.scenario,
        'run_id': args.run_id, 'run_attempt': args.run_attempt,
        'app_id': args.app_id, 'runtime': args.runtime,
        'source_sha': args.source_sha, 'bundle_sha256': args.bundle_sha256,
    }
    failures = verify(receipt, args.out_dir, expect=expect)
    for line in failures:
        print(f'FAIL: {line}', file=sys.stderr)
    if failures:
        return 1
    print(f'ok: {args.lane}/{args.scenario} receipt accepted')
    return 0


if __name__ == '__main__':
    sys.exit(main())
