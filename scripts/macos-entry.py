"""Packaged macOS app defaults to private persistent storage and menu controls."""

import sys
from pathlib import Path

from mousepilot.server import main

if "--data-dir" not in sys.argv:
    sys.argv += ["--data-dir", str(Path.home() / "Library/Application Support/MousePilot")]
if "--tray" not in sys.argv:
    sys.argv.append("--tray")
main()
