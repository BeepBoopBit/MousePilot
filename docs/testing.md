# Testing MousePilot

## Automated checks

```sh
uv sync --locked
uv run python -m unittest discover -s tests
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv build
```

Run these on Linux, Windows, and macOS. Tests use fake desktop objects and an actual MCP
stdio client with a test backend; they do not inject native input. Passing them
does not establish real Windows compatibility.

For a dependency check, export the locked runtime/build requirements and audit
on Linux, Windows, and macOS so platform-specific packages are included:

```sh
uv export --locked --all-extras --no-dev --no-emit-project --output-file audit-requirements.txt
uv run pip-audit --requirement audit-requirements.txt --disable-pip --no-deps
```

Remove `audit-requirements.txt` afterward; it is a generated file. A successful
audit means no known vulnerabilities were reported by that service at that time,
not that dependencies have no vulnerabilities.

## Native Windows checks

Use a test device or save your work first. Keep local keyboard/mouse access and
know the emergency stop: **Ctrl+Alt+Shift+F11**. Live scripts move input and focus
windows; they are not part of CI and must not run on an unattended real desktop.

The scripts expect the project at `~/mousepilot` on Windows. Configure a private
profile on the controlling machine. Launch only the dedicated test window:

```powershell
.\scripts\start-test-target.ps1
```

From the controlling machine, with working SSH access and the backend running:

```sh
uv run python scripts/verify-windows.py --config devices.toml --device windows --ssh-host windows
uv run python scripts/verify-lifecycle.py --config devices.toml --device windows
```

The native checks cover clicks, Unicode input, shortcuts, zoomed crops, window
focus, horizontal scrolling, cross-monitor dragging, and emergency stop. The
lifecycle script deliberately restarts the packaged backend and drops only its
own SSH tunnel during a five-second drag. It waits for the real 90-second lease
to expire, verifies no replay, then verifies input and a new MCP connection.

Reports/screenshots are generated in `captures/` and must remain private. Results
are device-specific observations. The lifecycle script requires the packaged
executable in `dist/`, so build it first. Restart existing MCP clients afterward.

Cleanup on Windows:

```powershell
Stop-ScheduledTask MousePilotTestTarget
Unregister-ScheduledTask MousePilotTestTarget -Confirm:$false
```

## Supervised lifecycle matrix

Lock/unlock, sleep/wake, reboot/login, unplug/replug, and scaling changes require
a human present to recover the session. Do not automate these transitions from
an unattended agent. For each case, record expected/actual behavior and verify:

- Input fails clearly while the desktop is unavailable; nothing is silently queued.
- Device identity persists and the correct interactive user session is targeted.
- Old screenshots are rejected after a restart or detected display change.
- Held input is released when possible, and ambiguous input is not retried.
- A fresh connection, screenshot, test click, and test text entry work after recovery.

Test these cases on the target device. Simulated tests do not establish
native desktop behavior.

## Explicit reset/takeover verification

With the dedicated target open and the backend running:

```sh
uv run python scripts/verify-reset.py --config devices.toml --device windows --ssh-host windows
```

This deliberately takes over the current controller, starts a drag, initializes
another MCP client while the device is busy, then resets during that drag. It
checks button release, revoked-session rejection, stale observations, explicit
resume, fresh input, and release without lease-expiry delay. It does not lock,
sleep, or reboot Windows. Reports remain in ignored `captures/` files. Only run
when interrupting any existing controller is authorized.


## Native macOS checks

Build/install the app using the README and grant its three privacy permissions.
Keep the desktop logged in and unlocked. On the Mac, run:

```sh
mkdir -p ~/mousepilot/captures
cd ~/mousepilot
uv run python scripts/macos-fixture.py ~/mousepilot/captures/mac-target-state.json
```

With that dedicated window open, run from the controller:

```sh
uv run python scripts/verify-macos.py --config devices.toml --device mac --ssh-host mac
```

This deliberately controls the fixture through MCP and SSH: screen capture,
window focus, clicks, Command chords, Unicode/emoji without Enter, native scroll
and drag, Retina crops, pause/resume, emergency stop, reset, and lease release.
Do not interact with the desktop during the run. Reports are saved only under
ignored `captures/`. It does not test lock/unlock, sleep/wake, reboot, multiple
Mac monitors, different keyboard layouts, Intel builds, notarization, or a clean
Mac installation. An automated fake-backend pass cannot establish these behaviors.


### macOS test notes

Record the app version, macOS version, hardware, and results for each live test.
A passing run applies only to the tested build and device.
Do not use an earlier run as evidence for the current build.

The fixture includes a standard Cocoa Edit menu so Command+A is routed through
the responder chain as it is in normal Mac applications. A custom Cocoa window
without menu key equivalents is not a valid Command shortcut target.

When replacing an ad-hoc signed build, macOS may retain a stale Accessibility
entry whose switch appears enabled while `device_info` reports untrusted. Remove
that entry with the minus button, add `~/Applications/MousePilot.app` again, and
enable it. Restart the same app after approval; do not grant a second `dist` copy.
