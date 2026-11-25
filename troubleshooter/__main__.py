"""Module entry point for ``python -m troubleshooter``."""

import sys
from .gui import main

if __name__ == "__main__":
    sys.exit(main())
