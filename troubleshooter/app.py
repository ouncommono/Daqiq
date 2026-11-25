"""Top-level Nuitka entry launcher for zero-Qt Daqiq-Troubleshooter.exe."""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from troubleshooter.win_ui import main

if __name__ == "__main__":
    sys.exit(main())
