# page_factory.py - Instantiates pages/dialogs with their shared dependencies
# SPDX-License-Identifier: GPL-3.0-or-later

from .logging_util import get_logger

_log = get_logger('page_factory')


class PageFactory:
    """Build pages and dialogs wired to the shared ``backend`` / ``task_manager``.

    The window is a view-layout + navigation coordinator. This factory owns
    every place a page or dialog is constructed so ``window.py`` never has to
    know a page's constructor signature or dependency list.

    Two kinds of pages exist:

    * **Static** pages (``browse``, ``search``, ``installed``, ``tap``, ``doctor``) are
      built by ``window.blp`` as ``Gtk.Template.Child`` widgets, so they
      cannot be constructed here. ``wire_pages`` resolves their dependencies
      in one place instead of scattering ``set_backend`` calls through the
      window.
    * **Dynamic** pages/dialogs (package details, version history, Brewfile
      tabs, maintenance) are created on demand. Each ``create_*`` method
      supplies ``backend`` / ``task_manager`` so the caller only passes the
      page-specific arguments.

    Adding a page dependency (a preferences manager, settings store, theme
    service, ...) changes only this file and the page — never ``window.py``.
    """

    def __init__(self, backend, task_manager):
        self.backend = backend
        self.task_manager = task_manager

    def wire_pages(self, browse_page, search_page, installed_page, tap_page, doctor_page):
        """Inject shared dependencies into the template-built pages."""
        browse_page.set_backend(self.backend)
        search_page.set_backend(self.backend)
        installed_page.set_backend_and_manager(self.backend, self.task_manager)
        tap_page.set_backend(self.backend)
        doctor_page.set_task_manager(self.task_manager)

    def create_package_details(self, package):
        """Create the package-details navigation page."""
        from .package_details import TavernPackageDetails
        return TavernPackageDetails(
            package=package,
            backend=self.backend,
            task_manager=self.task_manager,
        )

    def create_version_history(self, package):
        """Create the version-history navigation page."""
        from .version_history_dialog import TavernVersionHistoryDialog
        return TavernVersionHistoryDialog(
            package=package,
            backend=self.backend,
        )

    def create_brewfile_page(self):
        """Create a fresh Brewfile page wired to the backend and task manager.

        Tab management (unique names, stack insertion) stays in window.py —
        the factory only produces the page.
        """
        from .brewfile_page import TavernBrewfilePage
        page = TavernBrewfilePage()
        page.set_backend_and_manager(self.backend, self.task_manager)
        return page

    def create_maintenance_page(self):
        """Create the on-demand maintenance page."""
        from .maintenance_page import MaintenancePage
        return MaintenancePage(self.task_manager)
