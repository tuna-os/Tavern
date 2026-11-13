# readme_renderer.py - Pure README presentation helpers
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transform package README data into details-page presentation values."""

from gi.repository import GLib

# README text is untrusted: it comes from whichever repository a package's
# metadata names, and python-markdown passes raw HTML through. The policy
# keeps what that HTML can load in line with the media policy in
# url_security.py: https images and media only, and no frames, forms,
# stylesheets, fonts or plugins. Scripts are also off in the view's settings.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; img-src https: data:; media-src https:; "
    "style-src 'unsafe-inline'; form-action 'none'; base-uri 'none'"
)

# Schemes a clicked README link may hand to the desktop.
EXTERNAL_LINK_SCHEMES = frozenset({'http', 'https', 'mailto'})


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
    <meta charset="utf-8" />
    <meta http-equiv="Content-Security-Policy" content="{CONTENT_SECURITY_POLICY}" />
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

    def navigation_policy(self, uri, *, link_clicked, document_uri=None):
        """Return 'load', 'open' or 'block' for a navigation in the README view.

        Only the rendered document itself loads in the view. A link opens
        outside the app only when the user clicked it and it uses a web or
        mail scheme. Everything else is blocked, which covers a README that
        redirects itself with ``<meta http-equiv="refresh">``.
        """
        if link_clicked:
            scheme = (uri or '').split(':', 1)[0].lower()
            return 'open' if scheme in EXTERNAL_LINK_SCHEMES else 'block'
        if uri and uri in ('about:blank', document_uri):
            return 'load'
        return 'block'

    def format_install_count(self, count):
        """Format a Homebrew install count, or return an empty value for zero."""
        if count <= 0:
            return ''
        if count >= 1_000_000:
            return f'{count / 1_000_000:.2f}M'
        if count >= 1000:
            return f'{count / 1000:.2f}K'
        return f'{count:,}'
