"""The Doctor page renders reports and retries without real Homebrew calls."""
from types import SimpleNamespace

from tavern import doctor_page
from tavern.doctor import parse_report


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
