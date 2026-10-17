"""The Doctor page renders reports and retries without real Homebrew calls."""
from types import SimpleNamespace

from tavern import doctor_page
from tavern.doctor import (
    parse_report, DoctorReport, DoctorIssue, DoctorBlock, DoctorFixStep, DoctorLink
)


def test_report_error_and_recovery(monkeypatch):
    page = doctor_page.TavernDoctorPage()
    report = parse_report('Warning: <unsafe markup>\n  brew cleanup\n', 1)
    page._complete(report, None)
    assert page.status_label.get_label() == 'Warnings found'
    row = page.findings_list.get_first_child()
    assert row.get_title() == '<unsafe markup>'
    assert not row.get_use_markup()
    assert page.copy_button.get_sensitive()
    copied = []
    monkeypatch.setattr(page, 'get_clipboard', lambda: SimpleNamespace(set=copied.append))
    page._copy_output(None)
    assert copied == [report.raw_output]
    page._complete(None, 'Timed out')
    assert page.error_label.get_visible()
    assert page._report is report
    assert 'previous report shown' in page.status_label.get_label()
    page._complete(parse_report('Ready to brew', 0), None)
    assert page.status_label.get_label() == 'No problems found'
    assert not page.findings_list.get_visible()


def test_refresh_suppresses_duplicate_runs_and_delivers_on_main_loop(monkeypatch):
    callbacks = []
    workers = []
    calls = []
    report = parse_report('Ready to brew', 0)
    service = SimpleNamespace(load=lambda **kwargs: calls.append(kwargs) or report)
    page = doctor_page.TavernDoctorPage(service=service)
    monkeypatch.setattr(doctor_page.threading, 'Thread', lambda **kwargs: SimpleNamespace(start=lambda: workers.append(kwargs['target'])))
    monkeypatch.setattr(doctor_page.GLib, 'idle_add', lambda *args: callbacks.append(args))
    page.refresh(force=True)
    page.refresh(force=True)
    assert len(workers) == 1
    assert not page.run_button.get_sensitive()
    workers[0]()
    assert calls == [{'force': True}]
    assert page._report is None
    callback, *args = callbacks[0]
    assert callback(*args) is False
    assert page._report is report
    assert page.run_button.get_sensitive()


def test_runner_requests_structured_output_and_preserves_warnings(monkeypatch):
    calls = []
    result = SimpleNamespace(stdout='{"findings": [], "tier": 1}', stderr='Extra warning', returncode=0)
    monkeypatch.setattr(doctor_page, 'run_read', lambda *args, **kwargs: calls.append((args, kwargs)) or result)
    assert doctor_page._run_doctor() is result
    assert calls == [((('doctor', '--json'),), {'timeout': 60})]


def test_runner_falls_back_only_for_unsupported_json(monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if '--json' in args:
            return SimpleNamespace(stdout='', stderr='Error: invalid option: --json', returncode=1)
        return SimpleNamespace(stdout='', stderr='Warning: Unlinked kegs', returncode=1)
    monkeypatch.setattr(doctor_page, 'run_read', run)
    result = doctor_page._run_doctor()
    assert calls == [('doctor', '--json'), ('doctor',)]
    assert result.stdout == 'Warning: Unlinked kegs'
    assert result.stderr == ''


def _report(*issues):
    return DoctorReport(issues=tuple(issues), raw_output='raw')


def _titles(page):
    titles = []
    child = page.findings_list.get_first_child()
    while child is not None:
        titles.append(child.get_title())
        child = child.get_next_sibling()
    return titles


def _by_title(page, title):
    child = page.findings_list.get_first_child()
    while child is not None:
        if child.get_title() == title:
            return child
        child = child.get_next_sibling()
    return None


def test_list_grouped_by_severity_in_display_order():
    page = doctor_page.TavernDoctorPage()
    page._complete(_report(
        DoctorIssue('warn', 'body', 'warning'),
        DoctorIssue('unsupported', 'body', 'unsupported'),
        DoctorIssue('error', 'body', 'error'),
    ), None)
    # Display order is unsupported, then error, then warning.
    assert _titles(page) == ['unsupported', 'error', 'warn']


def test_selection_follows_issue_when_reordered():
    page = doctor_page.TavernDoctorPage()
    page._complete(_report(
        DoctorIssue('first', 'b1', 'warning'),
        DoctorIssue('second', 'b2', 'error'),
    ), None)
    second = _by_title(page, 'second')
    page.findings_list.select_row(second)

    # Reload with the issues in a different order; selection follows it.
    page._complete(_report(
        DoctorIssue('second', 'b2', 'error'),
        DoctorIssue('first', 'b1', 'warning'),
    ), None)
    selected = page.findings_list.get_selected_row()
    assert selected is not None
    assert selected.get_title() == 'second'


def test_selection_dropped_and_defaults_to_first_when_resolved():
    page = doctor_page.TavernDoctorPage()
    page._complete(_report(
        DoctorIssue('keep', 'b1', 'warning'),
        DoctorIssue('gone', 'b2', 'error'),
    ), None)
    gone = _by_title(page, 'gone')
    page.findings_list.select_row(gone)

    # 'gone' resolved on reload: selection falls back to the first issue.
    page._complete(_report(DoctorIssue('keep', 'b1', 'warning')), None)
    selected = page.findings_list.get_selected_row()
    assert selected is not None
    assert selected.get_title() == 'keep'


def test_detail_panels_selected_issue():
    page = doctor_page.TavernDoctorPage()
    page._complete(_report(DoctorIssue('Broken tap', 'Repair it now', 'error')), None)
    assert page.detail_placeholder.get_visible() is False
    assert page.detail_content.get_visible() is True
    assert page.detail_title.get_label() == 'Broken tap'
    assert page.detail_severity.get_label() == 'Error'
    assert page.detail_body.get_label() == 'Repair it now'


def test_detail_shows_placeholder_without_issues():
    page = doctor_page.TavernDoctorPage()
    page._complete(_report(), None)
    assert page.detail_placeholder.get_visible() is True
    assert page.detail_content.get_visible() is False


def test_issue_title_is_not_parsed_as_markup():
    # Regression: an issue title containing markup must render literally.
    page = doctor_page.TavernDoctorPage()
    page._complete(_report(DoctorIssue('<markup>', 'body', 'warning')), None)
    row = page.findings_list.get_first_child()
    assert row.get_title() == '<markup>'
    assert row.get_use_markup() is False


def test_detail_renders_structured_blocks(monkeypatch):
    page = doctor_page.TavernDoctorPage()
    copied = []
    monkeypatch.setattr(page, 'get_clipboard', lambda: SimpleNamespace(set=copied.append))

    blocks = (
        DoctorBlock(type='prose', value=('Some explanation',), caption='Caption:'),
        DoctorBlock(type='command', value=(DoctorFixStep('brew cleanup', ('cleanup',), needs_admin=False),)),
        DoctorBlock(type='command', value=(DoctorFixStep('sudo chown -R me /opt', None, needs_admin=True),)),
        DoctorBlock(type='data', value=('/path/one', '/path/two')),
        DoctorBlock(type='link', value=(DoctorLink('https://example.com', 'action'),)),
    )
    issue = DoctorIssue('Issue with blocks', 'raw body', 'warning', blocks=blocks)
    page._complete(_report(issue), None)

    assert page.detail_content.get_visible() is True
    assert page.detail_body.get_visible() is False
    assert page.detail_body.get_label() == 'raw body'
    assert page.detail_blocks.get_first_child() is not None

    page._copy_text('test-copy')
    assert copied == ['test-copy']
