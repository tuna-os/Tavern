#!/usr/bin/env python3
"""Fail when a Blueprint-visible literal bypasses gettext extraction."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VISIBLE_LITERAL = re.compile(
    r'^\s*(label|title|description|placeholder-text|tooltip-text):\s*"'
)


def main():
    errors = []
    potfiles = set(
        line.strip() for line in (ROOT / 'po' / 'POTFILES.in').read_text().splitlines()
        if line.strip() and not line.lstrip().startswith('#')
    )
    for path in sorted((ROOT / 'src').glob('*.blp')):
        relative = path.relative_to(ROOT).as_posix()
        if relative not in potfiles:
            errors.append(f'{relative}: missing from po/POTFILES.in')
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            if VISIBLE_LITERAL.search(line):
                errors.append(
                    f'{relative}:{line_number}: visible string must use _("…")')
    if errors:
        print('\n'.join(errors))
        return 1
    print('Translation coverage check passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
