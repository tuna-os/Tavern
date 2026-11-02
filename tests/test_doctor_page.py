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
    monkeypatch.setattr('tavern.brew_env.is_brew_available', lambda: True)
    result = SimpleNamespace(stdout='{"findings": [], "tier": 1}', stderr='Extra warning', returncode=0)
    monkeypatch.setattr(doctor_page, 'run_read', lambda *args, **kwargs: calls.append((args, kwargs)) or result)
    assert doctor_page._run_doctor() is result
    assert calls == [((('doctor', '--json'),), {'timeout': 60})]


def test_runner_falls_back_only_for_unsupported_json(monkeypatch):
    calls = []
    monkeypatch.setattr('tavern.brew_env.is_brew_available', lambda: True)
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


def _walk(widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from _walk(child)
        child = child.get_next_sibling()


def _fix_buttons(page):
    from gi.repository import Gtk
    return [widget for widget in _walk(page.detail_blocks)
            if isinstance(widget, Gtk.Button) and widget.get_label() == 'Fix']


def _fix_page():
    from tavern.task_manager import Task
    tasks = []

    def submit(args, title):
        task = Task(None, args[0], packages=[], command=args, title=title)
        tasks.append(task)
        return task

    page = doctor_page.TavernDoctorPage(task_manager=SimpleNamespace(submit_command=submit))
    report = parse_report('Warning: Cleanup\n  brew cleanup\n\nWarning: Links\n  brew link foo\n', 1)
    page._complete(report, None)
    return page, tasks, report


def test_fix_queues_argv_once_and_tracks_progress_across_selection():
    page, tasks, report = _fix_page()
    button, = _fix_buttons(page)
    button.emit('clicked')
    # Even a stale/programmatic duplicate click must be suppressed.
    button.emit('clicked')
    assert len(tasks) == 1
    task = tasks[0]
    assert task.command == ('cleanup',)
    assert task.title == task.operation == 'brew cleanup'
    assert not button.get_sensitive()
    task._set_running()
    task._update_phase('Removing…', 0.5)
    page.findings_list.select_row(_by_title(page, 'Links'))
    assert _fix_buttons(page)[0].get_sensitive()
    page.findings_list.select_row(_by_title(page, 'Cleanup'))
    button, = _fix_buttons(page)
    assert not button.get_sensitive()
    _, spinner, status, progress = page._fix_widgets['brew cleanup'][0]
    assert spinner.get_spinning()
    assert status.get_label() == 'Removing…'
    assert progress.get_fraction() == 0.5
    # A reload reconstructs controls but preserves the same command state.
    page._complete(report, None)
    assert not _fix_buttons(page)[0].get_sensitive()


def test_failed_fix_stays_inline_and_can_be_retried(monkeypatch):
    page, tasks, _ = _fix_page()
    refreshes = []
    monkeypatch.setattr(page, 'refresh', lambda **kwargs: refreshes.append(kwargs))
    _fix_buttons(page)[0].emit('clicked')
    tasks[0]._set_failed('<literal error>')
    button, spinner, status, progress = page._fix_widgets['brew cleanup'][0]
    assert button.get_sensitive()
    assert status.get_label() == '<literal error>'
    assert status.has_css_class('error')
    assert not spinner.get_visible()
    assert not progress.get_visible()
    assert not refreshes
    button.emit('clicked')
    assert len(tasks) == 2
    assert page._fix_tasks['brew cleanup'] is tasks[1]
    assert not status.has_css_class('error')
    tasks[1]._set_completed()
    assert refreshes == [{'force': True}]


def test_cancelled_fix_can_retry_without_refresh(monkeypatch):
    page, tasks, _ = _fix_page()
    refreshes = []
    monkeypatch.setattr(page, 'refresh', lambda **kwargs: refreshes.append(kwargs))
    _fix_buttons(page)[0].emit('clicked')
    tasks[0]._set_cancelled()
    assert _fix_buttons(page)[0].get_sensitive()
    assert not refreshes


def test_non_runnable_blocks_are_copy_only(monkeypatch):
    page, tasks, _ = _fix_page()
    copied = []
    monkeypatch.setattr(page, '_copy_text', copied.append)
    for body in ('  sudo brew cleanup', '  brew cleanup\n  brew autoremove',
                 '  brew cleanup && brew autoremove', '  rm /tmp/example'):
        report = parse_report('Warning: Manual fix\n' + body, 1)
        page._complete(report, None)
        assert not _fix_buttons(page)
        block = report.issues[0].blocks[0]
        page._submit_fix(block)
        assert not tasks
        from gi.repository import Gtk
        notes = [w.get_label() for w in _walk(page.detail_blocks) if isinstance(w, Gtk.Label)]
        assert any('Terminal' in note for note in notes)
        copies = [w for w in _walk(page.detail_blocks)
                  if isinstance(w, Gtk.Button) and w.get_tooltip_text() == 'Copy Command']
        copies[0].emit('clicked')
        assert copied[-1] == block.value[0].display_command


def test_success_during_check_forces_another_report(monkeypatch):
    page, tasks, report = _fix_page()
    workers = []
    monkeypatch.setattr(doctor_page.threading, 'Thread',
                        lambda **kwargs: SimpleNamespace(start=lambda: workers.append(kwargs['target'])))
    _fix_buttons(page)[0].emit('clicked')
    page.refresh()
    tasks[0]._set_completed()
    assert page._refresh_pending
    assert len(workers) == 1
    page._complete(report, None)
    assert len(workers) == 2
    assert page._busy
    assert not page._refresh_pending


def test_identical_commands_share_inflight_state():
    page, tasks, _ = _fix_page()
    report = parse_report('Warning: First\n  brew cleanup\n\nWarning: Second\n  brew cleanup', 1)
    page._complete(report, None)
    _fix_buttons(page)[0].emit('clicked')
    page.findings_list.select_row(_by_title(page, 'Second'))
    _fix_buttons(page)[0].emit('clicked')
    assert len(tasks) == 1
    assert not _fix_buttons(page)[0].get_sensitive()


def test_fix_requires_shared_task_manager():
    page = doctor_page.TavernDoctorPage()
    report = parse_report('Warning: Cleanup\n  brew cleanup', 1)
    page._complete(report, None)
    button, = _fix_buttons(page)
    assert not button.get_sensitive()
    block = report.issues[0].blocks[0]
    page._submit_fix(block)
    assert not page._fix_tasks
    page.set_task_manager(SimpleNamespace())
    assert button.get_sensitive()
