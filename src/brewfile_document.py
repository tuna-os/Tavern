"""Brewfile source identity and non-evaluating display of extended entries."""
# SPDX-License-Identifier: GPL-3.0-or-later

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

_ENTRY = re.compile(r'^\s*(cargo|uv|npm|vscode(?:_insiders)?|go|mas|krew|winget)\s+[\"\']([^\"\']+)[\"\']')


@dataclass(frozen=True)
class BrewfileDocument:
    path: str
    source: str
    digest: str

    @classmethod
    def read(cls, path):
        path = str(Path(path).absolute())
        raw = Path(path).read_bytes()
        return cls(path, raw.decode('utf-8'), hashlib.sha256(raw).hexdigest())

    @property
    def extra_entries(self):
        """Display hints only; Ruby conditionals/interpolation are not evaluated."""
        return tuple(match.groups() for line in self.source.splitlines()
                     if (match := _ENTRY.match(line)))

    def verify(self):
        if hashlib.sha256(Path(self.path).read_bytes()).hexdigest() != self.digest:
            raise ValueError('The Brewfile changed after review. Reopen it and review it again.')

    @property
    def install_args(self):
        # Keep the original path for Ruby __dir__ and relative-file semantics.
        # Never reconstruct source from the decorative package tiles.
        return ('bundle', 'install', '--no-upgrade', '--file', self.path)

    @property
    def deps_args(self):
        return ('deps', '--brewfile=' + self.path)
