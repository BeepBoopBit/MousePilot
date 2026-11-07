# MousePilot usage

Control a Windows or macOS desktop from a manual CLI or an MCP client. The Windows
`mousepilot-server` captures screenshots and performs input in the logged-in user's
session. `mousepilot` runs beside the agent, opens an SSH tunnel, verifies the
device identity, and exposes that device through MCP over stdio.

## Windows backend setup

Python development setup (Python 3.11+, Windows 10 1703+ / Windows 11):

1. Copy this project to the Windows machine and install `uv`.
2. Run `uv sync --no-dev` in that directory.
3. In PowerShell **inside the logged-in desktop session**, run:

```powershell
.\.venv\Scripts\mousepilot-server.exe --tray
```

On first launch the server generates `mousepilot-token.txt` and `mousepilot-device-id.txt`
in its working directory. Keep that directory stable so identity survives
restarts. The server listens only on `127.0.0.1:8765`. The desktop must remain
logged in and unlocked. Elevated apps and secure desktops can block input.

To run in the user session now and at subsequent logins, use:

```powershell
.\scripts\start-server.ps1
# If uv cannot locate a usable interpreter:
.\scripts\start-server.ps1 -Python C:\path\to\python.exe
```

This registers the interactive, non-elevated scheduled task `MousePilot` with no
execution time limit. The tray icon shows enabled/paused and connected/idle
status. Its menu offers pause, resume, and quit. The global emergency stop is
**Ctrl+Alt+Shift+F11**. A stop interrupts ongoing input, releases tracked keys and
buttons, and blocks new input until explicitly resumed. Screenshots still work.

To remove autostart:

```powershell
Stop-ScheduledTask MousePilot
Unregister-ScheduledTask MousePilot -Confirm:$false
```

## Standalone Windows executable

Build on Windows:

```powershell
.\scripts\build-windows.ps1
.\dist\mousepilot-server.exe --tray
# Install the executable as the login task:
.\scripts\start-server.ps1 -Executable .\dist\mousepilot-server.exe
```

The executable bundles Python and its dependencies. The Windows build includes a
`--help` smoke test. Build output is not signed. Run only one backend instance
per desktop session; the emergency hotkey is intentionally exclusive.

## Configure the controlling machine

Copy the device token through SSH to a private local file. Read the Windows
device ID from `mousepilot-device-id.txt`, then create a profile:

```toml
[devices.windows]
ssh_host = "windows"
remote_port = 8765
token_file = "windows-token.txt"
expected_device_id = "DEVICE_UUID_FROM_WINDOWS"
```

Relative token paths resolve against the configuration file's directory. The
default config path is `~/.config/mousepilot/devices.toml`; override with `--config`.
Protect the token file, for example with `chmod 600 windows-token.txt` on Linux.
SSH keys and host verification come from your existing SSH setup. The adapter
uses noninteractive SSH, so establish working SSH access before using MCP.

Each invocation opens a temporary local port, forwards it to Windows loopback,
verifies the pinned device ID and protocol version, and closes the tunnel on
exit. A port allocation/startup failure is reported; input is never retried.

For an existing tunnel, use `url = "http://127.0.0.1:18765"` in place of `ssh_host`
and `remote_port`. Direct CLI use with `--url` is also supported for debugging,
but MCP requires a named profile with a pinned identity.

```sh
mousepilot --config devices.toml devices list
```

## MCP client configuration

Use the project's absolute installed command and configuration paths:

```json
{
  "mcpServers": {
    "mousepilot-windows": {
      "command": "/absolute/path/to/mousepilot/.venv/bin/mousepilot",
      "args": ["--config", "/absolute/path/to/devices.toml", "--device", "windows", "mcp"]
    }
  }
}
```

This is a common configuration shape; the exact settings location depends on the
MCP client. See `examples/` for portable templates. Configure separate MCP entries
for separate devices. An adapter is bound to one device for its entire lifetime.

### Tools

| Tool | Behavior |
|---|---|
| `device_info()` | Identity, displays and scaling, cursor, version, capabilities, pause state |
| `list_displays()` | Labels, aliases, monitor numbers, resolution, orientation, scaling, layout, and cursor monitor |
| `screen_overview(width?, height?)` | Navigation-only labeled thumbnails arranged in desktop layout |
| `current_screen(display_id?, width?, grid?, cursor_marker?)` | PNG image plus structured screenshot metadata |
| `crop_screen(screenshot_id, x, y, width, height, output_width?)` | Fresh zoomed capture with a new actionable screenshot ID |
| `list_windows(title?)` | Visible titled desktop windows, bounds, minimized and foreground state |
| `focus_window(window_id)` | Restore and request focus, verified against the foreground window |
| `move_cursor(x, y, screenshot_id)` | Move using returned-image pixels |
| `click(x, y, screenshot_id, button?, count?)` | Left/right/middle; single/double click |
| `scroll(steps, axis?)` | Vertical: positive up. Horizontal: positive right. Maximum 20 wheel notches |
| `type_text(text)` | Unicode text, including emoji; no Enter; maximum 2000 characters |
| `press_key(key)` | Enter, Tab, Escape, Backspace, Delete, arrows, Home, End, Page Up/Down, Space |
| `hotkey(keys)` | Unique modifiers followed by a key, e.g. `["ctrl", "a"]` |
| `drag(from_x, from_y, to_x, to_y, screenshot_id, duration?, button?, to_screenshot_id?)` | Separate source/destination images supported; duration 0.1–5 seconds |
| `stop_control()` | Pause and interrupt input; release held keys/buttons |
| `resume_control()` | Explicitly re-enable input |

Hotkey modifiers: `ctrl`, `alt`, `shift`, `win`. Final key: a named key above,
ASCII letter/digit, or F1–F11. `type_text` rejects control characters and line
breaks. Enter is always a separate action and may send or submit in the focused
application. Key and mouse cleanup is attempted after input errors; a forced
process kill cannot guarantee cleanup.

## Choosing a monitor

Start with `screen_overview()` to locate the application across monitors. It
returns an image arranged in the desktop's desktop coordinate layout, with
monitor labels, primary status, resolution, scaling, and cursor location. Negative
origins and portrait monitors are supported. Captures are sequential, not atomic.

Then call `current_screen(display_id="primary")` or use a display ID from
`list_displays()`. Click only using that single-display screenshot and its ID.
The overview deliberately has no actionable screenshot ID: its labels and image
coordinates cannot be passed to mouse tools. There is no global active monitor.

Configure friendly aliases in the controlling machine's device profile:

```toml
[devices.windows.display_aliases]
main = "primary"
# Additional aliases may target the exact device_name shown by list_displays.
```

`main` follows whichever monitor Windows currently marks primary. To name a
particular display, map the alias to its `device_name` instead. Windows may
reassign display device names after hardware/driver changes; inspect the overview
after reconnecting hardware. Aliases must not shadow native display IDs or device
names. A disconnected or unknown target fails instead of falling back to primary.
Aliases are loaded when the CLI/MCP adapter starts, so restart it after editing.

```sh
mousepilot --device windows displays
mousepilot --device windows overview --output captures/overview.png
mousepilot --device windows screen --display-id main
```

## Precision and window control

`crop_screen` takes a rectangle in an existing screenshot's image pixels and
captures that region **again**, at native resolution, optionally enlarged to
`output_width` (default 1280). It does not crop or magnify old screenshot pixels.
The returned image has its own screenshot ID and desktop bounds, so its local
coordinates work directly with click, move, and drag. The original image may be
outdated; observe the fresh crop before acting. Nested crops are supported.
Output size is bounded to 4096 pixels in width, 8192 in height, and 16 million
pixels, preserving aspect ratio. Enlarging beyond native pixels adds no detail.

`list_windows(title="editor")` filters by case-insensitive title substring. It
returns visible titled top-level desktop windows, including minimized windows.
The list does not include a UI element tree or application controls. Each opaque
window ID expires after 120 seconds. `focus_window` rechecks the window's handle,
process/thread, class and title before restoring/activating it. A changed title
also requires a fresh list. Window IDs are short-lived observations, not durable
identities; Windows can recycle handles.

Windows may deny foreground activation. MousePilot can use a frame click or
keyboard shortcut as a fallback. Set `allow_input=false` to disable these actions.
See [focus a window](targeting.md#focus-a-window) for details.
The tool returns `focus_denied` if activation fails.
Observe the window after focus and select a field before typing.

For cross-monitor dragging, capture both monitors, then pass the source image ID
as `screenshot_id` and the destination image ID as `to_screenshot_id`. Start and
end coordinates each belong to their respective images. Both images must still
be valid. The same mechanism works between crops. Without a destination ID,
both endpoints use the source image as before. Intermediate cursor positions may
be clipped across gaps between monitors; the final cursor position is verified.

Horizontal scrolling uses native Windows horizontal wheel events, not Shift plus
vertical scrolling. Some applications do not handle horizontal wheel input.

```sh
mousepilot --device windows crop 100 100 200 80 --frame FRAME_ID --output-width 1280
mousepilot --device windows windows --title 'editor'
mousepilot --device windows focus WINDOW_ID
mousepilot --device windows scroll 3 --axis horizontal
mousepilot --device windows drag 300 200 100 100 --frame SOURCE_ID --to-frame DESTINATION_ID
```

## Coordinate contract

See [reliable targeting](targeting.md) for target previews, window image bounds,
and Windows accessible element clicks.

Use pixels from the **returned image**, with `(0, 0)` at its top-left. The server
handles resizing and monitor offsets, including negative desktop coordinates.
Default capture is the primary monitor at a maximum width of 1280 pixels. Use
`device_info` to get other display IDs, or increase `width` for small targets.

Each screenshot returns:

- `device_id`, `display_id`, and `screenshot_id`.
- `image_size` and `desktop_bounds`.
- Explicit coordinate spaces and valid screenshot coordinate ranges.
- Cursor positions in desktop and image coordinates, plus `inside_capture`;
  `cursor.image` is null when the cursor is outside the capture.
- Capture time and expiration interval.

Snapshots expire after 120 seconds; only the latest 32 are retained. Changes to
display IDs, bounds, or reported scaling invalidate old screenshots. Restarting
the server invalidates all screenshots. A screenshot ID **does not establish that
the UI is unchanged**. Observe again after navigation, scrolling, or actions.
Screenshot and cursor sampling are not atomic. Grid lines and cursor markers are
optional rendered annotations, not separate overlays on the desktop.

## Manual commands

```sh
mousepilot --device windows screen --output captures/before.png
mousepilot --device windows move 640 400 --frame SCREENSHOT_ID --dry-run
mousepilot --device windows click 640 400 --frame SCREENSHOT_ID
mousepilot --device windows click 640 400 --frame SCREENSHOT_ID --count 2
mousepilot --device windows type 'hello'
mousepilot --device windows key enter
mousepilot --device windows hotkey ctrl a
mousepilot --device windows scroll -3
mousepilot --device windows drag 200 200 400 250 --frame SCREENSHOT_ID
mousepilot --device windows stop
mousepilot --device windows resume
```

Manual screenshots save a PNG and matching JSON sidecar. Without `--url` or
`--device`, desktop commands report a configuration error. For local control,
configure a loopback URL profile; this keeps snapshot state in the persistent
server rather than a short-lived CLI process.

## Control ownership, failures, and logs

Only one client owns the control session. A heartbeat renews its 90-second lease;
normal shutdown releases it immediately. After a crash, a replacement client may
need to wait for expiry. Actions are serialized; concurrent input returns `busy`.
Losing a connection does not undo already injected input or automatically cancel
an operation, which remains bounded. Inspect the screen before issuing input
again. MCP tool errors include a stable error code and a readable message.

`mousepilot-server.log` rotates at 1 MB with two backups. Request logs record timestamp,
operation, HTTP status, and error code. They exclude tokens, session IDs, typed
text, and screenshot data. Startup failures include diagnostic tracebacks.
Use loopback and SSH; exposing the backend directly on a network is unsupported.

## Testing

Use the [testing guide](testing.md) for automated checks and live desktop tests.

## Limits

Native backends support Windows and macOS 14+.
Windows control discovery uses UI Automation. Coverage depends on the application.
macOS control discovery and OCR are not implemented.
MousePilot does not provide unattended login or secure-desktop control.
Input can fail in locked sessions, elevated applications, or permission dialogs.

Use supervised tests for sleep/wake, lock/unlock, monitor changes, mixed scaling,
and different keyboard layouts. See [testing](testing.md).
Windows executables are unsigned. macOS apps use ad-hoc signatures and are
not notarized.

## Resetting control

MCP startup does not reserve a control lease. While another client owns the
lease, use `control_status()` and, only for an intended takeover,
`reset_control()`. Reset stops active input, releases tracked keys/buttons,
revokes old sessions, clears cached screenshots/window IDs, and gives the caller
a fresh lease. Input stays paused. Capture a fresh screen, then call
`resume_control()` explicitly. Call `release_control()` when done.

Revoked clients report lost control and do not automatically reclaim it. Status
and reset remain usable even after this client's lease is lost. Reset requires
a working connection to the backend. `mousepilot --device windows reset`
is the equivalent manual fallback and does not wait for the 90-second lease.


## macOS backend

See the [macOS quick start](../README.md#macos) for app
installation, privacy permissions, and login startup. The same MCP interface and
SSH device profiles apply. Select a separate profile, e.g. `--device mac`.

macOS display/window bounds use global Quartz **points**, with a top-left origin;
Retina screenshots contain more pixels. Mouse tools always take coordinates in
the returned image. The server performs the mapping; do not multiply coordinates
by the display scale yourself. Screenshot metadata includes `coordinate_space`.
Display `pixel_size` and `scale_percent` describe native capture resolution.

`cmd`/`command` means Command, `alt`/`option` means Option, and `ctrl` means Control.
Use `hotkey(["cmd", "a"])` to select text on macOS. Key names use US keyboard
positions; text entry posts Unicode independently of the current keyboard layout.
Horizontal and vertical scrolling use Quartz scroll-wheel events.

Screen capture uses ScreenCaptureKit. Window inspection/focus uses Accessibility;
some apps expose incomplete window information, and macOS may deny activation.
Secure fields, login screens, locked sessions, and permission prompts cannot be
assumed controllable. The emergency listener requires Input Monitoring before
any input is enabled. No privacy database changes or permission bypass is used.

To stop login startup, run `launchctl bootout gui/$(id -u)/io.mousepilot.server`
and remove `~/Library/LaunchAgents/io.mousepilot.server.plist`. Preserve the app's
Application Support directory when updating to retain its token/device identity.
