"""Windowed entry point. Equivalent to ``python -m notepad_app``."""

from __future__ import annotations

import sys

from notepad_app.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
