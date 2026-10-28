"""Ponto de entrada do executável (PyInstaller): dois cliques abrem a interface."""

import sys

from metaclean.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
