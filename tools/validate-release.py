#!/usr/bin/env python3
"""Validate Tavern's single-source release contract."""

import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def project_version():
    match = re.search(
        r"project\('tavern',\s*\n\s*version:\s*'([^']+)'",
        (ROOT / 'meson.build').read_text(),
    )
    if not match:
        raise ValueError('could not read project version from meson.build')
    return match.group(1)


def appstream_versions():
    text = (ROOT / 'data' / 'org.tunaos.tavern.metainfo.xml.in').read_text()
    return re.findall(r'<release\s+version="([^"]+)"', text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version')
    parser.add_argument('--tag')
    args = parser.parse_args()
    expected = args.version or (args.tag[1:] if args.tag and args.tag.startswith('v') else None)
    if not expected:
        parser.error('provide --version or a v-prefixed --tag')

    errors = []
    meson_version = project_version()
    if expected != meson_version:
        errors.append(f'requested {expected}, but meson.build is {meson_version}')
    releases = appstream_versions()
    if not releases or releases[0] != expected:
        actual = releases[0] if releases else 'missing'
        errors.append(f'latest AppStream release is {actual}, expected {expected}')
    if errors:
        print('\n'.join(f'error: {error}' for error in errors), file=sys.stderr)
        return 1
    print(f'Release contract validated for Tavern {expected}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
