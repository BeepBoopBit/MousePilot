# llama.cpp WebUI and screenshot images

Use the local HTTP MCP adapter to connect llama.cpp WebUI to MousePilot.
The MCP client must pass screenshot images to a vision-capable model.
If the model receives only text metadata, check the client's image support
and connection settings before you use mouse coordinates.

## Connection

Use the local Streamable HTTP adapter to connect the WebUI directly to
MousePilot. Run the adapter and the native device backend as separate processes.

## Windows setup

Start the native backend normally. Configure a local device profile pointing to
`http://127.0.0.1:8765`, with its backend token and pinned device ID as described
in [configuration](configuration.md).

From the project directory:

```powershell
uv run mousepilot --config .\devices.toml --device windows mcp --transport streamable-http
```

This listens only on `127.0.0.1:8766` and creates
`mousepilot-mcp-token.txt` in the working directory. This is a separate bearer
token for the MCP adapter; keep both tokens private.

For automatic startup in the interactive Windows session:

```powershell
.\scripts\start-mcp-http.ps1 -Config .\devices.toml -Device windows
```

The script registers the `MousePilotMCP` login task and prints the URL and token
file path. It requires the project's synced `.venv`. The normal native backend
startup task must also remain enabled.

In llama.cpp WebUI's MCP server settings, add a direct remote server:

- URL: `http://127.0.0.1:8766/mcp`
- Transport: Streamable HTTP (or automatic HTTP detection).
- Header: `Authorization: Bearer TOKEN_FROM_mousepilot-mcp-token.txt`
- Proxy: off; connect directly from the local browser.

Disable duplicate MousePilot connections so the client uses the intended adapter.
Start a new conversation. Ask the model to capture the screen and describe
a visible object. Do not act on
coordinates until it can describe the actual image.

The default allowed browser origins are `http://localhost:8080` and
`http://127.0.0.1:8080`. For another local port, supply `--http-origin` explicitly.
The adapter requires bearer authentication even on loopback, restricts origins,
and retains the MCP SDK's host validation. It does not expose the desktop on a
LAN address. Use stdio over the existing SSH device profiles for other clients.
