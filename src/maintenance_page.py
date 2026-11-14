"""On-demand security, user-service and disk-maintenance controls."""
# SPDX-License-Identifier: GPL-3.0-or-later

import gettext
import threading
from gi.repository import Adw, GLib, Gtk
from .brew_commands import parse_services, parse_vulns, transcript, version_install_args
from .command_dialog import show_command

_ = gettext.gettext


class MaintenancePage(Adw.NavigationPage):
    def __init__(self, manager, runner=None):
        super().__init__(title=_('Maintenance'))
        self._manager = manager
        self._runner = runner
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24,
                      margin_top=24, margin_bottom=32, margin_start=24, margin_end=24)
        scroll.set_child(Adw.Clamp(child=box, maximum_size=800))
        toolbar.set_content(scroll)
        self.set_child(toolbar)

        # Header Hero
        hero_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                           margin_top=8, margin_bottom=12, halign=Gtk.Align.CENTER)
        hero_icon = Gtk.Image.new_from_icon_name('applications-system-symbolic')
        hero_icon.set_pixel_size(48)
        hero_icon.add_css_class('dim-label')
        hero_box.append(hero_icon)

        hero_title = Gtk.Label(label=_('System Maintenance'))
        hero_title.add_css_class('title-1')
        hero_box.append(hero_title)

        hero_desc = Gtk.Label(label=_('Security audits, service management, and disk cleanup'))
        hero_desc.add_css_class('dim-label')
        hero_desc.set_wrap(True)
        hero_desc.set_justify(Gtk.Justification.CENTER)
        hero_box.append(hero_desc)
        box.append(hero_box)

        # ── 1. Security Audit ──────────────────────────────────────────
        security = Adw.PreferencesGroup(
            title=_('Security Audit'),
            description=_('Check installed formulae against known vulnerabilities via OSV.dev.')
        )

        self.scan_button = Gtk.Button(label=_('Scan'), icon_name='security-high-symbolic', valign=Gtk.Align.CENTER)
        self.scan_button.add_css_class('suggested-action')
        self.scan_button.add_css_class('pill')
        self.scan_button.connect('clicked', self._scan)

        self._security_output = ''
        self.view_output_button = Gtk.Button(label=_('View Log'), icon_name='text-x-generic-symbolic',
                                             valign=Gtk.Align.CENTER)
        self.view_output_button.add_css_class('flat')
        self.view_output_button.set_tooltip_text(_('View raw security scan output'))
        self.view_output_button.set_sensitive(False)
        self.view_output_button.connect('clicked', lambda _b: show_command(
            self.get_root(), _('Security Scan Output'),
            _('Warnings and skipped formulae are part of the report.'), text=self._security_output))

        sec_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sec_header.append(self.view_output_button)
        sec_header.append(self.scan_button)
        security.set_header_suffix(sec_header)

        self.security_status_row = Adw.ExpanderRow(
            title=_('Audit Status'),
            subtitle=_('Not scanned yet — click Scan to check installed formulae')
        )
        self.security_status_icon = Gtk.Image.new_from_icon_name('security-high-symbolic')
        self.security_status_icon.add_css_class('dim-label')
        self.security_status_row.add_prefix(self.security_status_icon)

        self.security_status = Gtk.Label(
            label=_('Not scanned'),
            xalign=0,
            wrap=True,
            selectable=True,
            margin_top=8,
            margin_bottom=8,
            margin_start=12,
            margin_end=12
        )
        self.security_status_row.add_row(self.security_status)
        security.add(self.security_status_row)

        self.security_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.security_list.add_css_class('boxed-list')
        security.add(self.security_list)
        box.append(security)

        # ── 2. Background Services ──────────────────────────────────────
        services = Adw.PreferencesGroup(
            title=_('Background Services'),
            description=_('Manage background services for your user account.')
        )
        self.services_button = Gtk.Button(label=_('Refresh'), icon_name='view-refresh-symbolic',
                                          valign=Gtk.Align.CENTER)
        self.services_button.add_css_class('pill')
        self.services_button.set_tooltip_text(_('Refresh Services'))
        self.services_button.connect('clicked', self._load_services)
        services.set_header_suffix(self.services_button)

        self.services_status = Gtk.Label(label=_('Not loaded'), xalign=0, wrap=True, selectable=True)

        self.services_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.services_list.add_css_class('boxed-list')
        self._empty_services_row = Adw.ActionRow(
            title=_('No services loaded'),
            subtitle=_('Click Refresh to discover user services')
        )
        empty_svc_icon = Gtk.Image.new_from_icon_name('system-run-symbolic')
        empty_svc_icon.add_css_class('dim-label')
        self._empty_services_row.add_prefix(empty_svc_icon)
        self.services_list.append(self._empty_services_row)
        services.add(self.services_list)
        box.append(services)

        # ── 3. Disk Maintenance ─────────────────────────────────────────
        cleanup = Adw.PreferencesGroup(
            title=_('Disk Maintenance'),
            description=_('Reclaim disk space by clearing caches and unused dependencies.')
        )
        for command, title, description, icon_name, btn_label in (
            ('cleanup', _('Clean Old Versions and Downloads'),
             _('Remove stale downloads and outdated package versions'),
             'user-trash-symbolic', _('Preview…')),
            ('autoremove', _('Remove Unused Dependencies'),
             _('Uninstall formulae no longer required by any package'),
             'package-x-generic-symbolic', _('Preview…')),
        ):
            row = Adw.ActionRow(title=title, subtitle=description, use_markup=False)
            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.add_css_class('dim-label')
            row.add_prefix(icon)

            button = Gtk.Button(label=btn_label, icon_name='system-search-symbolic', valign=Gtk.Align.CENTER)
            button.connect('clicked', lambda _b, cmd=command, label=title:
                           self._cleanup(cmd, label))
            row.add_suffix(button)
            row.set_activatable_widget(button)
            cleanup.add(row)
        box.append(cleanup)

        # ── 4. Historical Formula ───────────────────────────────────────
        versions = Adw.PreferencesGroup(
            title=_('Historical Formula Extraction'),
            description=_('Extract and install an older formula version from Git history.')
        )
        self.formula_entry = Adw.EntryRow(title=_('Formula Name'))
        icon_f = Gtk.Image.new_from_icon_name('package-x-generic-symbolic')
        icon_f.add_css_class('dim-label')
        self.formula_entry.add_prefix(icon_f)
        versions.add(self.formula_entry)

        self.version_entry = Adw.EntryRow(title=_('Target Version (e.g. 14.1.0)'))
        icon_v = Gtk.Image.new_from_icon_name('tag-symbolic')
        icon_v.add_css_class('dim-label')
        self.version_entry.add_prefix(icon_v)
        versions.add(self.version_entry)

        install_row = Adw.ActionRow(
            title=_('Extract and Install'),
            subtitle=_('Create a local tap extract and queue installation'),
        )
        icon_inst = Gtk.Image.new_from_icon_name('document-open-recent-symbolic')
        icon_inst.add_css_class('dim-label')
        install_row.add_prefix(icon_inst)

        self.version_button = Gtk.Button(
            label=_('Review Install…'),
            icon_name='system-software-install-symbolic',
            valign=Gtk.Align.CENTER
        )
        self.version_button.add_css_class('suggested-action')
        self.version_button.connect('clicked', self._version_install)
        install_row.add_suffix(self.version_button)
        install_row.set_activatable_widget(self.version_button)
        versions.add(install_row)
        box.append(versions)

    def _version_install(self, _button):
        try:
            args = version_install_args(self.formula_entry.get_text().strip(),
                                        self.version_entry.get_text().strip())
        except ValueError as error:
            show_command(self.get_root(), _('Check Formula and Version'), str(error), text=str(error))
            return
        show_command(self.get_root(), _('Install a Historical Formula?'),
                     _('Homebrew may create a personal versions tap and extract a formula from Git history. '
                       'You must maintain extracted formulae yourself; they receive no automatic security fixes. '
                       'The build may be slow or fail. This does not pin your current installation, '
                       'and it does not support casks. There is no dry-run for this command.'),
                     text='brew ' + ' '.join(args),
                     confirm=lambda: self._manager.submit_command(args, _('Install Historical Formula')),
                     confirm_label=_('Install Historical Formula'))

    def _request(self, button, status, args, parser, complete):
        if not button.get_sensitive():
            return
        button.set_sensitive(False)
        status.set_label(_('Loading…'))
        if status == self.security_status:
            self.security_status_row.set_subtitle(_('Scanning installed formulae…'))
            self.security_status_icon.set_from_icon_name('view-refresh-symbolic')
            self.security_status_icon.remove_css_class('dim-label')
            self.security_status_icon.remove_css_class('success')
            self.security_status_icon.remove_css_class('warning')
            self.security_status_icon.remove_css_class('error')
        elif status == self.services_status and hasattr(self, '_empty_services_row'):
            self._empty_services_row.set_title(_('Loading services…'))
            self._empty_services_row.set_subtitle(_('Querying Homebrew background services…'))

        def done(result, data, error):
            button.set_sensitive(True)
            if error is not None:
                status.set_label(_('Check failed; previous results may be stale.\n{error}').format(error=error))
                if status == self.security_status:
                    self.security_status_row.set_subtitle(_('Check failed'))
                    self.security_status_icon.set_from_icon_name('dialog-error-symbolic')
                    self.security_status_icon.add_css_class('error')
                    self.security_status_row.set_expanded(True)
                elif status == self.services_status:
                    self._clear(self.services_list)
                    err_row = Adw.ActionRow(
                        title=_('Failed to load services'),
                        subtitle=str(error),
                    )
                    err_icon = Gtk.Image.new_from_icon_name('dialog-error-symbolic')
                    err_icon.add_css_class('error')
                    err_row.add_prefix(err_icon)
                    self.services_list.append(err_row)
            else:
                complete(result, data)
            return False

        def worker():
            try:
                result = self._runner(args)
                data = parser(result)
            except Exception as error:
                GLib.idle_add(done, None, None, str(error))
            else:
                GLib.idle_add(done, result, data, None)

        threading.Thread(target=worker, daemon=True, name='tavern-maintenance').start()

    @staticmethod
    def _clear(listbox):
        while child := listbox.get_first_child():
            listbox.remove(child)

    def _scan(self, _button):
        self._request(self.scan_button, self.security_status, ('vulns', '--json'),
                      parse_vulns, self._show_scan)

    def _show_scan(self, result, data):
        self._security_output = transcript(result)
        self.view_output_button.set_sensitive(True)
        self._clear(self.security_list)
        count = sum(len(f['vulnerabilities']) for f in data['findings'])
        summary = _('Open vulnerabilities reported: {count}').format(count=count)
        skipped = data['skipped_formulae']
        if skipped:
            summary += '\n' + _('Skipped formulae: {names}').format(names=', '.join(skipped))
        if result.stderr or (result.returncode and not count):
            summary += '\n' + _('Coverage may be incomplete. Review the command warnings.')
            summary += '\n' + (result.stderr or '')
        self.security_status.set_label(summary)

        if count == 0 and not skipped and not result.stderr and not (result.returncode and not count):
            self.security_status_icon.set_from_icon_name('object-select-symbolic')
            self.security_status_icon.remove_css_class('dim-label')
            self.security_status_icon.remove_css_class('warning')
            self.security_status_icon.remove_css_class('error')
            self.security_status_icon.add_css_class('success')
            self.security_status_row.set_subtitle(_('No open vulnerabilities reported'))
            self.security_status_row.set_expanded(False)
        else:
            self.security_status_icon.set_from_icon_name('dialog-warning-symbolic')
            self.security_status_icon.remove_css_class('dim-label')
            self.security_status_icon.remove_css_class('success')
            self.security_status_icon.remove_css_class('error')
            self.security_status_icon.add_css_class('warning')
            if count > 0:
                self.security_status_row.set_subtitle(
                    gettext.ngettext(
                        '{count} vulnerability reported',
                        '{count} vulnerabilities reported',
                        count
                    ).format(count=count)
                )
            else:
                self.security_status_row.set_subtitle(_('Scan completed with warnings'))
            self.security_status_row.set_expanded(True)

        for finding in data['findings']:
            for key, state in (('vulnerabilities', _('Open')), ('patched', _('Resolved by formula patch'))):
                for vuln in finding[key]:
                    is_open = (key == 'vulnerabilities')
                    severity = vuln.get('severity') or _('Unknown severity')
                    row = Adw.ExpanderRow(
                        title=f"{finding['formula']} {finding['version']} — {vuln['id']}",
                        subtitle=f"{state} · {severity}",
                        use_markup=False
                    )
                    icon = Gtk.Image.new_from_icon_name(
                        'dialog-warning-symbolic' if is_open else 'object-select-symbolic'
                    )
                    icon.add_css_class('warning' if is_open else 'success')
                    row.add_prefix(icon)

                    pill = Gtk.Label(label=state)
                    pill.add_css_class('pill')
                    pill.add_css_class('warning' if is_open else 'success')
                    pill.set_valign(Gtk.Align.CENTER)
                    row.add_suffix(pill)

                    detail_box = Gtk.Box(
                        orientation=Gtk.Orientation.VERTICAL,
                        spacing=8,
                        margin_top=12,
                        margin_bottom=12,
                        margin_start=16,
                        margin_end=16
                    )

                    if vuln.get('summary'):
                        summary_lbl = Gtk.Label(
                            label=vuln['summary'],
                            xalign=0,
                            wrap=True,
                            selectable=True
                        )
                        detail_box.append(summary_lbl)

                    fixed = ', '.join(vuln.get('fixed_versions') or []) or _('No released fix reported')
                    fixed_row = Adw.ActionRow(
                        title=_('Fixed in'),
                        subtitle=fixed,
                        use_markup=False
                    )
                    icon_fixed = Gtk.Image.new_from_icon_name('package-x-generic-symbolic')
                    icon_fixed.add_css_class('dim-label')
                    fixed_row.add_prefix(icon_fixed)
                    detail_box.append(fixed_row)

                    row.add_row(detail_box)
                    self.security_list.append(row)

    def _load_services(self, _button):
        self._request(self.services_button, self.services_status, ('services', 'list', '--json'),
                      parse_services, self._show_services)

    def _show_services(self, result, services):
        self._clear(self.services_list)
        self.services_status.set_label(result.stderr or (_('No user services found') if not services else ''))
        if not services:
            empty_row = Adw.ActionRow(
                title=_('No user services found'),
                subtitle=result.stderr or _('No background services are currently installed'),
            )
            empty_icon = Gtk.Image.new_from_icon_name('system-run-symbolic')
            empty_icon.add_css_class('dim-label')
            empty_row.add_prefix(empty_icon)
            self.services_list.append(empty_row)
            return

        for service in services:
            status = service.get('status', 'stopped')
            is_running = (status == 'started')
            is_error = status in ('error', 'failed')

            row = Adw.ExpanderRow(title=service['name'], subtitle=status, use_markup=False)

            if is_running:
                icon_name = 'media-playback-start-symbolic'
                icon_css = 'success'
            elif is_error:
                icon_name = 'dialog-error-symbolic'
                icon_css = 'error'
            else:
                icon_name = 'media-playback-stop-symbolic'
                icon_css = 'dim-label'

            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.add_css_class(icon_css)
            row.add_prefix(icon)

            pill = Gtk.Label(label=status)
            pill.add_css_class('pill')
            if is_running:
                pill.add_css_class('success')
            elif is_error:
                pill.add_css_class('error')
            pill.set_valign(Gtk.Align.CENTER)
            row.add_suffix(pill)

            buttons = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=8,
                margin_top=10,
                margin_bottom=10,
                margin_start=16,
                margin_end=16,
                halign=Gtk.Align.CENTER
            )

            start_btn = Gtk.Button(label=_('Start'), icon_name='media-playback-start-symbolic')
            if not is_running:
                start_btn.add_css_class('suggested-action')
            start_btn.connect('clicked', lambda _b, name=service['name']:
                              self._service_action(name, 'start', _('Start')))
            buttons.append(start_btn)

            stop_btn = Gtk.Button(label=_('Stop'), icon_name='media-playback-stop-symbolic')
            if is_running:
                stop_btn.add_css_class('destructive-action')
            stop_btn.connect('clicked', lambda _b, name=service['name']:
                             self._service_action(name, 'stop', _('Stop')))
            buttons.append(stop_btn)

            restart_btn = Gtk.Button(label=_('Restart'), icon_name='view-refresh-symbolic')
            restart_btn.connect('clicked', lambda _b, name=service['name']:
                                self._service_action(name, 'restart', _('Restart')))
            buttons.append(restart_btn)

            row.add_row(buttons)
            self.services_list.append(row)

    def _service_action(self, name, action, label):
        title = f'{label}: {name}'

        def execute():
            task = self._manager.submit_command(('services', action, name), title)
            task.connect('finished', lambda *_: self._load_services(None))

        show_command(self.get_root(), title,
                     _('This changes the service for your user account. Start registers it at login; '
                       'stop unregisters it. Restart may interrupt clients using the service.'),
                     text=f'brew services {action} {name}', confirm=execute,
                     confirm_label=label, destructive=action != 'start')

    def _cleanup(self, command, title):
        show_command(self.get_root(), title,
                     _('Review the removal list. Homebrew recalculates it when the queued task runs.'),
                     args=(command, '--dry-run'),
                     confirm=lambda: self._manager.submit_command((command,), title),
                     confirm_label=_('Remove'), destructive=True, runner=self._runner)
