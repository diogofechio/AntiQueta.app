"""Gera o executável em dist/.  Uso: pip install pyinstaller && python build.py

Se existir assets/icone.ico (Windows) ou assets/icone.icns (macOS), ele vira o ícone do app.
"""

import os
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).parent
args = [
    str(ROOT / "antiqueta.py"),
    "--name", "AntiQueta.IA",
    "--onefile",
    "--clean",
    "--noconfirm",
    "--add-data", f"{ROOT / 'metaclean' / 'static'}{os.pathsep}metaclean/static",
]
icon = ROOT / "assets" / ("icone.icns" if sys.platform == "darwin" else "icone.ico")
if icon.exists():
    args += ["--icon", str(icon)]

PyInstaller.__main__.run(args)
