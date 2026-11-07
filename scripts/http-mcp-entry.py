"""Quiet Windows launcher with private local logs for the HTTP MCP adapter."""

import argparse
import sys
from pathlib import Path

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--log-file", type=Path, required=True)
args, rest = parser.parse_known_args()
args.log_file.parent.mkdir(parents=True, exist_ok=True)
sys.stdout = sys.stderr = args.log_file.open("a", encoding="utf-8", buffering=1)
sys.argv = [sys.argv[0], *rest]
from mousepilot.cli import main  # noqa: E402

main()
