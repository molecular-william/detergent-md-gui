"""Compatibility launcher; use python -m dashboard.cli.screen_candidates."""
from pathlib import Path
import runpy
import sys

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    runpy.run_module('dashboard.cli.screen_candidates', run_name='__main__')
