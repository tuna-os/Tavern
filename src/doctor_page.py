"""GTK presentation for read-only Homebrew diagnostics."""
# SPDX-License-Identifier: GPL-3.0-or-later

import gettext
import threading

from gi.repository import Adw, GLib, Gtk

from .doctor import DoctorService, severity_groups, select_after_reload
from .brew_commands import run_read, transcript

_ = gettext.gettext


def _run_doctor():
    from .brew_env import is_brew_available
    if not is_brew_available():
        from .doctor import DoctorError
        raise DoctorError(_('Homebrew is not installed.'))
    result = run_read(('doctor', '--json'), timeout=60)
    if result.returncode and any(message in transcript(result).lower() for message in
                                ('invalid option: --json', 'unknown option: --json')):
        # Pre-7 Homebrew: warnings are printed to stderr in the text format.
        result = run_read(('doctor',), timeout=60)
        result.stdout = transcript(result)
        result.stderr = ''
    else:
        result.doctor_json = True
    return result


@Gtk.Template(resource_path='/org.tunaos.tavern/doctor-page.ui')
class TavernDoctorPage(Adw.Bin):
    __gtype_name__ = 'TavernDoctorPage'

    run_button = Gtk.Template.Child()
    copy_button = Gtk.Template.Child()
    spinner = Gtk.Template.Child()
    status_label = Gtk.Template.Child()
    error_label = Gtk.Template.Child()
    findings_list = Gtk.Template.Child()
    detail_placeholder = Gtk.Template.Child()
    detail_content = Gtk.Template.Child()
    detail_title = Gtk.Template.Child()
    detail_severity = Gtk.Template.Child()
    detail_body = Gtk.Template.Child()
    raw_expander = Gtk.Template.Child()
    raw_view = Gtk.Template.Child()
    config_button = Gtk.Template.Child()

    def __init__(self, service=None, **kwargs):
        super().__init__(**kwargs)
        self._service = service if service is not None else DoctorService(_run_doctor)
        self._report = None
        self._busy = False
        self._rows = {}
        self.run_button.connect('clicked', lambda _button: self.refresh(force=True))
        self.copy_button.connect('clicked', self._copy_output)
        self.config_button.connect('clicked', self._show_config)
        self.connect('map', lambda _page: self.refresh())
        self.findings_list.connect('row-selected', self._on_row_selected)
        self._render_detail(None)

    def refresh(self, force=False):
        if self._busy:
            return
        self._busy = True
        self.run_button.set_sensitive(False)
        self.spinner.start()
        self.error_label.set_visible(False)
        self.status_label.set_label(_('Re-checking…') if self._report else _('Running brew doctor…'))

        def worker():
            try:
                report = self._service.load(force=force)
            except Exception as error:
                GLib.idle_add(self._complete, None, str(error))
            else:
                GLib.idle_add(self._complete, report, None)

        threading.Thread(target=worker, daemon=True, name='tavern-doctor').start()

    def _complete(self, report, error):
        self._busy = False
        self.spinner.stop()
        self.run_button.set_sensitive(True)
        self.run_button.set_label(_('Run Again'))
        if error is not None:
            self.status_label.set_label(
                _('Check failed — previous report shown') if self._report else _('The check could not be completed')
            )
            self.error_label.set_label(error)
            self.error_label.set_visible(True)
            return False

        self._report = report
        self.error_label.set_visible(bool(report.warnings))
        self.error_label.set_label(report.warnings)
        self.status_label.set_label(_('Warnings found') if report.issues else _('No problems found'))
        if report.tier is not None:
            self.status_label.set_label(self.status_label.get_label() + ' — ' +
                                        _('Support tier: {tier}').format(tier=report.tier))
        self.raw_view.get_buffer().set_text(report.raw_output)
        self.raw_expander.set_visible(True)
        self.copy_button.set_sensitive(bool(report.raw_output))
        self._build_list(report)
        return False

    def _build_list(self, report):
        """Rebuild the grouped list and revalidate the selection.

        The list is grouped by severity in display order. The previous selection is
        captured from the live list before it is rebuilt, then kept when its issue is
        still present (it may have moved), dropped when it resolved, and defaults to
        the first issue otherwise. The list grabs focus so up/down navigates findings.
        """
        previous = self._rows.get(self.findings_list.get_selected_row())
        previous_content_id = previous.content_id if previous is not None else None

        while child := self.findings_list.get_first_child():
            self.findings_list.remove(child)
        self._rows.clear()

        severities = {'warning': _('Warning'), 'error': _('Error'),
                      'unsupported': _('Unsupported configuration')}
        for _key, group in severity_groups(report.issues):
            for issue in group:
                # The body renders in the detail pane; the list row only names the issue.
                row = Adw.ActionRow(title=issue.title, subtitle=severities[issue.severity],
                                    use_markup=False)
                self.findings_list.append(row)
                self._rows[row] = issue
        self.findings_list.set_visible(bool(report.issues))

        desired = select_after_reload(previous_content_id, report.issues)
        selected_row = None
        if desired is not None:
            for row, issue in self._rows.items():
                if issue.content_id == desired.content_id:
                    selected_row = row
                    break
        self.findings_list.unselect_all()
        if selected_row is not None:
            self.findings_list.select_row(selected_row)
        if report.issues:
            self.findings_list.grab_focus()
        else:
            self._render_detail(None)

    def _on_row_selected(self, _list_box, row):
        self._render_detail(self._rows.get(row) if row is not None else None)

    def _render_detail(self, issue):
        if issue is None:
            self.detail_placeholder.set_visible(True)
            self.detail_content.set_visible(False)
            return
        self.detail_placeholder.set_visible(False)
        self.detail_content.set_visible(True)
        self.detail_title.set_label(issue.title)
        self.detail_severity.set_label(
            {'warning': _('Warning'), 'error': _('Error'),
             'unsupported': _('Unsupported configuration')}[issue.severity])
        self.detail_body.set_label(issue.body)

    def _copy_output(self, _button):
        if self._report is not None:
            self.get_clipboard().set(self._report.raw_output)

    def _show_config(self, _button):
        from .command_dialog import show_command
        show_command(self.get_root(), _('Homebrew Configuration'),
                     _('Includes platform and sandbox diagnostics, including Landlock when available. '
                       'Review local paths and account details before sharing.'), args=('config',))
