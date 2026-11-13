# readme_renderer.py - Pure README presentation helpers
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transform package README data into details-page presentation values."""

import re
from urllib.parse import urlparse

from gi.repository import GLib

# README text is untrusted. The document may not load anything except https
# images, and may not submit forms or change its base URI.
README_CSP = (
    "default-src 'none'; img-src https: data:; style-src 'unsafe-inline'; "
    "form-action 'none'; base-uri 'none'; frame-src 'none'; object-src 'none'"
)

# Raw HTML elements that load subresources, navigate, or restyle the page.
_BLOCKED_PAIRED = re.compile(
    r'<\s*(script|iframe|object|embed|form|style|noscript|svg|math|template)\b.*?<\s*/\s*\1\s*>',
    re.IGNORECASE | re.DOTALL,
)
_BLOCKED_SINGLE = re.compile(
    r'<\s*/?\s*(script|iframe|object|embed|form|style|noscript|svg|math|template|'
    r'meta|link|base|frame|frameset|applet|input|button|textarea|select)\b[^>]*>?',
    re.IGNORECASE,
)

_EXTERNAL_SCHEMES = frozenset({'http', 'https', 'mailto'})


def strip_unsafe_html(html):
    """Remove raw HTML elements that could load content or navigate."""
    previous = None
    while previous != html:
        previous = html
        html = _BLOCKED_PAIRED.sub('', html)
    return _BLOCKED_SINGLE.sub('', html)


def is_external_link_allowed(uri):
    """True only for http(s)/mailto links that may be handed to the launcher."""
    try:
        return urlparse(uri or '').scheme.lower() in _EXTERNAL_SCHEMES
    except ValueError:
        return False


class ReadmeRenderer:
    """Render README text without owning any GTK widgets or page state."""

    def preview(self, text):
        """Return a short plain-text preview suitable for a GTK label."""
        preview_lines = []
        for line in text.splitlines():
            stripped = line.strip()
            # Skip markdown headings, blank lines, images, badges, and rules.
            if (
                not stripped
                or stripped.startswith('#')
                or stripped.startswith('!')
                or stripped.startswith('---')
                or stripped.startswith('===')
            ):
                continue
            clean = stripped.lstrip('*_>`-').strip()
            if clean:
                preview_lines.append(clean)
            if len(preview_lines) >= 6:
                break
        return '\n'.join(preview_lines) if preview_lines else text[:300]

    def base_uri(self, source_url):
        """Return the raw GitHub directory used for relative README assets."""
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

    def html(self, text, is_dark=False):
        """Convert README markdown into the self-contained WebView document."""
        try:
            import markdown as md

            html_body = md.markdown(
                text,
                extensions=['fenced_code', 'tables', 'nl2br'],
                output_format='html5',
            )
            html_body = strip_unsafe_html(html_body)
        except Exception:
            # Keep the existing safe fallback when python-markdown is absent.
            escaped = GLib.markup_escape_text(text)
            html_body = f'<pre>{escaped}</pre>'

        default_color = '#e4e4e4' if is_dark else '#1c1c1c'
        default_link = '#78aeed' if is_dark else '#1a5fb4'
        return f"""
<!doctype html>
<html>
  <head>
    <meta http-equiv="Content-Security-Policy" content="{README_CSP}" />
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
</html>
"""

    def format_install_count(self, count):
        """Format a Homebrew install count, or return an empty value for zero."""
        if count <= 0:
            return ''
        if count >= 1_000_000:
            return f'{count / 1_000_000:.2f}M'
        if count >= 1000:
            return f'{count / 1000:.2f}K'
        return f'{count:,}'
