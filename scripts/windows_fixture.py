"""Read-only observation helper for the dedicated Windows test window."""

import json
import subprocess
import time


def read_state(host):
    # Read-only retries tolerate the fixture rewriting its observation file.
    for attempt in range(5):
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                host,
                "powershell",
                "-NoProfile",
                "-Command",
                '[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); Get-Content "$env:USERPROFILE\\mousepilot\\target-state.json" -Raw',
            ],
            capture_output=True,
            timeout=15,
        )
        if result.returncode == 0:
            try:
                return json.loads(result.stdout.decode("utf-8-sig"))
            except ValueError:
                pass
        if attempt == 4:
            raise RuntimeError(
                f"Could not read target state: {result.stderr.decode(errors='replace')}"
            )
        time.sleep(0.1)
