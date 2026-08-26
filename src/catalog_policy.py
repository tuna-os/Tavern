# catalog_policy.py - Deterministic catalog filtering, ranking, and curation
# SPDX-License-Identifier: GPL-3.0-or-later

from dataclasses import dataclass
from datetime import date, datetime, timezone
from urllib.parse import urlparse


DEFAULT_CURATION = {
    'schema_version': 1,
    'sections': [
        {
            'id': 'popular-formulae',
            'title': 'Popular Formulae',
            'package_type': 'formula',
            'packages': [
                'git', 'wget', 'curl', 'node', 'python@3.12', 'ffmpeg',
                'htop', 'vim', 'neovim', 'tmux', 'ripgrep', 'fzf', 'jq',
                'bat', 'eza', 'imagemagick', 'yt-dlp', 'gh', 'go', 'rust',
            ],
        },
        {
            'id': 'popular-casks',
            'title': 'Popular Casks',
            'package_type': 'cask',
            'packages': [
                'firefox', 'google-chrome', 'visual-studio-code', 'vlc',
                'slack', 'zoom', 'spotify', 'discord', 'rectangle',
                'obsidian', 'warp', 'tableplus', 'postman', 'docker', 'alfred',
            ],
        },
        {
            'id': 'tunaos-picks',
            'title': 'TunaOS Picks',
            'package_type': 'formula',
            'packages': [
                'ripgrep', 'fd', 'fzf', 'bat', 'eza', 'zoxide', 'jq',
                'shellcheck', 'just', 'btop', 'lazygit', 'starship',
            ],
        },
    ],
}


@dataclass(frozen=True)
class CatalogFilters:
    query: str = ''
    package_types: frozenset[str] = frozenset()
    installed_only: bool = False
    outdated_only: bool = False
    pinned_only: bool = False
    vulnerable_only: bool = False
    compatible_only: bool = False
    tap: str = ''


def package_matches(package, filters, *, outdated=(), pinned=(), platform=None):
    """Return whether *package* matches a stable, composable filter set."""
    query = filters.query.casefold().strip()
    searchable = ' '.join((
        package.name,
        getattr(package, 'display_name', ''),
        getattr(package, 'description', ''),
    )).casefold()
    if query and query not in searchable:
        return False
    if filters.package_types and package.pkg_type not in filters.package_types:
        return False
    if filters.installed_only and not package.installed:
        return False
    names = {package.name, package.full_name}
    if filters.outdated_only and names.isdisjoint(outdated):
        return False
    if filters.pinned_only and names.isdisjoint(pinned):
        return False
    if filters.vulnerable_only and not package.has_known_vulnerability:
        return False
    if filters.compatible_only and not package.supports_platform(platform):
        return False
    if filters.tap and getattr(package, 'tap', '') != filters.tap:
        return False
    return True


def search_rank(package, query):
    """Rank exact/prefix/display/description matches deterministically."""
    query = query.casefold().strip()
    name = package.name.casefold()
    display_name = getattr(package, 'display_name', '').casefold()
    description = getattr(package, 'description', '').casefold()
    if name == query:
        match = 0
    elif display_name == query:
        match = 1
    elif name.startswith(query):
        match = 2
    elif display_name.startswith(query):
        match = 3
    elif query in name or query in display_name:
        match = 4
    elif query in description:
        match = 5
    else:
        match = 6
    return (match, -(getattr(package, 'installs_30d', 0) or 0), name)


def filter_packages(packages, filters, *, outdated=(), pinned=(), platform=None):
    return [
        package for package in packages
        if package_matches(
            package, filters, outdated=outdated, pinned=pinned, platform=platform,
        )
    ]


def sort_packages(packages, mode='name', *, outdated=(), pinned=()):
    outdated = set(outdated)
    pinned = set(pinned)

    def key(package):
        names = {package.name, package.full_name}
        label = (package.display_name or package.name).casefold()
        if mode == 'updates':
            return (names.isdisjoint(outdated), label)
        if mode == 'type':
            return (package.pkg_type, label)
        if mode == 'tap':
            return (getattr(package, 'tap', '').casefold(), label)
        if mode == 'security':
            return (not package.has_known_vulnerability, label)
        if mode == 'pinned':
            return (names.isdisjoint(pinned), label)
        return (label,)

    return sorted(packages, key=key)


def validate_curation(data):
    """Validate the small remote curation schema and return normalized data."""
    if not isinstance(data, dict) or data.get('schema_version') != 1:
        raise ValueError('Unsupported curation schema')
    sections = data.get('sections')
    if not isinstance(sections, list):
        raise ValueError('Curation sections must be a list')
    normalized = []
    section_ids = set()
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError('Curation section must be an object')
        section_id = section.get('id')
        title = section.get('title')
        package_type = section.get('package_type')
        packages = section.get('packages')
        if not isinstance(section_id, str) or not section_id.strip():
            raise ValueError('Curation section id is required')
        if not isinstance(title, str) or not title.strip():
            raise ValueError('Curation section title is required')
        if package_type not in ('formula', 'cask'):
            raise ValueError('Curation package_type must be formula or cask')
        if not isinstance(packages, list) or not all(
            isinstance(name, str) and name for name in packages
        ):
            raise ValueError('Curation packages must be non-empty strings')
        section_id = section_id.strip()
        if section_id in section_ids:
            raise ValueError('Curation section ids must be unique')
        section_ids.add(section_id)
        summary = section.get('summary', '')
        link = section.get('link', '')
        platforms = section.get('platforms', [])
        starts_at = section.get('starts_at', '')
        ends_at = section.get('ends_at', '')
        if not isinstance(summary, str) or len(summary) > 240:
            raise ValueError('Curation summary must be at most 240 characters')
        if link and (not isinstance(link, str) or urlparse(link).scheme != 'https'):
            raise ValueError('Curation links must use HTTPS')
        if not isinstance(platforms, list) or not all(
            value in ('linux', 'darwin') for value in platforms
        ):
            raise ValueError('Curation platforms must contain linux or darwin')
        for value in (starts_at, ends_at):
            if value:
                try:
                    date.fromisoformat(value)
                except (TypeError, ValueError):
                    raise ValueError('Curation validity dates must use YYYY-MM-DD')
        if starts_at and ends_at and starts_at > ends_at:
            raise ValueError('Curation validity window is inverted')
        normalized.append({
            'id': section_id,
            'title': title.strip(),
            'package_type': package_type,
            'packages': list(dict.fromkeys(packages))[:24],
            'summary': summary.strip(),
            'link': link,
            'platforms': platforms,
            'starts_at': starts_at,
            'ends_at': ends_at,
        })
    return {'schema_version': 1, 'sections': normalized[:8]}


def curated_packages(packages, names, limit=24):
    by_name = {package.name: package for package in packages}
    return [by_name[name] for name in names if name in by_name][:limit]


def curation_section(data, section_id, *, platform=None, today=None):
    """Return a section only when its platform and validity window apply."""
    if today is None:
        today = datetime.now(timezone.utc).date()
    elif isinstance(today, str):
        today = date.fromisoformat(today)
    for section in data.get('sections', []):
        if section.get('id') == section_id:
            platforms = section.get('platforms') or []
            if platforms and platform not in platforms:
                return None
            starts_at = section.get('starts_at')
            ends_at = section.get('ends_at')
            if starts_at and today < date.fromisoformat(starts_at):
                return None
            if ends_at and today > date.fromisoformat(ends_at):
                return None
            return section
    return None
