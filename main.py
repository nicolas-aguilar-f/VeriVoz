"""VeriVoz — entry point.

    .venv\\Scripts\\python main.py      (or double-click run.bat)
"""
import sys

from verivoz.ui.app import run

if __name__ == "__main__":
    sys.exit(run())
