# package_details_helpers.py - Presentation and formatting helpers for package details
# SPDX-License-Identifier: GPL-3.0-or-later

import html
import re

FONT_PANGRAM = 'The quick brown fox jumps over the lazy dog.'


def format_install_count(count):
    """Format install count into human-readable string (e.g. 1.25M, 150.00K)."""
    if not count or count <= 0:
        return None
    if count >= 1_000_000:
        return f"{count / 1_000_000:.2f}M"
    elif count >= 1000:
        return f"{count / 1000:.2f}K"
    else:
        return f"{count:,}"


def extract_readme_preview(text, max_lines=6):
    """Build a plain-text preview from lines, skipping headings, badges, and rules."""
    if not text:
        return ""
    preview_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        # Skip markdown headings, blank lines, images, badges, horizontal rules
        if (not stripped or stripped.startswith('#') or stripped.startswith('!') or
                stripped.startswith('---') or stripped.startswith('===')):
            continue
        # Strip inline markdown formatting for preview
        clean = stripped.lstrip('*_>`-').strip()
        if clean:
            preview_lines.append(clean)
        if len(preview_lines) >= max_lines:
            break
    return '\n'.join(preview_lines) if preview_lines else text[:300]


def compute_readme_base_uri(source_url):
    """Compute base URI for resolving relative README assets from package source URL."""
    if not source_url:
        return None
    src = source_url.rstrip('/')
    if not src.startswith('https://github.com/'):
        return None
    parts = src.split('/')
    if len(parts) < 5:
        return None
    owner, repo = parts[3], parts[4]
    return f'https://raw.githubusercontent.com/{owner}/{repo}/HEAD/'


def build_readme_html(text, is_dark=False):
    """Generate isolated HTML markup for README WebView rendering."""
    try:
        import markdown as md
        html_body = md.markdown(
            text,
            extensions=['fenced_code', 'tables', 'nl2br'],
            output_format='html5',
        )
    except Exception:
        escaped = html.escape(text)
        html_body = f'<pre>{escaped}</pre>'

    default_color = '#e4e4e4' if is_dark else '#1c1c1c'
    default_link = '#78aeed' if is_dark else '#1a5fb4'

    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>
      html, body {{
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        margin: 0;
        padding: 0;
        color: {default_color};
        background: transparent !important;
        background-color: transparent !important;
      }}
      a {{ color: {default_link}; }}
      img, video {{ max-width: 100%; height: auto; border-radius: 8px; }}
      pre, code {{ white-space: pre-wrap; word-break: break-word; }}

      @media (prefers-color-scheme: dark) {{
        body {{ color: #e4e4e4; }}
        a {{ color: #78aeed; }}
      }}
      @media (prefers-color-scheme: light) {{
        body {{ color: #1c1c1c; }}
        a {{ color: #1a5fb4; }}
      }}
    </style>
  </head>
  <body>{html_body}</body>
</html>"""


def get_font_family_name(package):
    """Determine font family name from package display_name or name."""
    if getattr(package, 'display_name', None):
        return package.display_name
    name = getattr(package, 'name', '') or ''
    return name.removeprefix('font-').replace('-', ' ').title()


def get_font_preview_samples(family_name):
    """Return standard pangram and typography sample tuples (text, size_pt)."""
    return [
        (family_name, 32),
        ('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 15),
        ('abcdefghijklmnopqrstuvwxyz 0123456789', 15),
        (FONT_PANGRAM, 22),
        (FONT_PANGRAM, 13),
    ]
