"""Doctor parsing and cache contracts do not need GTK or a real brew."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from loader import load_module

doctor = load_module('src/doctor.py', 'doctor')


def test_healthy_report():
    report = doctor.parse_report('Your system is ready to brew.\n', 0)
    assert report.issues == ()
    assert report.raw_output == 'Your system is ready to brew.\n'


def test_warnings_exit_one_keep_blocks_and_strip_ansi():
    raw = '\x1b[33mWarning:\x1b[0m Unlinked kegs\nRun this command:\n  brew link hello\n\nWarning: Old setup\nThis is a Tier 3 configuration.\n'
    report = doctor.parse_report(raw, 1)
    assert [issue.severity for issue in report.issues] == ['unsupported', 'warning']
    assert report.issues[1].body == 'Run this command:\n  brew link hello'
    assert '\x1b' not in report.raw_output
    assert report.issues[1].content_id == doctor.parse_report(raw, 1).issues[1].content_id


def test_errors_precede_warnings():
    report = doctor.parse_report('Warning: Small problem\nDetails\nError: Major problem\nMore details', 1)
    assert [issue.title for issue in report.issues] == ['Major problem', 'Small problem']


@pytest.mark.parametrize('output,code', [('', 1), ('brew not found', 127), ('Warning: partial', 2)])
def test_command_failure_is_not_healthy(output, code):
    with pytest.raises(doctor.DoctorError):
        doctor.parse_report(output, code)


def test_cache_force_and_expiry():
    calls = []
    now = [0]

    def run():
        calls.append(True)
        return SimpleNamespace(stdout='Your system is ready to brew.', returncode=0)

    service = doctor.DoctorService(run, clock=lambda: now[0])
    first = service.load()
    assert service.load() is first
    service.load(force=True)
    assert len(calls) == 2
    now[0] = doctor.REPORT_TTL
    service.load()
    assert len(calls) == 3


def test_failed_refresh_does_not_replace_report_or_timestamp():
    calls = []
    now = [0]

    def run():
        calls.append(True)
        if len(calls) == 2:
            raise TimeoutError('Timed out')
        return SimpleNamespace(stdout='Warning: Fix your setup', returncode=1)

    service = doctor.DoctorService(run, clock=lambda: now[0])
    first = service.load()
    now[0] = doctor.REPORT_TTL
    with pytest.raises(TimeoutError):
        service.load()
    assert service._report is first
    assert service._reported_at == 0
    service.load()
    assert len(calls) == 3


def test_concurrent_loads_share_one_report():
    calls = []

    def run():
        calls.append(True)
        return SimpleNamespace(stdout='All good', returncode=0)

    service = doctor.DoctorService(run)
    with ThreadPoolExecutor(max_workers=4) as pool:
        reports = list(pool.map(lambda _index: service.load(), range(8)))
    assert all(report is reports[0] for report in reports)
    assert len(calls) == 1
