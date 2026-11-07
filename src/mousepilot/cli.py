"""Manual control and MCP adapter entry point."""

import argparse
import base64
import json
import sys
from pathlib import Path

from .client import DEFAULT_CONFIG, connection, profiles
from .protocol import ControlError


def main():
    parser = argparse.ArgumentParser(description="Windows/macOS desktop control and MCP adapter")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--device", help="Device name from devices.toml")
    target.add_argument("--url", help="Loopback backend URL through a manually opened SSH tunnel")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--token-file", default="mousepilot-token.txt")
    sub = parser.add_subparsers(dest="command", required=True)
    server = sub.add_parser(
        "serve", help="Run the Windows/macOS backend; equivalent to mousepilot-server"
    )
    server.add_argument("--port", type=int, default=8765)
    server.add_argument("--identity-file", default="mousepilot-device-id.txt")
    server.add_argument("--name")
    server.add_argument("--tray", action="store_true")
    mcp = sub.add_parser("mcp", help="Expose the selected device over MCP")
    mcp.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    mcp.add_argument("--http-port", type=int, default=8766)
    mcp.add_argument("--http-token-file", type=Path, default=Path("mousepilot-mcp-token.txt"))
    mcp.add_argument(
        "--http-origin",
        action="append",
        help="Allowed local browser origin; repeat for multiple origins",
    )
    devices = sub.add_parser("devices")
    devices.add_argument("action", choices=["list"])
    for name in ("info", "displays", "stop", "resume", "control-status", "reset"):
        sub.add_parser(name)
    overview = sub.add_parser("overview", help="Labeled thumbnails arranged in desktop layout")
    overview.add_argument("--width", type=int, default=1600)
    overview.add_argument("--height", type=int, default=1000)
    overview.add_argument("--output", default="captures/overview.png")
    screen = sub.add_parser("screen")
    screen.add_argument("--display-id", default="primary")
    screen.add_argument("--width", type=int, default=1280)
    screen.add_argument("--grid", action="store_true")
    screen.add_argument("--cursor-marker", action="store_true")
    screen.add_argument("--output", default="captures/screen.png")
    window_info = sub.add_parser("window-info", help="Current window position, size and monitors")
    window_info.add_argument("window_id")
    window_capture = sub.add_parser(
        "window-capture", help="Capture the visible focused window region"
    )
    window_capture.add_argument("window_id")
    window_capture.add_argument("--width", type=int, default=1280)
    window_capture.add_argument("--grid", action="store_true")
    window_capture.add_argument("--cursor-marker", action="store_true")
    window_capture.add_argument("--output", default="captures/window.png")
    crop = sub.add_parser("crop", help="Capture a fresh zoomed region of a screenshot")
    for name in ("x", "y", "width", "height"):
        crop.add_argument(name, type=int)
    crop.add_argument("--frame", required=True)
    crop.add_argument("--output-width", type=int, default=1280)
    crop.add_argument("--output", default="captures/crop.png")
    preview = sub.add_parser(
        "preview", help="Mark a target and show a magnified preview without input"
    )
    preview.add_argument("x", type=int)
    preview.add_argument("y", type=int)
    preview.add_argument("--frame", required=True)
    preview.add_argument("--radius", type=int, default=80)
    preview.add_argument("--output", default="captures/preview.png")
    elements = sub.add_parser(
        "elements", help="Windows UI Automation controls in an annotated screenshot"
    )
    elements.add_argument("window_id")
    elements.add_argument("--frame", required=True)
    elements.add_argument("--limit", type=int, default=80)
    elements.add_argument("--output", default="captures/elements.png")
    element_click = sub.add_parser("element-click", help="Revalidate and click an observed element")
    element_click.add_argument("element_id")
    element_click.add_argument("--button", choices=["left", "right", "middle"], default="left")
    element_click.add_argument("--count", type=int, choices=[1, 2], default=1)
    windows = sub.add_parser("windows", help="List visible titled desktop windows")
    windows.add_argument("--title", default="")
    windows.add_argument("--frame")
    focus = sub.add_parser("focus", help="Request and verify foreground focus")
    focus.add_argument("window_id")
    focus.add_argument(
        "--no-input",
        dest="allow_input",
        action="store_false",
        help="Disable Windows click/keyboard activation fallbacks",
    )
    for name in ("move", "click"):
        action = sub.add_parser(name)
        action.add_argument("x", type=int)
        action.add_argument("y", type=int)
        action.add_argument("--frame", required=True)
        action.add_argument("--dry-run", action="store_true")
        if name == "click":
            action.add_argument("--button", choices=["left", "right", "middle"], default="left")
            action.add_argument("--count", type=int, choices=[1, 2], default=1)
    key = sub.add_parser("key", help="Explicit key press; Enter can submit")
    key.add_argument(
        "key",
        choices=[
            "enter",
            "tab",
            "escape",
            "backspace",
            "delete",
            "left",
            "right",
            "up",
            "down",
            "home",
            "end",
            "pageup",
            "pagedown",
            "space",
        ],
    )
    typing = sub.add_parser("type", help="Type into the focused field without Enter")
    typing.add_argument("text")
    hotkey = sub.add_parser("hotkey")
    hotkey.add_argument("keys", nargs="+")
    scroll = sub.add_parser("scroll")
    scroll.add_argument("steps", type=int)
    scroll.add_argument("--axis", choices=["vertical", "horizontal"], default="vertical")
    drag = sub.add_parser("drag")
    for name in ("from_x", "from_y", "to_x", "to_y"):
        drag.add_argument(name, type=int)
    drag.add_argument("--frame", required=True)
    drag.add_argument("--to-frame")
    drag.add_argument("--duration", type=float, default=0.5)
    drag.add_argument("--button", choices=["left", "right", "middle"], default="left")
    args = vars(parser.parse_args())
    try:
        op = args["command"]
        if op == "serve":
            from .server import serve

            serve(
                args["port"], args["token_file"], args["identity_file"], args["name"], args["tray"]
            )
            return
        if op == "devices":
            print(json.dumps(profiles(args["config"]), indent=2))
            return
        if op == "mcp" and not args["device"]:
            raise ValueError("MCP requires --device NAME with a pinned device identity")
        with connection(
            args["device"],
            args["config"],
            args["url"],
            args["token_file"],
            acquire=op not in ("info", "displays", "stop", "mcp", "control-status", "reset"),
            lazy=op == "mcp",
        ) as remote:
            if op == "mcp":
                from .mcp_server import create_mcp

                mcp = create_mcp(remote, args["device"])
                if args["transport"] == "streamable-http":
                    from .http_mcp import serve as serve_http

                    serve_http(mcp, args["http_port"], args["http_token_file"], args["http_origin"])
                else:
                    mcp.run(transport="stdio")
                return
            output = args.get("output")
            request = {
                k: v
                for k, v in args.items()
                if k not in ("device", "config", "url", "token_file", "output")
            }
            if op == "focus" and request.get("allow_input") is True:
                request.pop(
                    "allow_input"
                )  # Preserve default-focus compatibility with older backends.
            if op in ("window-info", "window-capture"):
                request["command"] = op.replace("-", "_")
            if op == "element-click":
                request["command"] = "element_click"
            if op == "control-status":
                request["command"] = "control_status"
            result = remote.execute(request)
            if "preview_png_base64" in result:
                zoom_path = Path(output).with_name(Path(output).stem + "-zoom.png")
                zoom_path.parent.mkdir(parents=True, exist_ok=True)
                zoom_path.write_bytes(base64.b64decode(result.pop("preview_png_base64")))
                result["preview_image_path"] = str(zoom_path)
            if "png_base64" in result:
                path = Path(output)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(base64.b64decode(result.pop("png_base64")))
                path.with_suffix(".json").write_text(json.dumps(result, indent=2))
                result["image_path"] = str(path)
            print(json.dumps(result, indent=2))
    except KeyboardInterrupt:
        pass
    except (ControlError, ValueError, OSError) as exc:
        print(f"Error: {getattr(exc, 'code', 'configuration')}: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
