# SPDX-License-Identifier: GPL-3.0-or-later
"""packaging/AppRun must work when launched through a symlink from another
directory, and must point Tavern at the bundle's own data, locale and libs."""
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_apprun_runs_through_symlink(tmp_path):
    appdir = tmp_path / 'AppDir'
    (appdir / 'usr' / 'bin').mkdir(parents=True)
    shutil.copy(ROOT / 'packaging' / 'AppRun', appdir / 'AppRun')
    tavern = appdir / 'usr' / 'bin' / 'tavern'
    tavern.write_text(
        '#!/bin/sh\n'
        'echo "$TAVERN_DATADIR"\necho "$TAVERN_LOCALEDIR"\n'
        'echo "$LD_LIBRARY_PATH"\necho "$@"\n'
    )
    tavern.chmod(0o755)
    (appdir / 'AppRun').chmod(0o755)

    bindir = tmp_path / 'elsewhere'
    bindir.mkdir()
    link = bindir / 'tavern'
    link.symlink_to(appdir / 'AppRun')

    env = {k: v for k, v in os.environ.items() if k != 'LD_LIBRARY_PATH'}
    out = subprocess.run(
        [str(link), 'arg1'], capture_output=True, text=True, check=True, env=env
    ).stdout.splitlines()

    real = str(appdir.resolve())
    assert out[0] == f'{real}/usr/share/tavern'
    assert out[1] == f'{real}/usr/share/locale'
    assert out[2] == f'{real}/usr/lib'
    assert out[3] == 'arg1'
