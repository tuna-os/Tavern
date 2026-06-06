# test_homebrew_cask.py - Validate the generated Homebrew cask Ruby.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Validate the cask Ruby produced by the update-homebrew-tap workflow.

We extract the cask source from the workflow's heredoc, substitute placeholder
values for the GitHub Actions interpolations, and shell out to whichever Ruby
the host has (Homebrew's portable Ruby or `ruby`) to confirm the file parses.
We also assert structural properties — on_macos + on_linux blocks, a wrapper
that uses --appimage-extract-and-run so the Linux cask works without libfuse2.
"""

import os
import re
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(REPO_ROOT, '.github', 'workflows', 'update-homebrew-tap.yml')


def _extract_cask_source():
    with open(WORKFLOW, 'r', encoding='utf-8') as f:
        text = f.read()
    m = re.search(
        r"cat > Casks/tavern\.rb << 'EOF'\n(?P<body>.*?)\n\s*EOF\n",
        text,
        re.DOTALL,
    )
    assert m, 'cask heredoc not found in workflow'
    body = m.group('body')
    # The workflow indents the heredoc body by 10 spaces; strip a common prefix.
    lines = body.splitlines()
    common = min((len(l) - len(l.lstrip()) for l in lines if l.strip()), default=0)
    body = '\n'.join(l[common:] if l.strip() else '' for l in lines)
    # Substitute placeholder values for ${{ ... }} interpolations.
    body = re.sub(r'\$\{\{[^}]*version[^}]*\}\}', '0.1.0', body)
    body = re.sub(
        r'\$\{\{[^}]*sha256[^}]*\}\}',
        '0' * 64,
        body,
    )
    return body


CASK_SOURCE = _extract_cask_source()


def test_cask_has_macos_and_linux_blocks():
    assert 'on_macos do' in CASK_SOURCE
    assert 'on_linux do' in CASK_SOURCE


def test_macos_cask_uses_app_artifact():
    assert re.search(r'on_macos do.*?app "Tavern\.app".*?end',
                     CASK_SOURCE, re.DOTALL), \
        'macOS block must declare `app "Tavern.app"`'


def test_linux_cask_uses_appimage_extract_and_run():
    """No FUSE2 dependency on the host."""
    assert '--appimage-extract-and-run' in CASK_SOURCE, \
        'Linux wrapper must use --appimage-extract-and-run to avoid libfuse2'


def test_linux_cask_installs_binary_named_tavern():
    assert re.search(r'on_linux do.*?binary "tavern".*?end',
                     CASK_SOURCE, re.DOTALL), \
        'Linux block must install a `tavern` binary symlink'


def test_cask_has_no_external_runtime_depends_on():
    """Neither block should declare a system package dependency — the cask
    must install cleanly out of the box on both macOS and any glibc-based Linux."""
    assert re.search(r'depends_on\s+formula:', CASK_SOURCE) is None
    assert re.search(r'depends_on\s+cask:', CASK_SOURCE) is None
    # `depends_on macos:` (version pin) is acceptable; we only forbid system
    # package deps that would require the user to install something extra.


def test_cask_parses_with_ruby():
    """Compile-check the cask with whichever Ruby is on the box."""
    ruby = (shutil.which('brew')
            and subprocess.run(
                ['brew', '--prefix', 'portable-ruby'],
                capture_output=True, text=True,
            ).stdout.strip())
    if ruby and os.path.isdir(ruby):
        ruby_bin = os.path.join(ruby, 'bin', 'ruby')
    else:
        ruby_bin = shutil.which('ruby')
    if not ruby_bin:
        pytest.skip('No ruby available to compile-check the cask')

    tmpfile = '/tmp/tavern_cask_compile_check.rb'
    with open(tmpfile, 'w', encoding='utf-8') as f:
        f.write(CASK_SOURCE)
    try:
        result = subprocess.run(
            [ruby_bin, '-c', tmpfile],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, \
            f'Cask Ruby failed to parse:\n{result.stderr}'
        assert 'Syntax OK' in result.stdout
    finally:
        os.unlink(tmpfile)
