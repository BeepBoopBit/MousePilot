"""Write public native package metadata. Do not include local paths."""

import argparse
import json
import platform
import sys
from pathlib import Path

from dev import version

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(
    json.dumps(
        {
            "project": "mousepilot",
            "version": version(),
            "platform": sys.platform,
            "architecture": platform.machine(),
        },
        indent=2,
    )
    + "\n"
)
