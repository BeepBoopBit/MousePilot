# Configuration

Install and start the device backend using the [README](../README.md#install).
Keep the device logged in and unlocked. For remote control, configure an SSH
alias and verify that `ssh windows` or `ssh mac` works without interactive prompts.
The backend listens only on `127.0.0.1:8765`; MousePilot opens the SSH tunnel.

## Device files

The Windows backend creates `mousepilot-token.txt` and `mousepilot-device-id.txt`
in its working directory. Keep that directory stable between launches.
The packaged Mac app stores these files under
`~/Library/Application Support/MousePilot/`.

Keep both files private and preserve them when upgrading. Copy the token to the
controlling machine over your trusted SSH connection; use the device ID to pin
the profile to the intended computer.

## Configure the controlling machine

On Linux/macOS, from your copy of the project:

```sh
cd /path/to/mousepilot
uv sync --locked
mkdir -p ~/.config/mousepilot
cp examples/devices.toml ~/.config/mousepilot/devices.toml
```

On Windows, from the project folder in PowerShell:

```powershell
uv sync --locked
New-Item -ItemType Directory -Force "$HOME/.config/mousepilot" | Out-Null
Copy-Item examples/devices.toml "$HOME/.config/mousepilot/devices.toml"
```


Copy the generated device token to a private file on this machine through your
trusted connection. Edit the profile with your SSH alias, token path, and the
exact ID from `mousepilot-device-id.txt`:

```toml
[devices.windows]
ssh_host = "windows"
remote_port = 8765
token_file = "windows-token.txt"
expected_device_id = "DEVICE_UUID_FROM_WINDOWS"

[devices.windows.display_aliases]
main = "primary"
```

Relative token paths resolve against the profile file's directory. Use file
permissions appropriate for your OS; for example, `chmod 600 windows-token.txt`
on Linux/macOS, or a user-restricted NTFS ACL on Windows. A token grants desktop
control, not merely read access. Never commit it or paste it into an issue.

Check the connection:

```sh
uv run mousepilot --device windows info
uv run mousepilot --device windows overview
```

The adapter opens its own SSH tunnel, checks the pinned device identity, and
closes the tunnel when it exits. It uses your existing SSH keys and host-key
verification. No publicly exposed backend port is needed.

## Connect an MCP client

For llama.cpp WebUI image forwarding, see [local HTTP setup](llama-cpp.md).
For coordinate and control discovery tools, see [reliable targeting](targeting.md).


Use the absolute installed command and profile paths:

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

On Windows, the command is `.venv\Scripts\mousepilot.exe` under the project
folder. Client configuration locations and formats differ. Portable JSON and
Codex TOML examples are in [examples/](../examples/). Restart the client after
adding the server. Configure one MCP instance per device.

## Add a Mac or a second device

Add a separate profile for each device:

```toml
[devices.mac]
ssh_host = "mac"
remote_port = 8765
token_file = "mac-token.txt"
expected_device_id = "DEVICE_UUID_FROM_MAC"

[devices.mac.display_aliases]
main = "primary"
```

Use `--device mac` in the CLI or MCP arguments. Add another MCP entry named
`mousepilot-mac` alongside `mousepilot-windows`; each instance controls one device.
See [the profiles example](../examples/devices.toml) and
[the Codex configuration example](../examples/codex-config.toml).

## macOS permissions

The installed app is `~/Applications/MousePilot.app`, separate from the system
`/Applications` folder. Open its menu bar item → **Grant permissions…** and enable
**Accessibility**, **Input Monitoring**, and **Screen & System Audio Recording**
in System Settings → Privacy & Security. Older macOS versions call the last
permission Screen Recording. Restart the same app if requested.

`device_info` reports each permission. Input stays blocked until Accessibility
and Input Monitoring are granted and the emergency hotkey listener is ready.
If Accessibility is enabled in Settings but reports untrusted, remove its stale
entry with **−**, add the installed app again, and enable it. Ad-hoc signed
rebuilds may require fresh approval; avoid granting a separate copy in `dist`.

The app is built for the build machine's CPU architecture, ad-hoc signed, and
not Developer ID signed or notarized. For distribution steps, see [releasing](releasing.md).
A source backend can run with:

```sh
uv run mousepilot-server --tray --data-dir "$HOME/Library/Application Support/MousePilot"
```

Source execution may use Python or the terminal as its privacy identity.

## Start at login

On Windows, from the project directory:

```powershell
.\scripts\start-server.ps1
```

For a packaged Windows executable:

```powershell
.\scripts\start-server.ps1 -Executable .\dist\mousepilot-server.exe
```

On macOS, after installing the app:

```sh
uv run python scripts/start-server-macos.py
```

These run the backend in the logged-in user's desktop session. A Windows backend
launched directly from an SSH shell does not replace an interactive scheduled task.

## Recovering a busy device

An MCP adapter starts without claiming the desktop, so recovery tools remain
available even while another client owns control. The first capture/input tool
claims a lease; `device_info`, `list_displays`, `control_status`, and `stop_control`
work without one.

When you explicitly want to take over a busy/stale connection:

1. Call `control_status()` to check ownership and pause state.
2. Call `reset_control()` to interrupt input, release tracked keys/buttons, revoke
   the old session, and invalidate all old screenshot/window IDs. This client gets
   a fresh lease; **input remains paused**.
3. Call `current_screen()` for a fresh observation, then `resume_control()` when
   ready to operate.
4. Call `release_control()` when finished so another client can take control
   without waiting for lease expiry.

Reset intentionally interrupts another controller. It requires the device token
and pinned identity. A revoked client cannot silently reclaim the desktop; it
must explicitly recover. `release_control` only releases this client's lease and
an already-running operation may finish. Use reset to interrupt active input.

Manual fallback (also works when another MCP client owns the device):

```sh
uv run mousepilot --device windows control-status
uv run mousepilot --device windows reset
uv run mousepilot --device windows screen
uv run mousepilot --device windows resume
```

The CLI releases its temporary lease when it exits; an MCP reset keeps the new
lease until release or shutdown. These tools reset control state.
They cannot restart a stopped backend or repair a broken SSH connection.
Restart the MCP client after an upgrade to reload tools.

## More usage

See [usage](usage.md) for monitor aliases, crops, tool arguments, logs, and removal;
[testing](testing.md) for validation; and [releasing](releasing.md) for package builds.
