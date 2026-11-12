#!/usr/bin/env python3
"""Guard release inputs against mutable downloads and network installs."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / '.github' / 'workflows' / 'release.yml',
          ROOT / 'org.tunaos.tavern.json']
USES_REF_RE = re.compile(r'^\s*(?:-\s+)?uses:\s*(\S+)@(\S+)')
SHA40_RE = re.compile(r'[0-9a-f]{40}')
# actions.lock, written by `gh actions-lock`, lists each workflow's pinned
# `owner/repo@ref` entries under `workflows:` in this fixed shape.
LOCK_WORKFLOW_RE = re.compile(r"^ {4}'([^']+)':")
LOCK_ENTRY_RE = re.compile(r"^ {8}- '([^']+)'$")


def locked_refs(text):
    """Map each workflow path in actions.lock to the refs it pins."""
    locked = {}
    current = None
    in_workflows = False
    for line in text.splitlines():
        if not line.startswith(' '):
            in_workflows = line.startswith('workflows:')
            current = None
            continue
        if not in_workflows:
            continue
        workflow = LOCK_WORKFLOW_RE.match(line)
        if workflow:
            current = locked.setdefault(workflow.group(1), set())
            continue
        entry = LOCK_ENTRY_RE.match(line)
        if entry and current is not None:
            current.add(entry.group(1).lower())
    return locked


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
    # A tag passes only if actions.lock pins it for that workflow. The lock
    # does not cover cross-repo reusable workflows, so those need a SHA.
    lockfile = ROOT / '.github' / 'workflows' / 'actions.lock'
    locked = locked_refs(lockfile.read_text()) if lockfile.exists() else {}
    for path in sorted(ROOT.glob('.github/workflows/*.yml')):
        workflow = str(path.relative_to(ROOT))
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            match = USES_REF_RE.match(line)
            if not match:
                continue
            action, ref = match.groups()
            if SHA40_RE.fullmatch(ref):
                continue
            repo = '/'.join(action.split('/')[:2])
            if ('/.github/workflows/' not in action
                    and f'{repo}@{ref}'.lower() in locked.get(workflow, set())):
                continue
            errors.append(f'{workflow}:{lineno}: unpinned uses ref "@{ref}"')
    if errors:
        print('\n'.join(errors))
        return 1
    print('Supply-chain policy check passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
