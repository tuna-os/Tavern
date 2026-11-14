"""Read-only Homebrew diagnostics, independent of GTK."""
# SPDX-License-Identifier: GPL-3.0-or-later

from dataclasses import dataclass
import gettext
import hashlib
import json
import re
import threading
import time

_ = gettext.gettext

REPORT_TTL = 3600
_ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)')
_FINDING = re.compile(r'^(Warning|Error):\s*(.*)$', re.MULTILINE)


@dataclass(frozen=True)
class DoctorIssue:
    title: str
    body: str
    severity: str
    blocks: tuple = ()  # typed blocks in document order; body is the verbatim text they were parsed from

    @property
    def content_id(self):
        return hashlib.sha256((self.title + '\n' + self.body).encode()).hexdigest()

    @property
    def is_runnable(self) -> bool:
        return any(block.is_runnable for block in self.blocks)

    @property
    def runnable_block(self):
        for block in self.blocks:
            if block.is_runnable:
                return block
        return None


@dataclass(frozen=True)
class DoctorReport:
    issues: tuple
    raw_output: str
    tier: object = None
    warnings: str = ''

# Display order for the Doctor list; unsupported is the least supported state.
SEVERITY_ORDER = ('unsupported', 'error', 'warning')


def severity_groups(issues):
    """Group ``issues`` by severity in display order (unsupported > error > warning).

    Returns ``[(key, [issue, ...]), ...]`` with empty groups skipped, ordered by
    :data:`SEVERITY_ORDER` regardless of the order the issues arrive in. Mirrors
    the sort ``parse_report`` applies, so the list renders grouped and ordered.
    """
    buckets = {key: [] for key in SEVERITY_ORDER}
    for issue in issues:
        buckets.setdefault(issue.severity, []).append(issue)
    return [(key, buckets[key]) for key in SEVERITY_ORDER if buckets[key]]


def select_after_reload(previous_content_id, issues):
    """Choose the issue to select after a report reload.

    Follows the previously selected issue by ``content_id`` when it is still
    present (it may have moved position), otherwise falls back to the first
    issue, or ``None`` when there is nothing to select. ``content_id`` is a
    stable hash of title+body, so it survives a reload that reorders issues.
    """
    if previous_content_id is not None:
        for issue in issues:
            if issue.content_id == previous_content_id:
                return issue
    return issues[0] if issues else None


# MARK: - Block model

# A brew doctor finding parses into an ordered list of typed blocks (document order). Keeping the
# blocks — and each command bound to its own data block — lets a renderer extract a safe fix instead
# of treating the whole body as one opaque string.
_BLOCK_PROSE = 'prose'
_BLOCK_COMMAND = 'command'
_BLOCK_DATA = 'data'
_BLOCK_LINK = 'link'

# brew keeps destructive lines in the free text, never in remediation.commands, so this allowlist is
# the only thing that turns an indented line into a command step — mirroring BrewUI's knownExecutables.
_KNOWN_EXECUTABLES = frozenset({
    'brew', 'git', 'rm', 'mkdir', 'chown', 'chmod', 'cp', 'mv', 'ln',
    'xcode-select', 'softwareupdate', 'csrutil', 'launchctl',
    'pip', 'pip3', 'python', 'python3', 'ruby', 'bash', 'zsh',
    'echo', 'fish_add_path', 'set',
})
# A colon intro naming a list forces a .data block before the first-member test, so a list whose first
# item reads as a command (e.g. "tools exist at both paths:" then "pip3") stays data, not a command.
_DATA_NOUN_CUE = (
    'tools', 'formulae', 'casks', 'taps', 'directories', 'kegs', 'places', 'files', 'paths',
)
# A couple of unindented captions take their items at column zero, so they open a .data block even
# before any indented member arrives.
_UNINDENTED_DATA_CUE = ('do not exist:', 'not writable by your user:')

_URL = re.compile(r'https?://[^\s]+', re.IGNORECASE)


@dataclass(frozen=True)
class DoctorLink:
    """A URL surfaced from a link block, classified by what the user is meant to do with it."""
    url: str
    role: str  # 'action' for developer.apple.com / macports.org, else 'reference'


@dataclass(frozen=True)
class DoctorFixStep:
    """One command line as brew printed it.

    ``arguments`` is the brew argv with the leading 'brew' dropped, so it is only present for a
    runnable brew invocation; sudo, external, and multi-tool steps never submit a fix.
    """
    display_command: str
    arguments: tuple | None = None
    needs_admin: bool = False


@dataclass(frozen=True)
class DoctorBlock:
    """One typed block in a DoctorIssue's body, kept in document order with its intro caption."""
    type: str
    value: tuple = ()  # [str] prose/data, [DoctorFixStep] command, [DoctorLink] link
    caption: str = ''
    preceded_by_blank_line: bool = False

    @property
    def is_runnable(self) -> bool:
        # Exactly one command step, a single brew invocation with extractable argv, no sudo.
        if self.type != _BLOCK_COMMAND or len(self.value) != 1:
            return False
        step = self.value[0]
        return step.arguments is not None and not step.needs_admin

    @property
    def runnable_step(self):
        return self.value[0] if self.is_runnable else None


def _first_url(line: str):
    match = _URL.search(line)
    return match.group(0).strip() if match else None


def _contains_link(line: str) -> bool:
    return _URL.search(line) is not None


def _link_role(url: str) -> str:
    host = url.split('//', 1)[-1].split('/', 1)[0]
    if host.startswith('www.'):
        host = host[4:]
    return 'action' if host in ('developer.apple.com', 'macports.org') else 'reference'


def _looks_like_item(trimmed: str) -> bool:
    return trimmed.startswith('/') or not any(ch.isspace() for ch in trimmed)


def _data_noun_cue(intro: str) -> bool:
    lower = intro.lower()
    return any(cue in lower for cue in _DATA_NOUN_CUE)


def _accepts_unindented_items(cue: str) -> bool:
    lower = cue.lower()
    return any(lower.endswith(suffix) for suffix in _UNINDENTED_DATA_CUE)


# Shell syntax means the printed line is more than one plain argv; such a step stays copy-only.
_SHELL_SYNTAX = re.compile(r'[;&|<>`$(){}*?~\'"\\]')


def _parse_fix_step(trimmed: str):
    tokens = trimmed.split()
    needs_admin = bool(tokens) and tokens[0] == 'sudo'
    if needs_admin:
        tokens = tokens[1:]
    # Drop a leading `env` and any KEY=VALUE assignments that merely set up the command.
    has_env_prefix = False
    while tokens and (tokens[0] == 'env' or '=' in tokens[0]):
        tokens = tokens[1:]
        has_env_prefix = True
    if not tokens or tokens[0] not in _KNOWN_EXECUTABLES:
        return None
    executable = tokens[0]
    arguments = None
    # Only a plain `brew ...` argv is extractable: running it without its env prefix or with shell
    # syntax split into literal arguments would not be the command brew printed.
    if (executable == 'brew' and not needs_admin and not has_env_prefix and len(tokens) > 1
            and not _SHELL_SYNTAX.search(trimmed)):
        arguments = tuple(tokens[1:])
    return DoctorFixStep(display_command=trimmed, arguments=arguments, needs_admin=needs_admin)


def _decide_block_type(first_member: str, intro: str) -> str:
    # A data-noun cue wins even when the first item reads as a command; otherwise the first member decides.
    if _data_noun_cue(intro):
        return _BLOCK_DATA
    if _parse_fix_step(first_member) is not None:
        return _BLOCK_COMMAND
    if _contains_link(first_member):
        return _BLOCK_LINK
    return _BLOCK_DATA


class _BlockBuilder:
    def __init__(self, block_type, caption=None, preceded_by_blank_line=False):
        self.type = block_type
        self.caption = caption
        self.preceded_by_blank_line = preceded_by_blank_line
        self.prose_lines = []
        self.command_steps = []
        self.data_items = []
        self.link_items = []


class _BodyBlockParser:
    """Walks a finding body line by line, emitting typed blocks in document order.

    Mirrors BrewUI's DoctorOutputParser: an unindented colon-terminated line is a caption waiting for
    its first indented member to decide the block type; an indented member joins the block the caption
    opened, or — for a stray command with no caption — opens a command block so a fix is not lost to
    the prose.
    """

    def __init__(self, body_lines, caption=None):
        self.committed = []
        self.current = None
        self.pending_caption = caption
        self.special_unindented_active = False
        self.next_block_follows_blank_line = False
        self.body_lines = body_lines

    def parse(self):
        for line in self.body_lines:
            self._process_line(line)
        self._flush_current()
        self._merge_same_paragraph_captions()
        return tuple(self.committed)

    def _consume_blank_line(self) -> bool:
        value = self.next_block_follows_blank_line
        self.next_block_follows_blank_line = False
        return value

    def _flush_current(self):
        builder = self.current
        self.current = None
        if builder is None:
            return
        content = {
            _BLOCK_PROSE: builder.prose_lines,
            _BLOCK_COMMAND: builder.command_steps,
            _BLOCK_DATA: builder.data_items,
            _BLOCK_LINK: builder.link_items,
        }[builder.type]
        if not content:
            return
        self.committed.append(DoctorBlock(
            type=builder.type,
            value=tuple(content),
            caption=builder.caption or '',
            preceded_by_blank_line=builder.preceded_by_blank_line,
        ))

    def _process_line(self, line):
        if not (line[:1] in (' ', '\t')):
            self._process_unindented(line.strip())
            return
        trimmed = line.strip()
        if not trimmed:
            return
        self._process_indented(trimmed)

    def _process_unindented(self, trimmed):
        if trimmed == '':
            self._flush_current()
            self.pending_caption = None
            self.special_unindented_active = False
            self.next_block_follows_blank_line = True
            return
        if trimmed.endswith(':'):
            self._flush_current()
            self.pending_caption = trimmed
            self.special_unindented_active = _accepts_unindented_items(trimmed)
            return
        if self._collect_unindented_data_item(trimmed):
            return
        self._append_prose_line(trimmed)

    def _collect_unindented_data_item(self, trimmed):
        if self.special_unindented_active and _looks_like_item(trimmed) and not _contains_link(trimmed):
            if self.current is None or self.current.type != _BLOCK_DATA:
                self._flush_current()
                self.current = _BlockBuilder(
                    _BLOCK_DATA, caption=self.pending_caption, preceded_by_blank_line=self._consume_blank_line())
                self.pending_caption = None
            self.current.data_items.append(trimmed)
            return True
        return False

    def _append_prose_line(self, trimmed):
        orphaned_caption = self.pending_caption
        if self.pending_caption is not None:
            self.pending_caption = None
            self.special_unindented_active = False
        if self.current is None or self.current.type != _BLOCK_PROSE:
            self._flush_current()
            self.current = _BlockBuilder(_BLOCK_PROSE, preceded_by_blank_line=self._consume_blank_line())
        if orphaned_caption is not None:
            self.current.prose_lines.append(orphaned_caption)
        self.current.prose_lines.append(trimmed)

    def _process_indented(self, trimmed):
        if self.pending_caption is not None:
            self._flush_current()
            self.current = _BlockBuilder(
                _decide_block_type(trimmed, self.pending_caption),
                caption=self.pending_caption, preceded_by_blank_line=self._consume_blank_line())
            self.pending_caption = None
        elif (self.current is None or self.current.type == _BLOCK_PROSE) and _parse_fix_step(trimmed) is not None:
            self._flush_current()
            self.current = _BlockBuilder(_BLOCK_COMMAND, preceded_by_blank_line=self._consume_blank_line())
        elif self.current is None:
            self.current = _BlockBuilder(_BLOCK_PROSE, preceded_by_blank_line=self._consume_blank_line())
        self._append_to_current(trimmed)

    def _append_to_current(self, trimmed):
        if self.current is None:
            return
        if self.current.type == _BLOCK_PROSE:
            self.current.prose_lines.append(trimmed)
        elif self.current.type == _BLOCK_COMMAND:
            step = _parse_fix_step(trimmed)
            if step is not None:
                self.current.command_steps.append(step)
        elif self.current.type == _BLOCK_DATA:
            if not _contains_link(trimmed):
                self.current.data_items.append(trimmed)
        else:
            url = _first_url(trimmed)
            if url is not None:
                self.current.link_items.append(DoctorLink(url=url, role=_link_role(url)))

    def _merge_same_paragraph_captions(self):
        # A caption not separated from a preceding prose block by a blank line is one continuous
        # paragraph; fold the caption onto the prose so the whole thing renders as one block.
        for index in range(1, len(self.committed)):
            current = self.committed[index]
            prior = self.committed[index - 1]
            if current.preceded_by_blank_line or not current.caption or prior.type != _BLOCK_PROSE:
                continue
            self.committed[index - 1] = DoctorBlock(
                type=_BLOCK_PROSE,
                value=tuple(prior.value) + (current.caption,),
                caption=prior.caption,
                preceded_by_blank_line=prior.preceded_by_blank_line,
            )
            self.committed[index] = DoctorBlock(
                type=current.type, value=current.value, caption='',
                preceded_by_blank_line=current.preceded_by_blank_line,
            )


def parse_blocks(body_lines, caption=None):
    """Parse a finding body into typed blocks in document order.

    ``caption`` is the finding title when it ends with a colon, so it opens the first block as a
    caption — mirroring BrewUI, where the title acts as the initial pending caption.
    """
    return _BodyBlockParser(body_lines, caption=caption).parse()


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
        raw_body = text[match.end():end]
        body = raw_body.strip()
        severity = 'error' if match[1] == 'Error' else 'warning'
        if re.search(r'unsupported configuration|tier 3 configuration', body, re.IGNORECASE):
            severity = 'unsupported'
        title = match[2].strip()
        blocks = parse_blocks(raw_body.strip('\n').split('\n'), caption=title if title.endswith(':') else None) if raw_body.strip('\n') else ()
        issues.append(DoctorIssue(title, body, severity, blocks))
    # brew doctor exits 1 when it has warnings. Other command failures must
    # not become a healthy report or hide behind a partial warning transcript.
    if returncode not in (0, 1) or (returncode == 1 and not issues):
        raise DoctorError(text.strip() or f'brew doctor exited with status {returncode}')
    order = {'unsupported': 0, 'error': 1, 'warning': 2}
    issues.sort(key=lambda issue: order[issue.severity])
    return DoctorReport(tuple(issues), text)


def parse_json_report(text, returncode):
    """Homebrew 7 Finding#to_h; remediation commands become a command block, never a flat string."""
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
            issues.append(_json_issue(
                lines[0], finding, 'unsupported' if finding.get('tier') in (3, 'unsupported') else 'warning'))
        issues.sort(key=lambda issue: issue.severity != 'unsupported')
        return DoctorReport(tuple(issues), text, tier)
    except (KeyError, TypeError, ValueError) as error:
        raise DoctorError(f'Invalid Homebrew diagnostic JSON: {error}') from error

def _json_issue(title, finding, severity):
    """Build one issue from a Homebrew 7 finding, parsing its body into blocks.

    brew wraps URLs in underline escapes and renders remediation as prose plus indented commands, so
    the body is assembled the way brew would print it and then parsed by the same block parser as the
    text path: a remediation command becomes a .command block bound to its own caption, and unlisted
    affects/links become .data/.link blocks.
    """
    text = finding['text'].strip()
    remediation = finding.get('remediation')
    # The title is the first line and stays out of the body, matching the text path where the finding
    # title is never part of the parsed body.
    body_lines = list(text.splitlines()[1:])
    if remediation is not None:
        if not isinstance(remediation, dict):
            raise ValueError('Invalid remediation')
        commands = remediation.get('commands', [])
        explanation = remediation.get('text', '')
        if not isinstance(commands, list) or not all(isinstance(c, str) for c in commands):
            raise ValueError('Invalid remediation commands')
        if not isinstance(explanation, str):
            raise ValueError('Invalid remediation text')
        if explanation:
            body_lines.append(explanation)
        elif commands:
            # brew introduces command-only remediation with its own caption.
            body_lines.append('You can solve this by running:')
        body_lines.extend('  ' + command for command in commands)
    blocks = parse_blocks(body_lines)
    affects = finding.get('affects', [])
    if isinstance(affects, list) and any(item not in text for item in affects):
        blocks = blocks + (DoctorBlock(type=_BLOCK_DATA, value=tuple(affects), caption='Affects:',
                                       preceded_by_blank_line=True),)
    links = finding.get('links', [])
    if isinstance(links, list) and any(link not in text for link in links):
        parsed = [DoctorLink(url=link, role='reference') for link in links if link not in text]
        blocks = blocks + (DoctorBlock(type=_BLOCK_LINK, value=tuple(parsed), caption='More information:',
                                       preceded_by_blank_line=True),)
    body = '\n'.join(body_lines)
    return DoctorIssue(title, body, severity, blocks)


def run_doctor(runner):
    """Run `brew doctor` through ``runner``; prefer JSON, fall back on pre-7 Homebrew."""
    from .brew_env import is_brew_available
    from .brew_commands import transcript
    if not is_brew_available():
        raise DoctorError(_('Homebrew is not installed.'))
    result = runner(('doctor', '--json'), timeout=60)
    if result.returncode and any(message in transcript(result).lower() for message in
                                ('invalid option: --json', 'unknown option: --json')):
        # Pre-7 Homebrew: warnings are printed to stderr in the text format.
        result = runner(('doctor',), timeout=60)
        result.stdout = transcript(result)
        result.stderr = ''
    else:
        result.doctor_json = True
    return result


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
                parser = parse_json_report if getattr(result, 'doctor_json', False) else parse_report
                report = parser(result.stdout or '', result.returncode)
            except DoctorError as error:
                raise DoctorError(str(error) + ('\n' + stderr if stderr else '')) from error
            if stderr:
                report = DoctorReport(report.issues,
                                      report.raw_output + '\n\n' + stderr, report.tier, stderr)
            self._report = report
            self._reported_at = self._clock()
            return report
