# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for package details helper functions (formatting, parsing, typography)."""

import pytest
from loader import load_module

helpers = load_module('src/package_details_helpers.py', 'package_details_helpers')


def test_format_install_count():
    assert helpers.format_install_count(None) is None
    assert helpers.format_install_count(0) is None
    assert helpers.format_install_count(-5) is None
    assert helpers.format_install_count(42) == "42"
    assert helpers.format_install_count(999) == "999"
    assert helpers.format_install_count(1000) == "1.00K"
    assert helpers.format_install_count(150000) == "150.00K"
    assert helpers.format_install_count(1250000) == "1.25M"


def test_extract_readme_preview():
    assert helpers.extract_readme_preview("") == ""
    assert helpers.extract_readme_preview(None) == ""

    markdown_text = """# Header 1
## Header 2
![Badge](https://img.shields.io/badge/test)
---
First line of meaningful text.
* Second bullet point.
> Third quoted line.
Fourth line.
Fifth line.
Sixth line.
Seventh line should be truncated.
"""
    preview = helpers.extract_readme_preview(markdown_text, max_lines=6)
    lines = preview.splitlines()
    assert len(lines) == 6
    assert lines[0] == "First line of meaningful text."
    assert lines[1] == "Second bullet point."
    assert lines[2] == "Third quoted line."
    assert "Seventh line" not in preview


def test_compute_readme_base_uri():
    assert helpers.compute_readme_base_uri(None) is None
    assert helpers.compute_readme_base_uri("") is None
    assert helpers.compute_readme_base_uri("https://gitlab.com/owner/repo") is None
    assert helpers.compute_readme_base_uri("https://github.com/incomplete") is None

    url = "https://github.com/BurntSushi/ripgrep"
    assert helpers.compute_readme_base_uri(url) == "https://raw.githubusercontent.com/BurntSushi/ripgrep/HEAD/"
    assert helpers.compute_readme_base_uri(url + "/") == "https://raw.githubusercontent.com/BurntSushi/ripgrep/HEAD/"


def test_build_readme_html():
    raw_markdown = "**bold text** and `code`"
    html_light = helpers.build_readme_html(raw_markdown, is_dark=False)
    assert "<!doctype html>" in html_light
    assert "bold text" in html_light
    assert "#1c1c1c" in html_light

    html_dark = helpers.build_readme_html(raw_markdown, is_dark=True)
    assert "#e4e4e4" in html_dark


def test_font_helpers():
    class DummyPackage:
        def __init__(self, name, display_name=None):
            self.name = name
            self.display_name = display_name

    pkg1 = DummyPackage(name="font-jetbrains-mono", display_name="JetBrains Mono")
    assert helpers.get_font_family_name(pkg1) == "JetBrains Mono"

    pkg2 = DummyPackage(name="font-fira-code")
    assert helpers.get_font_family_name(pkg2) == "Fira Code"

    samples = helpers.get_font_preview_samples("Fira Code")
    assert len(samples) == 5
    assert samples[0] == ("Fira Code", 32)
    assert samples[3] == (helpers.FONT_PANGRAM, 22)
