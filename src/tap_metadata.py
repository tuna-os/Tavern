"""Pure metadata extraction for locally installed Homebrew taps."""

import re


def _read_header(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as source:
            return source.read(8192)
    except Exception:
        return None


def _extract(source, pattern, default=''):
    match = re.search(pattern, source, re.MULTILINE)
    return match.group(1).strip() if match else default


def parse_formula_file(path, tap_name, package_name):
    """Return formula API-shaped metadata from a Ruby formula header."""
    source = _read_header(path)
    if source is None:
        return None

    version = _extract(source, r'^\s*version\s+["\']([^"\']+)["\']') or _extract(
        source, r'tag:\s+["\']v?([^"\']+)["\']'
    )
    return {
        'name': package_name,
        'full_name': f'{tap_name}/{package_name}',
        'desc': _extract(source, r'^\s*desc\s+["\']([^"\']+)["\']'),
        'homepage': _extract(source, r'^\s*homepage\s+["\']([^"\']+)["\']'),
        'versions': {'stable': version},
        'license': _extract(source, r'^\s*license\s+["\']([^"\']+)["\']'),
        'urls': {
            'stable': {
                'url': _extract(source, r'^\s*url\s+["\']([^"\']+)["\']')
            }
        },
    }


def parse_cask_file(path, tap_name, package_name):
    """Return cask API-shaped metadata from a Ruby cask header."""
    source = _read_header(path)
    if source is None:
        return None

    name = _extract(source, r'^\s*name\s+["\']([^"\']+)["\']')
    description = _extract(source, r'^\s*desc\s+["\']([^"\']+)["\']')
    token_match = re.search(r'cask\s+["\']([^"\']+)["\']', source)
    token = token_match.group(1) if token_match else package_name
    depends_on = {}
    if 'macos' in source.lower() and re.search(r'depends_on\s+macos:', source):
        depends_on['macos'] = True

    return {
        'token': token,
        'full_token': f'{tap_name}/{token}',
        'name': [name] if name else ([description] if description else [token]),
        'desc': description,
        'homepage': _extract(source, r'^\s*homepage\s+["\']([^"\']+)["\']'),
        'version': _extract(source, r'^\s*version\s+["\']([^"\']+)["\']'),
        'url': _extract(source, r'^\s*url\s+["\']([^"\']+)["\']'),
        'depends_on': depends_on,
    }
