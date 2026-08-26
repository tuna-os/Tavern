#!/usr/bin/env python3
"""Guard release inputs against mutable downloads and network installs."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / '.github' / 'workflows' / 'release.yml', ROOT / 'org.tunaos.tavern.json']


def main():
    errors = []
    for path in TARGETS:
        text = path.read_text()
        for pattern, message in (
            (r'/continuous/', 'continuous release download'),
            (r'raw\.githubusercontent\.com/[^/]+/[^/]+/(?:master|main)/', 'mutable raw branch download'),
            (r'pip3? install(?![^\n]*(?:==|--no-index))', 'unversioned/network pip install'),
        ):
            if re.search(pattern, text):
                errors.append(f'{path.relative_to(ROOT)}: {message}')
    manifest = (ROOT / 'org.tunaos.tavern.json').read_text()
    if '"tag": "v0.22.2"' in manifest and '"commit":' not in manifest:
        errors.append('org.tunaos.tavern.json: tagged git source needs a commit')
    if errors:
        print('\n'.join(errors))
        return 1
    print('Supply-chain policy check passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
