# package_details.py - Package info + install/remove dialog
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, Gdk, Gio, GLib, GObject, Pango

# Optional README renderer for Linux builds with WebKitGTK available.
try:
    gi.require_version('WebKit', '6.0')
    from gi.repository import WebKit
except Exception:
    WebKit = None

from .backend import Package, BrewBackend
from .task_manager import Task, TaskStatus, TaskOperation
from .logging_util import get_logger
from .screenshot_lightbox import TavernScreenshotLightbox


_log = get_logger('package_details')


@Gtk.Template(resource_path='/dev/hanthor/Tavern/package-details.ui')
class TavernPackageDetails(Adw.NavigationPage):
    __gtype_name__ = 'TavernPackageDetails'

    __gsignals__ = {
        'package-changed': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'package-history-requested': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'package-activated': (GObject.SignalFlags.RUN_LAST, None, (object,)),
    }

    details_stack = Gtk.Template.Child()
    detail_icon = Gtk.Template.Child()
    detail_name = Gtk.Template.Child()
    detail_display_name = Gtk.Template.Child()
    detail_type_badge = Gtk.Template.Child()
    detail_desc = Gtk.Template.Child()
    install_button = Gtk.Template.Child()
    remove_button = Gtk.Template.Child()
    update_button = Gtk.Template.Child()
    version_row = Gtk.Template.Child()
    version_label = Gtk.Template.Child()
    license_row = Gtk.Template.Child()
    license_label = Gtk.Template.Child()
    info_listbox = Gtk.Template.Child()
    homepage_row = Gtk.Template.Child()
    homepage_label = Gtk.Template.Child()
    installs_row = Gtk.Template.Child()
    installs_stack = Gtk.Template.Child()
    installs_label = Gtk.Template.Child()
    error_label = Gtk.Template.Child()
    detail_progress_bar = Gtk.Template.Child()
    screenshot_bin = Gtk.Template.Child()
    screenshot_button = Gtk.Template.Child()
    screenshot_picture = Gtk.Template.Child()
    readme_bin = Gtk.Template.Child()
    readme_overlay = Gtk.Template.Child()
    readme_preview_box = Gtk.Template.Child()
    readme_preview_label = Gtk.Template.Child()
    readme_fade_overlay = Gtk.Template.Child()
    show_readme_button = Gtk.Template.Child()
    variants_bin = Gtk.Template.Child()
    variants_flow = Gtk.Template.Child()
    related_bin = Gtk.Template.Child()
    related_flow = Gtk.Template.Child()

    def __init__(self, package=None, backend=None, task_manager=None, **kwargs):
        super().__init__(**kwargs)
        self._package = package
        self._backend = backend
        self._task_manager = task_manager
        self._task = None
        self._hover_link = None
        self._readme_text = None
        self._readme_webview = None

        self.install_button.connect('clicked', self._on_install_clicked)
        self.remove_button.connect('clicked', self._on_remove_clicked)
        self.update_button.connect('clicked', self._on_update_clicked)
        # pin_button is added in newer templates only; gracefully fall back to None
        # if the bundled .ui hasn't been rebuilt yet.
        self.pin_button = self.get_template_child(TavernPackageDetails, 'pin_button')
        self._pin_handler_id = None
        if self.pin_button is not None:
            self._pin_handler_id = self.pin_button.connect('toggled', self._on_pin_toggled)
        if self._backend:
            self._backend.connect('pinned-changed', lambda b, _s: self._update_buttons())
        self.info_listbox.connect('row-activated', self._on_info_row_activated)
        self.screenshot_button.connect('clicked', self._on_screenshot_clicked)

        # Set cursor for screenshot button
        self.screenshot_button.set_cursor(Gdk.Cursor.new_from_name('pointer', None))

        if package:
            _log.debug('Opening details for %s (%s)', package.name, package.pkg_type)
            self._populate(package)

    def _populate(self, package):
        from .logging_util import get_logger
        _log = get_logger('package_details')
        
        self.set_title(package.display_name or package.name)
        self.set_tag(f"details_{package.name}_{id(self)}")
        self.readme_bin.set_visible(False)
        self.readme_overlay.set_visible(True)
        self.readme_preview_label.set_label('')
        self.readme_preview_box.set_visible(True)
        self.readme_fade_overlay.set_visible(True)
        self._readme_text = None
        
        self.detail_name.set_label(package.name)
        self.detail_desc.set_label(package.description or 'No description available.')
        _log.debug('Setting description: %s', package.description[:50] if package.description else 'None')

        if package.display_name and package.display_name != package.name:
            self.detail_display_name.set_label(package.display_name)
            self.detail_display_name.set_visible(True)

        self.detail_type_badge.set_label(package.pkg_type)
        if package.pkg_type == 'cask':
            self.detail_type_badge.add_css_class('cask-badge')

        _log.debug('Setting version_label: %s', package.version or 'Unknown')
        self.version_label.set_label(package.version or 'Unknown')

        if package.license_:
            _log.debug('Setting license: %s', package.license_)
            self.license_label.set_label(package.license_)
            self.license_row.set_visible(True)
        else:
            _log.debug('No license for %s', package.name)

        if package.homepage:
            _log.debug('Setting homepage: %s', package.homepage)
            self.homepage_label.set_label(package.homepage)
        else:
            self.homepage_row.set_sensitive(False)
            self.homepage_label.set_label('Not available')
            _log.debug('No homepage for %s', package.name)

        # Show the installs row initially with the spinner active
        if package.pkg_type == 'cask' or package.pkg_type == 'formula':
            self.installs_row.set_visible(True)
            self.installs_stack.set_visible_child_name('spinner')
            self.installs_row.set_sensitive(False)  # Not clickable until loaded
        else:
            self.installs_row.set_visible(False)

        self._update_buttons()
        self.details_stack.set_visible_child_name('content')

        # Re-attach to any already-running task for this package
        if self._task_manager:
            existing = self._task_manager.get_task_for_package(package)
            if existing:
                self._bind_task(existing)

        # Fetch icon, screenshot, and README
        if self._backend:
            self._backend.fetch_icon_async(package, self._on_icon_fetched)
            self._backend.fetch_screenshot_async(package, self._on_screenshot_fetched)
            self._backend.fetch_readme_async(package, self._on_readme_fetched)
            self._backend.get_package_info_async(package, self._on_info_loaded)
            GLib.idle_add(self._load_related_packages)

    def _load_related_packages(self):
        if not self._backend or not self._package:
            return

        # Prefer explicit dependency / same-tap relationships from the backend.
        # Fall back to substring search only if both lookups come back empty.
        variants = []
        related = []
        if hasattr(self._backend, 'get_variants') and hasattr(self._backend, 'get_related_packages'):
            variants = self._backend.get_variants(self._package, limit=6)
            related = self._backend.get_related_packages(self._package, limit=6)

        if not variants and not related:
            search_term = self._package.name.split('@')[0]
            for p in self._backend.search(search_term):
                if p.name == self._package.name or p.full_name == self._package.full_name:
                    continue
                if p.name.split('@')[0] == search_term:
                    variants.append(p)
                else:
                    related.append(p)
        
        # Process Variants
        if variants:
            variants = variants[:3]
            while child := self.variants_flow.get_first_child():
                self.variants_flow.remove(child)
                
            from .package_tile import TavernPackageTile
            for pkg in variants:
                tile = TavernPackageTile(package=pkg)
                tile.connect('activated', self._on_related_clicked)
                tile.connect('install-requested', self._on_related_install_requested)
                self._load_tile_icon(tile, pkg)
                self.variants_flow.append(tile)
            self.variants_bin.set_visible(True)
        else:
            self.variants_bin.set_visible(False)

        # Process Related
        if related:
            related = related[:3]
            while child := self.related_flow.get_first_child():
                self.related_flow.remove(child)
                
            from .package_tile import TavernPackageTile
            for pkg in related:
                tile = TavernPackageTile(package=pkg)
                tile.connect('activated', self._on_related_clicked)
                tile.connect('install-requested', self._on_related_install_requested)
                self._load_tile_icon(tile, pkg)
                self.related_flow.append(tile)
            self.related_bin.set_visible(True)
        else:
            self.related_bin.set_visible(False)

    def _load_tile_icon(self, tile, package):
        if not self._backend:
            return
        def on_icon_fetched(pkg, pixbuf):
            if pixbuf:
                tile.set_icon_pixbuf(pixbuf)
        self._backend.fetch_icon_async(package, on_icon_fetched)

    def _on_related_clicked(self, tile):
        pkg = tile.get_package()
        if pkg:
            self.emit('package-activated', pkg)

    def _on_related_install_requested(self, tile):
        pkg = tile.get_package()
        if pkg and self._task_manager:
            self._task_manager.install(pkg)

    def _update_buttons(self):
        pkg = self._package
        busy = self._task is not None and self._task.is_active
        
        is_outdated = False
        if self._backend and hasattr(self._backend, '_outdated_formulae'):
            if pkg.name in getattr(self._backend, '_outdated_formulae', {}) or pkg.name in getattr(self._backend, '_outdated_casks', {}):
                is_outdated = True

        if pkg.installed:
            self.install_button.set_visible(False)
            self.remove_button.set_visible(True)
            self.remove_button.set_sensitive(not busy)
            self.update_button.set_visible(is_outdated)
            self.update_button.set_sensitive(not busy)
        else:
            self.install_button.set_visible(True)
            self.remove_button.set_visible(False)
            self.update_button.set_visible(False)
            self.install_button.set_sensitive(not busy)

        # Pin button: only meaningful for installed formulae.
        if self.pin_button is not None:
            show_pin = pkg.installed and pkg.pkg_type == 'formula'
            self.pin_button.set_visible(show_pin)
            if show_pin and self._backend is not None:
                is_pinned = self._backend.is_pinned(pkg.name)
                # Avoid re-firing `toggled` while we sync from backend state.
                self.pin_button.handler_block(self._pin_handler_id)
                self.pin_button.set_active(is_pinned)
                self.pin_button.handler_unblock(self._pin_handler_id)
                self.pin_button.set_tooltip_text(
                    'Unpin (allow upgrades)' if is_pinned else 'Pin this version (prevent upgrades)'
                )
                self.pin_button.set_sensitive(not busy)

    def _on_pin_toggled(self, button):
        if not self._backend or not self._package:
            return
        pkg = self._package
        if pkg.pkg_type != 'formula':
            return
        currently_pinned = self._backend.is_pinned(pkg.name)
        if button.get_active() and not currently_pinned:
            self._backend.pin_async(pkg)
        elif not button.get_active() and currently_pinned:
            self._backend.unpin_async(pkg)

    def _on_info_loaded(self, package, data):
        if package != self._package:
            return
            
        if data:
            # Re-parse API data into the existing Package object so analytics are updated
            package._from_api(data, package.pkg_type)
        
        # Now update the UI with the fresh installs data (or hide if failed to load)
        if package.installs_90d > 0:
            count = package.installs_90d
            if count >= 1_000_000:
                formatted = f"{count / 1_000_000:.2f}M"
            elif count >= 1000:
                formatted = f"{count / 1000:.2f}K"
            else:
                formatted = f"{count:,}"
            self.installs_label.set_label(formatted)
            self.installs_stack.set_visible_child_name('label')
            self.installs_row.set_sensitive(True)
        else:
            self.installs_row.set_visible(False)
            self.installs_row.set_sensitive(False)

    def _on_icon_fetched(self, package, pixbuf):
        if pixbuf and package == self._package:
            try:
                from gi.repository import Gdk
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                self.detail_icon.set_from_paintable(texture)
            except Exception:
                pass

    def _on_screenshot_fetched(self, package, pixbuf):
        if pixbuf and package == self._package:
            try:
                from gi.repository import Gdk
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                self.screenshot_picture.set_paintable(texture)
                self.screenshot_bin.set_visible(True)
                self._current_screenshot = texture
            except Exception:
                pass

    def _on_screenshot_clicked(self, button):
        if hasattr(self, '_current_screenshot') and self._current_screenshot:
            lightbox = TavernScreenshotLightbox(self._current_screenshot)
            lightbox.present_with_animation(self.get_root())

    def _on_readme_fetched(self, package, text):
        if not text or package != self._package:
            return
        self._readme_text = text

        # Prefer inline README rendering when WebKit is available, so animated
        # GIF/WebM embedded in READMEs can play directly in the details view.
        if self._render_readme_webview(text):
            self.readme_bin.set_visible(True)
            return

        # Build a plain-text preview from the first ~6 lines, skipping headings/blanks
        preview_lines = []
        for line in text.splitlines():
            stripped = line.strip()
            # Skip markdown headings, blank lines, images, badges, horizontal rules
            if not stripped or stripped.startswith('#') or stripped.startswith('!') or stripped.startswith('---') or stripped.startswith('==='):
                continue
            # Strip inline markdown formatting for preview
            clean = stripped.lstrip('*_>`-').strip()
            if clean:
                preview_lines.append(clean)
            if len(preview_lines) >= 6:
                break
        preview_text = '\n'.join(preview_lines) if preview_lines else text[:300]
        self.readme_preview_label.set_label(preview_text)
        self.readme_preview_box.set_visible(True)
        self.readme_fade_overlay.set_visible(True)
        self.readme_bin.set_visible(True)

    def _readme_base_uri(self):
        """Return a base URI for resolving relative README assets."""
        if not self._package or not self._package.source_url:
            return None

        # Typical source_url: https://github.com/<owner>/<repo>
        src = self._package.source_url.rstrip('/')
        if not src.startswith('https://github.com/'):
            return None

        parts = src.split('/')
        if len(parts) < 5:
            return None
        owner, repo = parts[3], parts[4]
        return f'https://raw.githubusercontent.com/{owner}/{repo}/HEAD/'

    def _render_readme_webview(self, text):
        if WebKit is None:
            return False

        try:
            if self._readme_webview is None:
                self._readme_webview = WebKit.WebView()
                self._readme_webview.set_vexpand(True)
                self._readme_webview.set_hexpand(True)
                self._readme_webview.set_size_request(-1, 420)
                self._readme_webview.add_css_class('readme-webview')

                settings = self._readme_webview.get_settings()
                if settings is not None:
                    settings.set_enable_javascript(False)

                self.readme_preview_box.remove(self.readme_preview_label)
                self.readme_preview_box.append(self._readme_webview)

            try:
                import markdown as md
                html_body = md.markdown(
                    text,
                    extensions=['fenced_code', 'tables', 'nl2br'],
                    output_format='html5',
                )
            except Exception:
                # Fallback if python-markdown is missing or errors.
                escaped = GLib.markup_escape_text(text)
                html_body = f'<pre>{escaped}</pre>'

            html = f"""
<!doctype html>
<html>
  <head>
    <meta charset=\"utf-8\" />
    <style>
      body {{
        font-family: sans-serif;
        margin: 0;
        padding: 0;
        color: #d8d8d8;
        background: transparent;
      }}
      a {{ color: #8ab4ff; }}
      img, video {{ max-width: 100%; height: auto; border-radius: 8px; }}
      pre, code {{ white-space: pre-wrap; word-break: break-word; }}
    </style>
  </head>
  <body>{html_body}</body>
</html>
"""
            self._readme_webview.load_html(html, self._readme_base_uri())
            self.readme_fade_overlay.set_visible(False)
            return True
        except Exception as e:
            _log.debug('README webview render failed, using text preview: %s', e)
            return False

    @Gtk.Template.Callback()
    def on_show_readme_clicked(self, *args):
        if self._package and self._package.homepage:
            _log.debug('Opening homepage externally for README')
            launcher = Gtk.UriLauncher.new(self._package.homepage)
            launcher.launch(self.get_root(), None, None, None)


    # Removed Read More and Debug button handlers



    # ── Task binding ─────────────────────────────────────────────
    def _bind_task(self, task):
        """Bind a Task — disable button + show slim progress bar; global bar handles overall feedback."""
        self._task = task
        self._update_buttons()
        self.detail_progress_bar.set_fraction(0.05)
        self.detail_progress_bar.set_visible(True)
        task.connect('notify::progress', self._on_task_progress)
        task.connect('finished', self._on_task_finished)

    def _on_task_progress(self, task, pspec):
        self.detail_progress_bar.set_fraction(task.progress)

    def _on_task_finished(self, task, success):
        _log.info('Detail task finished: %s  success=%s', task.title, success)
        self._task = None
        self.detail_progress_bar.set_fraction(1.0 if success else 0.0)
        self.detail_progress_bar.set_visible(False)
        self._update_buttons()
        if not success and task.error_detail:
            self.error_label.set_label(task.error_detail)
            self.error_label.set_visible(True)
        else:
            self.error_label.set_visible(False)
        self.emit('package-changed', self._package)

    # ── Button handlers ──────────────────────────────────────────
    def _on_install_clicked(self, button):
        if not self._task_manager:
            return
        _log.info('Install clicked: %s', self._package.name)
        task = self._task_manager.install(self._package)
        self._bind_task(task)

    def _on_update_clicked(self, button):
        if not self._task_manager:
            return
        _log.info('Update clicked: %s', self._package.name)
        task = self._task_manager.install(self._package)  # Upgrade uses the install operation
        self._bind_task(task)

    def _on_remove_clicked(self, button):
        if not self._task_manager:
            return
        _log.info('Remove clicked: %s', self._package.name)
        task = self._task_manager.remove(self._package)
        self._bind_task(task)

    def _on_info_row_activated(self, listbox, row):
        if row == self.version_row and self._package:
            self.emit('package-history-requested', self._package)
        elif row == self.homepage_row and self._package and self._package.homepage:
            launcher = Gtk.UriLauncher.new(self._package.homepage)
            launcher.launch(self.get_root(), None, None, None)
        elif row == self.installs_row and self._package and self._package._raw_analytics:
            try:
                from .stats_dialog import TavernStatsDialog
                dialog = TavernStatsDialog(self._package)
                dialog.present(self.get_root())
            except ImportError:
                _log.error('TavernStatsDialog not found')
            except Exception as e:
                _log.error('Failed to open stats dialog: %s', e)
