# SPDX-License-Identifier: GPL-3.0-or-later
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loader import load_module

check_translations = load_module('tools/check-translations.py', 'check_translations')


def setup(tmp_path, monkeypatch, potfiles_lines=(), blueprints=None):
    (tmp_path / 'po').mkdir()
    (tmp_path / 'po' / 'POTFILES.in').write_text('\n'.join(potfiles_lines) + '\n')
    (tmp_path / 'src').mkdir()
    for name, text in (blueprints or {}).items():
        (tmp_path / 'src' / name).write_text(text)
    monkeypatch.setattr(check_translations, 'ROOT', tmp_path)


def test_passes_when_registered_and_translated(tmp_path, monkeypatch, capsys):
    setup(
        tmp_path, monkeypatch,
        potfiles_lines=['src/window.blp'],
        blueprints={'window.blp': 'label: _("Hello");\n'},
    )
    assert check_translations.main() == 0
    assert 'passed' in capsys.readouterr().out


def test_flags_blueprint_missing_from_potfiles(tmp_path, monkeypatch):
    setup(
        tmp_path, monkeypatch,
        potfiles_lines=['# comment', ''],
        blueprints={'window.blp': 'label: _("Hello");\n'},
    )
    assert check_translations.main() == 1


def test_flags_visible_literal_bypassing_gettext(tmp_path, monkeypatch):
    setup(
        tmp_path, monkeypatch,
        potfiles_lines=['src/window.blp'],
        blueprints={'window.blp': 'label: "Hello";\n'},
    )
    assert check_translations.main() == 1


def test_allows_non_visible_property_as_literal(tmp_path, monkeypatch):
    setup(
        tmp_path, monkeypatch,
        potfiles_lines=['src/window.blp'],
        blueprints={'window.blp': 'icon-name: "settings-symbolic";\n'},
    )
    assert check_translations.main() == 0
