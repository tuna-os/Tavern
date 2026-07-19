# media.py - Icon, screenshot, and README fetching (mixin for BrewBackend)
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import threading
from urllib.request import Request

import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GLib, GdkPixbuf

from .backend_icons import ico_to_png as _ico_to_png
from .logging_util import get_logger

_log = get_logger('media')


def urlopen(req, timeout=None):
    """Resolve through the backend module so test monkeypatches of
    tavern.backend.urlopen keep working for media fetches."""
    from . import backend
    return backend.urlopen(req, timeout=timeout)


class MediaMixin:
    """Network media fetching mixed into BrewBackend."""

    def fetch_icon_async(self, package, callback):
        """Fetch an icon for the package on a bounded worker pool.

        Concurrent requests for the same package are coalesced: only one
        network fetch runs, and every registered callback receives the result.
        """
        with self._icon_lock:
            waiters = self._icon_inflight.get(package.name)
            if waiters is not None:
                waiters.append((package, callback))
                return
            self._icon_inflight[package.name] = [(package, callback)]
        self._icon_executor.submit(self._fetch_icon_job, package)

    def _fetch_icon_job(self, package):
        try:
            pixbuf = self._fetch_icon(package)
        except Exception as e:
            _log.debug('Icon fetch failed for %s: %s', package.name, e)
            pixbuf = None
        with self._icon_lock:
            waiters = self._icon_inflight.pop(package.name, [])
        for pkg, cb in waiters:
            GLib.idle_add(cb, pkg, pixbuf)

    def _fetch_icon(self, package):
        """Try multiple icon sources for a package. Returns a pixbuf or None."""
        _log.debug('Fetching icon for %s', package.name)
        icon_path = os.path.join(self._cache_dir, f'icon_{package.name}.png')

        if os.path.exists(icon_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(icon_path, 64, 64, True)
                _log.debug('Loaded cached icon for %s: %dx%d', package.name, pixbuf.get_width(), pixbuf.get_height())
                return pixbuf
            except Exception as e:
                _log.debug('Failed to load cached icon for %s: %s', package.name, e)

        icon_urls = []

        # 0. Explicit icon URL (used by flatpak appstream metadata)
        if getattr(package, 'icon_url', None):
            icon_urls.append(package.icon_url)

        is_github_repo = False
        github_owner = None
        
        # Check if homepage implies a GitHub repo
        if package.homepage and 'github.com' in package.homepage:
            import re
            m = re.search(r'github\.com/([^/\s"\']+)/([^/\s"\'#?.]+)', package.homepage)
            if m:
                is_github_repo = True
                github_owner = m.group(1)

        # 1. First image from source repo README (good for projects with logo images)
        # Prioritize images containing keywords like 'logo' or 'brand'
        readme_images = self._fetch_readme_images(package)
        if readme_images:
            logo_images = [img for img in readme_images if any(kw in img.lower() for kw in ('logo', 'brand'))]
            if logo_images:
                icon_urls.extend(logo_images)
            # Add at most one non-logo image as a fallback to avoid excessive slow network requests
            non_logo_images = [img for img in readme_images if img not in logo_images]
            if non_logo_images:
                icon_urls.append(non_logo_images[0])
            
        # 2. GitHub org/user avatar (if it's a GitHub repo)
        if is_github_repo and github_owner:
            icon_urls.append(f'https://github.com/{github_owner}.png?size=128')

        # 3. Scrape the homepage HTML for the best available favicon
        if package.homepage and not is_github_repo:
            domain = package.homepage.replace('https://', '').replace('http://', '').split('/')[0]
            if not domain.endswith('gitlab.com'):
                favicon_url = self._find_favicon_url(package.homepage)
                if favicon_url:
                    icon_urls.append(favicon_url)

        # 4. Google S2 favicon service
        if package.homepage and not is_github_repo:
            domain = package.homepage.replace('https://', '').replace('http://', '').split('/')[0]
            icon_urls.append(f'https://www.google.com/s2/favicons?domain={domain}&sz=128')

        # 5. DuckDuckGo favicon service
        if package.homepage and not is_github_repo:
            domain = package.homepage.replace('https://', '').replace('http://', '').split('/')[0]
            icon_urls.append(f'https://icons.duckduckgo.com/ip3/{domain}.ico')

        for url in icon_urls:
            try:
                req = Request(url, headers={'User-Agent': 'Mozilla/5.0 Tavern/0.1'})
                with urlopen(req, timeout=10) as resp:
                    data = resp.read()
                    if len(data) < 200:  # Filter out 1x1 pixel / blank responses
                        continue

                    # ICO files need conversion — GdkPixbuf may not support them
                    if (url.lower().endswith('.ico')
                            or resp.headers.get('Content-Type', '').startswith('image/x-icon')
                            or resp.headers.get('Content-Type', '').startswith('image/vnd.microsoft.icon')):
                        converted = _ico_to_png(data)
                        if converted:
                            data = converted
                        else:
                            continue  # Unusable ICO — skip to next source

                    loader = GdkPixbuf.PixbufLoader()
                    loader.write(data)
                    loader.close()
                    pixbuf = loader.get_pixbuf()
                    if pixbuf:
                        pixbuf = pixbuf.scale_simple(64, 64, GdkPixbuf.InterpType.BILINEAR)
                        with open(icon_path, 'wb') as f:
                            f.write(data)
                        _log.debug('Downloaded and loaded icon for %s from %s: %dx%d', package.name, url, pixbuf.get_width(), pixbuf.get_height())
                        return pixbuf
            except Exception as e:
                _log.debug('Icon source %s failed for %s: %s', url, package.name, e)
                continue

        _log.debug('No icon found for %s', package.name)
        return None

    def _find_favicon_url(self, homepage):
        """
        Fetch the homepage HTML and return the best favicon URL found, or None.

        Priority order:
          1. apple-touch-icon (usually 180×180 PNG — best quality)
          2. icon with PNG/ICO type
          3. shortcut icon
          4. /favicon.png directly
          5. /favicon.ico directly
        """
        import re
        try:
            req = Request(homepage, headers={'User-Agent': 'Mozilla/5.0 Tavern/0.1'})
            with urlopen(req, timeout=8) as resp:
                # Only read the <head> — stop after 32 KB to avoid downloading full pages
                chunk = resp.read(32768).decode('utf-8', errors='replace')
        except Exception:
            return None

        # Parse origin from the URL for resolving relative paths
        from urllib.parse import urljoin

        # Collect all <link> icon tags
        links = re.findall(
            r'<link\s[^>]*rel=["\']([^"\']*)["\'][^>]*href=["\']([^"\']+)["\']'
            r'|<link\s[^>]*href=["\']([^"\']+)["\'][^>]*rel=["\']([^"\']*)["\']',
            chunk, re.IGNORECASE
        )

        candidates = []
        for m in links:
            rel = (m[0] or m[3]).lower()
            href = m[1] or m[2]
            if not href or href.startswith('data:'):
                continue
            url = urljoin(homepage, href)
            if 'apple-touch-icon' in rel:
                candidates.append((0, url))  # Highest priority
            elif 'icon' in rel and href.lower().endswith('.png'):
                candidates.append((1, url))
            elif 'icon' in rel and href.lower().endswith('.ico'):
                candidates.append((2, url))
            elif 'icon' in rel:
                candidates.append((3, url))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            return candidates[0][1]

        # Fall back to root-relative well-known paths
        from urllib.parse import urlparse
        parsed = urlparse(homepage)
        base = f'{parsed.scheme}://{parsed.netloc}'
        for path in ('/favicon.png', '/favicon.ico'):
            url = base + path
            try:
                req = Request(url, headers={'User-Agent': 'Tavern/0.1'})
                with urlopen(req, timeout=5) as resp:
                    if resp.status == 200 and int(resp.headers.get('Content-Length', '9999')) > 200:
                        return url
            except Exception:
                continue

        return None



    def fetch_screenshot_async(self, package, callback):
        """Try to fetch a screenshot for the package."""
        thread = threading.Thread(
            target=self._fetch_screenshot_thread,
            args=(package, callback),
            daemon=True,
        )
        thread.start()

    def fetch_readme_async(self, package, callback):
        """Fetch the README text for a package from its GitHub source repo."""
        thread = threading.Thread(
            target=self._fetch_readme_thread,
            args=(package, callback),
            daemon=True,
        )
        thread.start()

    def _fetch_readme_thread(self, package, callback):
        import re
        GH_RE = re.compile(r'github\.com/([^/\s"\']+)/([^/\s"\'#?.]+)')

        owner, repo = None, None
        for candidate in (getattr(package, 'source_url', ''), package.homepage or ''):
            if not candidate:
                continue
            m = GH_RE.search(candidate)
            if m:
                o, r = m.group(1), m.group(2).rstrip('.git')
                if o.lower() not in ('releases', 'downloads', 'mirrors', 'raw', 'orgs', 'users'):
                    owner, repo = o, r
                    break

        if not owner:
            GLib.idle_add(callback, package, None)
            return

        text = None
        for readme_name in ('README.md', 'readme.md', 'Readme.md', 'README.rst', 'README'):
            raw_url = f'https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{readme_name}'
            try:
                req = Request(raw_url, headers={'User-Agent': 'Tavern/0.1'})
                with urlopen(req, timeout=15) as resp:
                    text = resp.read().decode('utf-8', errors='replace')
                break
            except Exception:
                continue

        GLib.idle_add(callback, package, text)



    def _fetch_screenshot_thread(self, package, callback):
        """Try to fetch a screenshot image for a package."""
        screenshot_path = os.path.join(self._cache_dir, f'screenshot_{package.name}.jpg')

        if os.path.exists(screenshot_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(screenshot_path, 800, 600, True)
                GLib.idle_add(callback, package, pixbuf)
                return
            except Exception:
                pass

        screenshot_urls = []

        # 1. tavern-metadata repo (curated)
        screenshot_urls.append(f'https://raw.githubusercontent.com/hanthor/tavern-metadata/main/screenshots/{package.name}.jpg')

        # 2. README images from source repo (skip the first one — that's the icon)
        readme_images = self._fetch_readme_images(package)
        if readme_images and len(readme_images) > 1:
            # Second image onwards are typically screenshots
            screenshot_urls.extend(readme_images[1:4])

        for url in screenshot_urls:
            try:
                req = Request(url, headers={'User-Agent': 'Tavern/0.1'})
                with urlopen(req, timeout=10) as resp:
                    data = resp.read()
                    if len(data) > 100:
                        with open(screenshot_path, 'wb') as f:
                            f.write(data)
                        loader = GdkPixbuf.PixbufLoader()
                        loader.write(data)
                        loader.close()
                        pixbuf = loader.get_pixbuf()
                        if pixbuf:
                            pixbuf = pixbuf.scale_simple(800, 600, GdkPixbuf.InterpType.BILINEAR)
                            GLib.idle_add(callback, package, pixbuf)
                            return
            except Exception:
                continue

        GLib.idle_add(callback, package, None)

    def _fetch_readme_images(self, package):
        """
        Extract absolute image URLs from the project's GitHub README.

        Returns a list of image URLs (may be empty). Results are cached
        on the Package object to avoid duplicate network hits when both
        the icon and screenshot threads run.
        """
        import re

        # Cache on the package object so icon + screenshot threads share the result
        cached = getattr(package, '_readme_images', None)
        if cached is not None:
            return cached

        package._readme_images = []  # mark as attempted

        GH_RE = re.compile(r'github\.com/([^/\s"\']+)/([^/\s"\'#?.]+)')

        owner, repo = None, None
        # source_url (stable tarball) is the most reliable source — check it first.
        # It's a direct GitHub archive/releases URL for the vast majority of formulae.
        for candidate in (getattr(package, 'source_url', ''), package.homepage or ''):
            if not candidate:
                continue
            m = GH_RE.search(candidate)
            if m:
                o = m.group(1)
                r = m.group(2).rstrip('.git')
                # Skip well-known non-project paths
                if o.lower() in ('releases', 'downloads', 'mirrors', 'raw', 'orgs', 'users'):
                    continue
                owner, repo = o, r
                break

        if not owner:
            return []

        # Try common README filenames in order
        text = None
        for readme_name in ('README.md', 'readme.md', 'Readme.md', 'README.rst'):
            raw_url = f'https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{readme_name}'
            try:
                req = Request(raw_url, headers={'User-Agent': 'Tavern/0.1'})
                with urlopen(req, timeout=10) as resp:
                    text = resp.read().decode('utf-8', errors='replace')
                break
            except Exception:
                continue

        if not text:
            return []

        # Extract markdown image syntax:  ![alt](url)
        # and HTML <img src="url"> tags
        md_images = re.findall(r'!\[.*?\]\(([^)]+)\)', text)
        html_images = re.findall(r"""<img\s[^>]*src=["']([^"']+)["']""", text, re.IGNORECASE)
        all_images = md_images + html_images

        # Resolve relative URLs to absolute GitHub raw URLs
        base_raw = f'https://raw.githubusercontent.com/{owner}/{repo}/HEAD/'

        absolute = []
        for img in all_images:
            img = img.strip()
            if not img:
                continue
            if img.startswith('http://') or img.startswith('https://'):
                url = img
            elif img.startswith('./'):
                url = base_raw + img[2:]
            elif img.startswith('/'):
                url = base_raw + img[1:]
            else:
                url = base_raw + img

            # Skip badge/shield images — not useful as icons or screenshots
            low = url.lower()
            if any(skip in low for skip in ('shields.io', 'badge', 'travis-ci', 'codecov',
                                             'appveyor', 'circleci', 'github/workflow',
                                             'actions/workflows', 'buymeacoffee',
                                             'ko-fi', 'opencollective', 'appimage',
                                             'flathub', 'snapcraft')):
                continue
            # Keep SVG if GdkPixbuf has SVG support; skip otherwise
            if low.endswith('.svg'):
                svg_ok = any(f.get_name() == 'svg' for f in GdkPixbuf.Pixbuf.get_formats())
                if not svg_ok:
                    continue

            absolute.append(url)

        package._readme_images = absolute
        return absolute
