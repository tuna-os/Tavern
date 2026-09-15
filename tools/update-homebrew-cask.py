#!/usr/bin/env python3
"""Update release fields without regenerating the tap-owned cask."""

import argparse
import hashlib
from pathlib import Path
import re


def update_cask(source, version, macos_sha256, linux_sha256):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('version must be X.Y.Z')
    for digest in (macos_sha256, linux_sha256):
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('invalid SHA-256')

    versions = list(re.finditer(r'(?m)^  version "(\d+\.\d+\.\d+)"$', source))
    if len(versions) != 1:
        raise ValueError('expected one top-level version')
    current = versions[0]
    if tuple(map(int, version.split('.'))) < tuple(map(int, current[1].split('.'))):
        raise ValueError('refusing to downgrade the cask')
    replacements = [(current.start(1), current.end(1), version)]
    for platform, digest in [('macos', macos_sha256), ('linux', linux_sha256)]:
        matches = list(re.finditer(
            rf'(?m)^  on_{platform} do\n    sha256 "([0-9a-f]{{64}})"$', source
        ))
        if len(matches) != 1:
            raise ValueError(f'expected one {platform} checksum immediately after its block header')
        match = matches[0]
        replacements.append((match.start(1), match.end(1), digest))
    if len(re.findall(r'(?m)^\s*sha256\s', source)) != 2:
        raise ValueError('expected exactly two platform checksums')
    for start, end, value in sorted(replacements, reverse=True):
        source = source[:start] + value + source[end:]
    return source


def checksum(path):
    with path.open('rb') as artifact:
        return hashlib.file_digest(artifact, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cask', type=Path)
    parser.add_argument('--version', required=True)
    parser.add_argument('--macos', required=True, type=Path)
    parser.add_argument('--linux', required=True, type=Path)
    args = parser.parse_args()
    source = args.cask.read_text()
    updated = update_cask(source, args.version, checksum(args.macos), checksum(args.linux))
    args.cask.write_text(updated)


if __name__ == '__main__':
    main()
