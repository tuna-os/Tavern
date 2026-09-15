"""Read-only Homebrew diagnostics, independent of GTK."""
# SPDX-License-Identifier: GPL-3.0-or-later

from dataclasses import dataclass
import hashlib
import json
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
    tier: object = None
    warnings: str = ''


class DoctorError(Exception):
    """The command failed without a usable diagnostic report."""


def parse_report(output, returncode):
    text = _ANSI.sub('', output)
    if text.lstrip().startswith(('{', '[')):
        return parse_json_report(text, returncode)
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


def parse_json_report(text, returncode):
    """Homebrew 7 Finding#to_h; remediation stays text, never executable."""
    try:
        data = json.loads(text)
        if returncode not in (0, 1) or not isinstance(data, dict):
            raise ValueError('Invalid diagnostic response')
        findings = data['findings']
        tier = data['tier']
        if not isinstance(findings, list) or tier not in (1, 2, 3, 'unsupported'):
            raise ValueError('Invalid diagnostic findings or support tier')
        if returncode == 1 and not findings:
            raise ValueError('Doctor failed without diagnostic findings')
        issues = []
        for finding in findings:
            if not isinstance(finding, dict) or not isinstance(finding.get('text'), str):
                raise ValueError('Invalid diagnostic finding')
            lines = finding['text'].strip().splitlines()
            if not lines:
                raise ValueError('Empty diagnostic finding')
            body = '\n'.join(lines[1:])
            remediation = finding.get('remediation')
            if remediation is not None:
                if not isinstance(remediation, dict):
                    raise ValueError('Invalid remediation')
                commands = remediation.get('commands', [])
                explanation = remediation.get('text', '')
                if not isinstance(commands, list) or not all(isinstance(c, str) for c in commands):
                    raise ValueError('Invalid remediation commands')
                if not isinstance(explanation, str):
                    raise ValueError('Invalid remediation text')
                body += '\n' + explanation + '\n' + '\n'.join(commands)
            severity = 'unsupported' if finding.get('tier') in (3, 'unsupported') else 'warning'
            issues.append(DoctorIssue(lines[0], body.strip(), severity))
        issues.sort(key=lambda issue: issue.severity != 'unsupported')
        return DoctorReport(tuple(issues), text, tier)
    except (KeyError, TypeError, ValueError) as error:
        raise DoctorError(f'Invalid Homebrew diagnostic JSON: {error}') from error


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
            stderr = getattr(result, 'stderr', '') or ''
            try:
                report = parse_report(result.stdout or '', result.returncode)
            except DoctorError as error:
                raise DoctorError(str(error) + ('\n' + stderr if stderr else '')) from error
            if stderr:
                report = DoctorReport(report.issues,
                                      report.raw_output + '\n\n' + stderr, report.tier, stderr)
            self._report = report
            self._reported_at = self._clock()
            return report
