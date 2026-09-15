"""Read-only Homebrew diagnostics, independent of GTK."""
# SPDX-License-Identifier: GPL-3.0-or-later

from dataclasses import dataclass
import hashlib
import re
import threading
import time

REPORT_TTL = 3600
_ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)')
_FINDING = re.compile(r'^(Warning|Error):\s*(.*)$', re.MULTILINE)


@dataclass(frozen=True)
class DoctorIssue:
    title: str
    body: str
    severity: str

    @property
    def content_id(self):
        return hashlib.sha256((self.title + '\n' + self.body).encode()).hexdigest()


@dataclass(frozen=True)
class DoctorReport:
    issues: tuple
    raw_output: str


class DoctorError(Exception):
    """The command failed without a usable diagnostic report."""


def parse_report(output, returncode):
    text = _ANSI.sub('', output)
    starts = list(_FINDING.finditer(text))
    issues = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        body = text[match.end():end].strip()
        severity = 'error' if match[1] == 'Error' else 'warning'
        if re.search(r'unsupported configuration|tier 3 configuration', body, re.IGNORECASE):
            severity = 'unsupported'
        issues.append(DoctorIssue(match[2].strip(), body, severity))
    # brew doctor exits 1 when it has warnings. Other command failures must
    # not become a healthy report or hide behind a partial warning transcript.
    if returncode not in (0, 1) or (returncode == 1 and not issues):
        raise DoctorError(text.strip() or f'brew doctor exited with status {returncode}')
    order = {'unsupported': 0, 'error': 1, 'warning': 2}
    issues.sort(key=lambda issue: order[issue.severity])
    return DoctorReport(tuple(issues), text)


class DoctorService:
    """Cache successful reports in memory; serialize concurrent reads."""

    def __init__(self, runner, clock=time.monotonic):
        self._runner = runner
        self._clock = clock
        self._lock = threading.Lock()
        self._report = None
        self._reported_at = 0

    def load(self, force=False):
        with self._lock:
            if not force and self._report is not None and self._clock() - self._reported_at < REPORT_TTL:
                return self._report
            result = self._runner()
            report = parse_report(result.stdout or '', result.returncode)
            self._report = report
            self._reported_at = self._clock()
            return report
