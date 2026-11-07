"""Install the local app as an Aqua-session LaunchAgent and start it at login."""

import json
import os
import plistlib
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener


def main():
    if sys.platform != "darwin":
        raise SystemExit("Run this script on macOS")
    app = Path.home() / "Applications/MousePilot.app/Contents/MacOS/MousePilot"
    if not app.is_file():
        raise SystemExit("Install MousePilot.app in ~/Applications first")
    data = Path.home() / "Library/Application Support/MousePilot"
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    agents = Path.home() / "Library/LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    path = agents / "io.mousepilot.server.plist"
    config = {
        "Label": "io.mousepilot.server",
        "ProgramArguments": [str(app), "--tray", "--data-dir", str(data)],
        "RunAtLoad": True,
        "LimitLoadToSessionType": "Aqua",
        "StandardOutPath": str(data / "launcher.log"),
        "StandardErrorPath": str(data / "launcher-error.log"),
    }
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain + "/io.mousepilot.server"], capture_output=True)
    # Stop only processes whose executable exactly matches this installation.
    listing = subprocess.check_output(["ps", "-axo", "pid=,comm="], text=True)
    for row in listing.splitlines():
        fields = row.strip().split(None, 1)
        if len(fields) == 2 and fields[1] == str(app):
            pid = int(fields[0])
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + 10
            while True:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                if time.monotonic() > deadline:
                    raise SystemExit("MousePilot did not exit; quit it from its menu and retry")
                time.sleep(0.1)
    with path.open("wb") as stream:
        plistlib.dump(config, stream)
    path.chmod(0o600)
    subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + 30
    while True:
        try:
            token = (data / "mousepilot-token.txt").read_text().strip()
            expected = (data / "mousepilot-device-id.txt").read_text().strip()
            request = Request(
                "http://127.0.0.1:8765/",
                data=b'{"command":"info"}',
                headers={"Authorization": "Bearer " + token},
            )
            with opener.open(request, timeout=1) as response:
                info = json.load(response)
            if info.get("device_id") != expected:
                raise SystemExit("Another server owns port 8765; inspect it before retrying")
            break
        except (OSError, ValueError):
            if time.monotonic() >= deadline:
                raise SystemExit("MousePilot did not become ready; inspect launcher-error.log")
            time.sleep(0.25)
    print("MousePilot is ready and installed for this user’s future logins.")


if __name__ == "__main__":
    main()
