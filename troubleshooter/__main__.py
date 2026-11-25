"""Module entry point for ``python -m troubleshooter``."""

import sys
from .win_ui import main

if __name__ == "__main__":
    sys.exit(main())
