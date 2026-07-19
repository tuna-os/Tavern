# package.py - Package model for formulae, casks, and flatpaks
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
from gi.repository import GObject


class Package(GObject.Object):
    """Represents a Homebrew formula or cask."""

    __gtype_name__ = 'TavernPackage'

    name = GObject.Property(type=str, default='')
    full_name = GObject.Property(type=str, default='')
    description = GObject.Property(type=str, default='')
    homepage = GObject.Property(type=str, default='')
    version = GObject.Property(type=str, default='')
    pkg_type = GObject.Property(type=str, default='formula')  # 'formula', 'cask', or 'flatpak'
    installed = GObject.Property(type=bool, default=False)
    display_name = GObject.Property(type=str, default='')
    icon_url = GObject.Property(type=str, default='')
    license_ = GObject.Property(type=str, default='')

    # Live task state (driven by TaskManager)
    task_active   = GObject.Property(type=bool,  default=False)
    task_progress = GObject.Property(type=float, default=0.0)
    task_label    = GObject.Property(type=str,   default='')

    def __init__(self, data=None, pkg_type='formula', installed_set=None, **kwargs):
        super().__init__()
        self._raw_analytics = {}
        self.source_url = ''
        self.dependencies = []  # list[str] — formula names this package depends on
        self.tap = ''           # e.g. 'homebrew/core' or 'foo/bar' for tapped pkgs
        self._installs_30d = None
        self._installs_90d = None
        self._installs_365d = None

        if data:
            self.pkg_type = pkg_type
            self._from_api(data, pkg_type, installed_set)

        # Caller-provided kwargs take precedence over parsed API data
        for k, v in kwargs.items():
            setattr(self, k, v)

    def _from_api(self, data, pkg_type, installed_set=None):
        self._raw_analytics = data.get('analytics', {})
        self._installs_30d = None
        self._installs_90d = None
        self._installs_365d = None

        if pkg_type == 'formula':
            name = data.get('name', '')
            self.name = name
            self.full_name = data.get('full_name', name)
            self.display_name = name
            self.description = data.get('desc', '') or ''
            self.homepage = data.get('homepage', '') or ''
            versions = data.get('versions', {})
            self.version = versions.get('stable', '') or '' if isinstance(versions, dict) else ''
            self.license_ = data.get('license', '') or ''
            # Stable source URL — often a github.com release tarball
            urls = data.get('urls', {})
            stable = urls.get('stable', {}) if isinstance(urls, dict) else {}
            self.source_url = stable.get('url', '') or '' if isinstance(stable, dict) else ''
            deps = data.get('dependencies', []) or []
            self.dependencies = [d for d in deps if isinstance(d, str)]
            self.tap = data.get('tap', '') or ''
        elif pkg_type == 'cask':
            name = data.get('token', '')
            self.name = name
            self.full_name = data.get('full_token', name)
            names = data.get('name', [])
            self.display_name = names[0] if names else name
            self.description = data.get('desc', '') or ''
            self.homepage = data.get('homepage', '') or ''
            self.version = data.get('version', '') or ''
            self.license_ = ''
            # Cask download URL
            self.source_url = data.get('url', '') or ''
            self.tap = data.get('tap', '') or ''
        else:
            app_id = data.get('id', '')
            self.name = app_id
            self.full_name = app_id
            self.display_name = data.get('name', '') or app_id
            self.description = data.get('summary', '') or ''
            self.homepage = (data.get('urls', {}) or {}).get('homepage', '') if isinstance(data.get('urls', {}), dict) else ''
            releases = data.get('releases', []) or []
            if isinstance(releases, list) and releases:
                self.version = (releases[0] or {}).get('version', '') or ''
            else:
                self.version = ''
            self.source_url = self.homepage
            self.icon_url = data.get('icon', '') or ''

        if installed_set:
            self.installed = name in installed_set or self.full_name in installed_set

    def _parse_analytics(self):
        if self._installs_30d is not None:
            return
        if not self._raw_analytics:
            self._installs_30d = 0
            self._installs_90d = 0
            self._installs_365d = 0
            return
        # Check for flat format first
        if 'installs_30d' in self._raw_analytics:
            self._installs_30d = self._raw_analytics.get('installs_30d', 0) or 0
            self._installs_90d = self._raw_analytics.get('installs_90d', 0) or 0
            self._installs_365d = self._raw_analytics.get('installs_365d', 0) or 0
            return
        # Fallback to nested Homebrew API format (install_on_request or install)
        nested = self._raw_analytics.get('install_on_request') or self._raw_analytics.get('install')
        if isinstance(nested, dict):
            self._installs_30d = sum(nested.get('30d', {}).values())
            self._installs_90d = sum(nested.get('90d', {}).values())
            self._installs_365d = sum(nested.get('365d', {}).values())
        else:
            self._installs_30d = 0
            self._installs_90d = 0
            self._installs_365d = 0

    @GObject.Property(type=int, default=0)
    def installs_30d(self):
        self._parse_analytics()
        return self._installs_30d

    @installs_30d.setter
    def installs_30d(self, value):
        self._installs_30d = value

    @GObject.Property(type=int, default=0)
    def installs_90d(self):
        self._parse_analytics()
        return self._installs_90d

    @installs_90d.setter
    def installs_90d(self, value):
        self._installs_90d = value

    @GObject.Property(type=int, default=0)
    def installs_365d(self):
        self._parse_analytics()
        return self._installs_365d

    @installs_365d.setter
    def installs_365d(self, value):
        self._installs_365d = value


