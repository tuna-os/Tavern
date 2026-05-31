#!/usr/bin/env python3
# test_assets.py - Test harness for fetching icons and screenshots for Tavern packages using actual logic from backend.py

import json
import os
import re
import urllib.request
from urllib.error import URLError, HTTPError
import threading
import struct

# API Endpoints
FORMULA_API = 'https://formulae.brew.sh/api/formula.json'
CASK_API = 'https://formulae.brew.sh/api/cask.json'

BASE_HEADERS = {'User-Agent': 'Tavern-Asset-Test-Harness/1.0'}

# 15 popular formulae (mostly CLI/dev tools) + 15 popular casks (GUI apps)
TEST_PACKAGES = {
    'formula': [
        'git', 'wget', 'curl', 'node', 'ffmpeg',
        'htop', 'neovim', 'tmux', 'ripgrep', 'fzf',
        'jq', 'bat', 'eza', 'lazygit', 'rust'
    ],
    'cask': [
        'firefox', 'google-chrome', 'visual-studio-code',
        'vlc', 'slack', 'discord', 'obsidian', 'postman',
        'docker', 'iterm2', 'spotify', 'zoom', 'raycast',
        'figma', 'notion'
    ]
}

def fetch_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or BASE_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except HTTPError as e:
        if e.code != 404:
            print(f"  HTTP {e.code} fetching {url}")
        return None
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return None

def is_github_org(org_name):
    """Check if a GitHub username belongs to an Organization."""
    data = fetch_json(f'https://api.github.com/users/{org_name}')
    if data and data.get('type') == 'Organization':
        print(f"  [GitHub] {org_name} is an Organization.")
        return True
    print(f"  [GitHub] {org_name} is NOT an Organization (skipping).")
    return False

def get_image_metadata_from_bytes(data):
    """
    Parse image dimensions directly from bytes.
    Returns (width, height) or None.
    Supports PNG, GIF, JPEG, and basic SVG.
    """
    try:
        # PNG
        if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 24:
            w, h = struct.unpack('>II', data[16:24])
            return (w, h)
            
        # GIF
        elif data.startswith(b'GIF87a') or data.startswith(b'GIF89a'):
            w, h = struct.unpack('<HH', data[6:10])
            return (w, h)

        # JPEG
        elif data.startswith(b'\xff\xd8'):
            offset = 2
            while offset < len(data) - 9:
                marker = data[offset]
                if marker == 0xff:
                    code = data[offset+1]
                    if code in (0xc0, 0xc2): # SOF0 or SOF2
                        h, w = struct.unpack('>HH', data[offset+5:offset+9])
                        return (w, h)
                    else:
                        length = struct.unpack('>H', data[offset+2:offset+4])[0]
                        offset += length + 2
                else:
                    break

        # SVG (very basic parsing)
        elif b'<svg' in data.lower():
            text = data.decode('utf-8', errors='ignore')
            m_vb = re.search(r'viewBox=["\"]?[\d\.]+s+[\d\.]+s+([\d\.]+)s+([\d\.]+)["\"]?', text, re.IGNORECASE)
            if m_vb:
                return (int(float(m_vb.group(1))), int(float(m_vb.group(2))))
            m_w = re.search(r'width=["\"]?([\d\.]+)["\"]?', text, re.IGNORECASE)
            m_h = re.search(r'height=["\"]?([\d\.]+)["\"]?', text, re.IGNORECASE)
            if m_w and m_h:
                return (int(float(m_w.group(1))), int(float(m_h.group(1))))
            return (512, 512) # Default high-res for SVG without explicit sizing

    except Exception:
        pass
    return None

def get_homepage_favicon(homepage):
    """
    Fetch the homepage HTML and return the best favicon URL found, or None.
    Priority order: apple-touch-icon, icon ending in png, icon ending in ico, other icon, /favicon.png, /favicon.ico
    """
    try:
        req = urllib.request.Request(homepage, headers=BASE_HEADERS)
        with urllib.request.urlopen(req, timeout=8) as resp:
            chunk = resp.read(32768).decode('utf-8', errors='replace')
    except Exception:
        return None

    from urllib.parse import urljoin

    links = re.findall(
        r'<link\s[^>]*rel=["\"]([^"\"]*)["\"][^>]*href=["\"]([^"\"]*)["\"]'
        r' |<link\s[^>]*href=["\"]([^"\"]*)["\"][^>]*rel=["\"]([^"\"]*)["\"]',
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
            candidates.append((0, url))
        elif 'icon' in rel and href.lower().endswith('.png'):
            candidates.append((1, url))
        elif 'icon' in rel and href.lower().endswith('.ico'):
            candidates.append((2, url))
        elif 'icon' in rel:
            candidates.append((3, url))

    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    from urllib.parse import urlparse
    parsed = urlparse(homepage)
    base = f'{parsed.scheme}://{parsed.netloc}'
    for path in ('/favicon.png', '/favicon.ico'):
        url = base + path
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Tavern/0.1'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200 and int(resp.headers.get('Content-Length', '9999')) > 200:
                    return url
        except Exception:
            continue

    return None

def fetch_readme_images(pkg):
    """Extract absolute image URLs from the project's GitHub README."""
    urls = pkg.get('urls', {})
    stable = urls.get('stable', {}) if isinstance(urls, dict) else {}
    src_url = stable.get('url', '') if isinstance(stable, dict) else ''
    homepage = pkg.get('homepage', '')

    GH_RE = re.compile(r'github\.com/([^/\s"\\]+)/([^/\s"\#?.]+)')

    owner, repo = None, None
    for candidate in (src_url, homepage):
        if not candidate:
            continue
        m = GH_RE.search(candidate)
        if m:
            o = m.group(1)
            r = m.group(2).rstrip('.git')
            if o.lower() in ('releases', 'downloads', 'mirrors', 'raw', 'orgs', 'users'):
                continue
            owner, repo = o, r
            break

    if not owner:
        return []

    text = None
    for readme_name in ('README.md', 'readme.md', 'Readme.md', 'README.rst'):
        raw_url = f'https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{readme_name}'
        try:
            req = urllib.request.Request(raw_url, headers=BASE_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                text = resp.read().decode('utf-8', errors='replace')
            break
        except Exception:
            continue

    if not text:
        return []

    md_images = re.findall(r'!\[[^\]]*\]\(([^)]+)\)', text)
    html_images = re.findall(r'<img[^>]+src=["\']([^"\'>]+)["\']', text, re.IGNORECASE)
    video_tags = re.findall(r'<video[^>]+src=["\']([^"\'>]+)["\']', text, re.IGNORECASE)
    video_source = re.findall(r'<source[^>]+src=["\']([^"\'>]+)["\']', text, re.IGNORECASE)
    
    all_media = md_images + html_images + video_tags + video_source

    base_raw = f'https://raw.githubusercontent.com/{owner}/{repo}/HEAD/'

    absolute = []
    for img in all_media:
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

        low = url.lower()
        if any(skip in low for skip in ('shields.io', 'badge', 'travis-ci', 'codecov',
                                         'appveyor', 'circleci', 'github/workflow',
                                         'actions/workflows', 'buymeacoffee',
                                         'ko-fi', 'opencollective', 'sponsor', 'paypal')):
            continue
        absolute.append(url)

    # Remove duplicates but preserve order
    return list(dict.fromkeys(absolute))

def check_url_validity_and_resolution(url):
    """Check if we can actually download a sensible file from the URL and return its resolution."""
    if url.startswith('data:'):
        return False, None
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 Tavern/0.1'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            # Read 8KB to cover headers of PNG, GIF, JPEG, and a good chunk of SVGs
            data = resp.read(8192)  
            if len(data) > 100:
                res = get_image_metadata_from_bytes(data)
                return True, res
    except Exception:
        pass
    return False, None

def get_assets(pkg):
    name = pkg.get('name', '')
    if isinstance(name, list): name = name[0]
    homepage = pkg.get('homepage', '')

    readme_images = fetch_readme_images(pkg)
    
    potential_icons = []
    potential_screenshots = []

    # 0. Curated Tavern Metadata Repo
    potential_screenshots.append((f'https://raw.githubusercontent.com/hanthor/tavern-metadata/main/screenshots/{name}.jpg', 'Tavern Metadata Repo', 100))
    
    # 1. GitHub Org logic
    if homepage:
        m = re.search(r'github\.com/([^/\s"\\]+)', homepage)
        if m:
            org = m.group(1)
            if org.lower() not in ('releases', 'downloads', 'mirrors', 'raw', 'orgs', 'users'):
                if is_github_org(org):
                     potential_icons.append((f'https://github.com/{org}.png', 'GitHub Org Image', 90))

    # 2. Scrape homepage
    if homepage:
        favicon = get_homepage_favicon(homepage)
        if favicon:
             potential_icons.append((favicon, 'Homepage HTML Favicon', 80))

    # 3. Process README images
    for i, img_url in enumerate(readme_images):
        low_url = img_url.lower()
        if low_url.endswith('.mp4') or low_url.endswith('.webm'):
            potential_screenshots.append((img_url, f'README Video #{i+1}', 95))
        elif low_url.endswith('.gif'):
            potential_screenshots.append((img_url, f'README GIF #{i+1}', 90))
        else:
            # Score will be evaluated based on resolution
            potential_screenshots.append((img_url, f'README Image #{i+1}', 50))
            potential_icons.append((img_url, f'README Image #{i+1}', 50))
            
    # 4. Google S2 / DuckDuckGo Fallback
    if homepage:
         domain = homepage.replace('https://', '').replace('http://', '').split('/')[0]
         potential_icons.append((f'https://www.google.com/s2/favicons?domain={domain}&sz=128', 'Google S2 Favicon', 30))
         potential_icons.append((f"https://icons.duckduckgo.com/ip3/{domain}.ico", 'DuckDuckGo Favicon', 20))

    # Evaluate Icons
    best_icon = None
    best_icon_score = -1

    for url, src, base_score in potential_icons:
        # Blacklist generic github icons
        if 'fluidicon.png' in url.lower() or 'github.githubassets.com' in url.lower():
             continue
             
        valid, res = check_url_validity_and_resolution(url)
        if not valid: continue
        
        score = base_score
        if res:
            w, h = res
            if w > 0 and h > 0:
                aspect_ratio = w / h
                if 0.9 <= aspect_ratio <= 1.1:
                    score += 20  # Boost square icons
                else:
                    score -= 10  # Penalize non-square
                
                if w >= 256:
                    score += 30  # High-res boost
                elif w >= 128:
                    score += 15
                elif w < 64:
                    score -= 10  # Penalize tiny icons
                    
        if score > best_icon_score:
            best_icon_score = score
            best_icon = (url, src, res)
            
    # Evaluate Screenshots
    best_ss = None
    best_ss_score = -1
    
    for url, src, base_score in potential_screenshots:
        if url.lower().endswith('.mp4') or url.lower().endswith('.webm'):
             score = base_score + 50
             if score > best_ss_score:
                 best_ss_score = score
                 best_ss = (url, src, None)
             continue
             
        valid, res = check_url_validity_and_resolution(url)
        if not valid: continue
        
        score = base_score
        
        lower_url = url.lower()
        if lower_url.endswith('.gif'):
             score += 40
             
        # Keyword boosts
        if 'screenshot' in lower_url or 'demo' in lower_url or 'usage' in lower_url:
             score += 40
             
        if res:
            w, h = res
            if w > 0 and h > 0:
                aspect_ratio = w / h
                if aspect_ratio >= 1.2:
                    score += 30  # Boost landscape images for screenshots
                if w >= 600:
                    score += 20  # Boost large images
                if w < 300:
                    score -= 30  # Penalize tiny images
                    
        # Don't pick the exact same image as the icon
        if best_icon and url == best_icon[0]:
            score -= 50
            
        if score > best_ss_score:
            best_ss_score = score
            best_ss = (url, src, res)
            
    return (
        best_icon[0] if best_icon else None, 
        best_icon[1] if best_icon else None, 
        best_icon[2] if best_icon else None,
        best_ss[0] if best_ss else None,
        best_ss[1] if best_ss else None
    )

import concurrent.futures

def process_package(pkg_info):
    pkg_data, ptype = pkg_info
    print(f"  [{ptype}] {pkg_data['name']}")
    icon_url, icon_src, icon_res, ss_url, ss_src = get_assets(pkg_data)
    return {
        'name': pkg_data['name'],
        'type': ptype,
        'icon_url': icon_url,
        'icon_src': icon_src,
        'icon_res': icon_res,
        'ss_url': ss_url,
        'ss_src': ss_src
    }

def main():
    print("Fetching Homebrew API...")
    formulae = fetch_json(FORMULA_API) or []
    casks = fetch_json(CASK_API) or []

    packages_to_process = []

    for f in formulae:
        if f['name'] in TEST_PACKAGES['formula']:
            packages_to_process.append((f, 'Formula'))
            
    for c in casks:
        if c.get('token') in TEST_PACKAGES['cask']:
            c_data = c.copy()
            c_data['name'] = c['token']
            packages_to_process.append((c_data, 'Cask'))

    results = []

    print(f"Processing {len(packages_to_process)} packages in parallel...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_pkg = {executor.submit(process_package, pkg): pkg for pkg in packages_to_process}
        for future in concurrent.futures.as_completed(future_to_pkg):
            try:
                res = future.result()
                results.append(res)
            except Exception as exc:
                print(f"Package generated an exception: {exc}")

    # Sort results to keep report output stable
    results.sort(key=lambda x: (x['type'], x['name']))

    print("Generating report.html...")
    with open('report.html', 'w', encoding='utf-8') as f:
        f.write('''<!DOCTYPE html>
<html>
<head>
<title>Tavern Asset Harness Report</title>
<style>
  body { font-family: sans-serif; background: #fdfdfd; margin: 40px; color: #333; }
  table { border-collapse: collapse; width: 100%; margin-top: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
  th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
  th { background: #eee; }
  img { max-width: 250px; max-height: 250px; border-radius: 8px; }
  video { max-width: 250px; border-radius: 8px; }
  .icon-img { width: 64px; height: 64px; object-fit: contain;}
  .src-label { font-size: 0.8em; color: #666; margin-top: 4px; display: block; }
</style>
</head>
<body>
<h1>Tavern Asset Test Harness Report</h1>
<table>
  <tr>
    <th>Package</th>
    <th>Type</th>
    <th>Icon</th>
    <th>Screenshot / Demo</th>
  </tr>
''')
        for r in results:
            if r['icon_url']:
                res_str = f" [{r['icon_res'][0]}x{r['icon_res'][1]}]" if r.get('icon_res') else " [unknown res]"
                icon_html = f'<img class="icon-img" src="{r["icon_url"]}" alt="Icon"><span class="src-label">{r["icon_src"]}{res_str}</span>'
            else:
                icon_html = '<em>None</em>'
            
            ss_html = '<em>None</em>'
            if r['ss_url']:
                 if r['ss_url'].endswith('.mp4') or 'video' in r['ss_url']:
                      ss_html = f'<video src="{r["ss_url"]}" autoplay loop muted playsinline></video><span class="src-label">{r["ss_src"]}</span>'
                 else:
                      ss_html = f'<img src="{r["ss_url"]}" alt="Screenshot"><span class="src-label">{r["ss_src"]}</span>'
            
            f.write(f'''  <tr>
    <td><strong>{r["name"]}</strong></td>
    <td>{r["type"]}</td>
    <td>{icon_html}</td>
    <td>{ss_html}</td>
  </tr>
''')
        f.write('</table></body></html>\\n')
    print("Done! Open report.html in your browser.")

if __name__ == '__main__':
    main()