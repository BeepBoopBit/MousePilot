"""MCP stdio tools for one explicitly selected device."""

import asyncio
import json
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from pydantic import Field

from .protocol import Button, ControlError, Coordinate, Key


def create_mcp(remote, device_name):
    server = FastMCP(
        name=f"mousepilot-{device_name}",
        instructions=(
            "If device_busy, inspect control_status. Use reset_control only for an explicitly requested takeover; it pauses input and requires a fresh screenshot and explicit resume. Use release_control when finished. Use screen_overview to locate an application across monitors, then current_screen with its display_id or alias. Overview coordinates are not actionable. Control the configured desktop device. Observe with current_screen before acting. "
            "All mouse coordinates are pixels in the returned image, not desktop pixels. Window bounds and action cursor_desktop are desktop coordinates. Window IDs may change on each listing; this does not mean a window reopened. Use get_window_info for current position, size and monitor IDs; focus_window then capture_window gives a simpler actionable window image. Window captures and derived crops/previews reject input after window movement, resizing or lost focus. Never guess controls from window bounds alone. If you cannot see returned images, stop visual actions and report the client image-delivery problem. On Windows use list_elements for numbered accessible controls, then click_element. Otherwise preview_target shows a crosshair and zoom before clicking. "
            "Use its screenshot_id. Screenshots expire after 120 seconds and do not prove the "
            "UI is unchanged. Observe again after navigation and input. type_text never presses "
            "Enter; press_key and hotkey can submit messages. Do not retry input automatically "
            "after a connection or input/backend error; do not try different coordinates to solve a native input error. Emergency stop: Ctrl+Alt+Shift+F11 on Windows; Ctrl+Option+Shift+F11 on macOS. On macOS use cmd for Command shortcuts; device_info reports required permissions."
        ),
    )
    read = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
    )
    # Desktop input can trigger arbitrary app actions; repeating it can add effects.
    write = ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True
    )
    control = ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
    )

    async def call(command, **args):
        try:
            result = await asyncio.to_thread(remote.execute, {"command": command, **args})
            image_data = result.pop("png_base64", None)
            preview_data = result.pop("preview_png_base64", None)
            content = []
            if image_data:
                content.append(ImageContent(type="image", mimeType="image/png", data=image_data))
            if preview_data:
                content.append(
                    TextContent(
                        type="text",
                        text="Magnified target preview follows. Navigation only: do not click using its pixel coordinates.",
                    )
                )
                content.append(ImageContent(type="image", mimeType="image/png", data=preview_data))
            content.append(TextContent(type="text", text=json.dumps(result)))
            return CallToolResult(content=content, structuredContent=result)
        except ControlError as exc:
            error = {"code": exc.code, "message": str(exc)}
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(error))],
                structuredContent={"error": error},
                isError=True,
            )

    @server.tool(annotations=read)
    async def control_status() -> CallToolResult:
        """Inspect whether control is active, whether this client owns it, lease expiry, and pause/reset state. Works while another client owns control."""
        return await call("control_status")

    @server.tool(annotations=write)
    async def reset_control() -> CallToolResult:
        """Explicit takeover: interrupt input, release held keys/buttons, revoke ALL old sessions and observations, and give this client control. Leaves input PAUSED; capture a fresh screen then resume explicitly. Works even when device_busy or this client was revoked."""
        return await call("reset")

    @server.tool(annotations=control)
    async def release_control() -> CallToolResult:
        """Relinquish only this client's lease and stop its heartbeat. Does not revoke another client. An in-flight operation may finish; use reset_control to interrupt input."""
        return await call("release")

    @server.tool(annotations=read)
    async def device_info() -> CallToolResult:
        """Read device identity, display IDs/bounds, cursor, capabilities, and pause state."""
        return await call("info")

    @server.tool(annotations=read)
    async def list_displays() -> CallToolResult:
        """List monitor IDs, aliases, labels, resolution, scaling, layout, and which contains the cursor."""
        return await call("displays")

    @server.tool(annotations=read)
    async def screen_overview(
        width: Annotated[int, Field(ge=400, le=2560)] = 1600,
        height: Annotated[int, Field(ge=300, le=1600)] = 1000,
    ) -> CallToolResult:
        """Show labeled thumbnails in desktop layout. For navigation only: capture a chosen display before clicking."""
        return await call("overview", width=width, height=height)

    @server.tool(annotations=read)
    async def current_screen(
        display_id: str = "primary",
        width: Annotated[int, Field(ge=100, le=8192)] = 1280,
        grid: bool = False,
        cursor_marker: bool = False,
    ) -> CallToolResult:
        """Capture a display ID or configured alias from list_displays. Return PNG and screenshot metadata; mouse coordinates use these image pixels."""
        return await call(
            "screen",
            display_id=display_id,
            width=width,
            grid=grid,
            cursor_marker=cursor_marker,
        )

    @server.tool(annotations=read)
    async def crop_screen(
        screenshot_id: str,
        x: Coordinate,
        y: Coordinate,
        width: Annotated[int, Field(ge=1, le=100000)],
        height: Annotated[int, Field(ge=1, le=100000)],
        output_width: Annotated[int, Field(ge=100, le=4096)] = 1280,
    ) -> CallToolResult:
        """Capture a fresh zoomed region selected in a screenshot's pixels. Returns a new actionable screenshot ID with its own coordinates."""
        return await call(
            "crop",
            frame=screenshot_id,
            x=x,
            y=y,
            width=width,
            height=height,
            output_width=output_width,
        )

    @server.tool(annotations=read)
    async def list_windows(
        title: Annotated[str, Field(max_length=200)] = "", screenshot_id: str | None = None
    ) -> CallToolResult:
        """List windows. bounds/desktop_bounds are DESKTOP units, not click coordinates. Supply screenshot_id for image_bounds in screenshot pixels. IDs are temporary observations; changed IDs do not mean reopened windows."""
        return await call(
            "windows", title=title, **({"frame": screenshot_id} if screenshot_id else {})
        )

    @server.tool(annotations=read)
    async def get_window_info(window_id: str) -> CallToolResult:
        """Get a listed window's current desktop x/y, width/height, monitor IDs, minimized and foreground state. Desktop units are NOT click coordinates; use capture_window next."""
        return await call("window_info", window_id=window_id)

    @server.tool(annotations=read)
    async def capture_window(
        window_id: str,
        width: Annotated[int, Field(ge=100, le=8192)] = 1280,
        grid: bool = False,
        cursor_marker: bool = False,
    ) -> CallToolResult:
        """Capture the visible desktop region of a focused window. Focus it first. Returns actionable window-image pixels; overlapping windows may appear. Moving, resizing, minimizing, closing or losing focus invalidates this screenshot and derived crops/previews. Capture again after changes."""
        return await call(
            "window_capture",
            window_id=window_id,
            width=width,
            grid=grid,
            cursor_marker=cursor_marker,
        )

    @server.tool(annotations=read)
    async def preview_target(
        x: Coordinate,
        y: Coordinate,
        screenshot_id: str,
        radius: Annotated[int, Field(ge=16, le=300)] = 80,
    ) -> CallToolResult:
        """Capture a fresh image, mark the proposed screenshot-pixel target, and show a magnified non-actionable preview. Does not move or click. Inspect the crosshair, then use target_image and the NEW screenshot_id for clicking."""
        return await call("preview", x=x, y=y, frame=screenshot_id, radius=radius)

    @server.tool(annotations=read)
    async def list_elements(
        window_id: str, screenshot_id: str, limit: Annotated[int, Field(ge=1, le=150)] = 80
    ) -> CallToolResult:
        """Windows UI Automation: label visible accessible controls with numbers and element IDs in a fresh screenshot. Focus the window first. No OCR. Choose a named control's element_id for click_element instead of guessing coordinates. Coverage varies by app. If discovery is unavailable or empty, returns a fresh window screenshot with visual click/type guidance. If a desired control is absent from a partial list, visually preview and click it instead; stop if the image cannot identify it."""
        return await call("elements", window_id=window_id, frame=screenshot_id, limit=limit)

    @server.tool(annotations=write)
    async def click_element(
        element_id: str, button: Button = "left", count: Annotated[int, Field(ge=1, le=2)] = 1
    ) -> CallToolResult:
        """Native click on a control from list_elements, bound to its observed screenshot. Rejects expired, moved, covered, disabled, or changed controls and background windows. Observe a fresh screenshot afterward; no UIA Invoke is used."""
        return await call("element_click", element_id=element_id, button=button, count=count)

    @server.tool(annotations=write)
    async def focus_window(window_id: str, allow_input: bool = True) -> CallToolResult:
        """Restore and activate a listed window, verifying foreground focus. On Windows, if the API is denied, may send one click to a verified visible title bar or straight resize border; never client content or caption buttons. If fully covered, may send Alt+Escape once then request this exact window. Set allow_input=false for API-only activation. If focus_denied remains, follow its screenshot guidance instead of looping."""
        return await call(
            "focus", window_id=window_id, **({"allow_input": False} if not allow_input else {})
        )

    @server.tool(annotations=write)
    async def move_cursor(x: Coordinate, y: Coordinate, screenshot_id: str) -> CallToolResult:
        """Move to a screenshot pixel. Does not click."""
        return await call("move", x=x, y=y, frame=screenshot_id)

    @server.tool(annotations=write)
    async def click(
        x: Coordinate,
        y: Coordinate,
        screenshot_id: str,
        button: Button = "left",
        count: Annotated[int, Field(ge=1, le=2)] = 1,
    ) -> CallToolResult:
        """Move and click once or twice at screenshot coordinates. Observe the result afterward."""
        return await call("click", x=x, y=y, frame=screenshot_id, button=button, count=count)

    @server.tool(annotations=write)
    async def scroll(
        steps: Annotated[int, Field(ge=-20, le=20)],
        axis: Literal["vertical", "horizontal"] = "vertical",
    ) -> CallToolResult:
        """Scroll at the cursor in wheel notches. Vertical positive is up; horizontal positive is right."""
        return await call("scroll", steps=steps, axis=axis)

    @server.tool(annotations=write)
    async def type_text(
        text: Annotated[str, Field(min_length=1, max_length=2000)],
    ) -> CallToolResult:
        """Type Unicode text into the focused field without Enter. Rejects controls and line breaks."""
        return await call("type", text=text)

    @server.tool(annotations=write)
    async def press_key(key: Key) -> CallToolResult:
        """Press one key in the focused application. Enter may submit or send; use deliberately."""
        return await call("key", key=key)

    @server.tool(annotations=write)
    async def hotkey(
        keys: Annotated[list[str], Field(min_length=2, max_length=5)],
    ) -> CallToolResult:
        """Press unique modifiers followed by a key, e.g. ["ctrl", "a"]. May trigger app actions."""
        return await call("hotkey", keys=keys)

    @server.tool(annotations=write)
    async def drag(
        from_x: Coordinate,
        from_y: Coordinate,
        to_x: Coordinate,
        to_y: Coordinate,
        screenshot_id: str,
        duration: Annotated[float, Field(ge=0.1, le=5)] = 0.5,
        button: Button = "left",
        to_screenshot_id: str | None = None,
    ) -> CallToolResult:
        """Drag using source screenshot pixels. For cross-monitor/crop dragging, provide to_screenshot_id and destination-image coordinates. Releases the button on interruption."""
        return await call(
            "drag",
            from_x=from_x,
            from_y=from_y,
            to_x=to_x,
            to_y=to_y,
            frame=screenshot_id,
            to_frame=to_screenshot_id,
            duration=duration,
            button=button,
        )

    @server.tool(annotations=control)
    async def stop_control() -> CallToolResult:
        """Pause input, interrupt active input, and release held keys/buttons. Screenshots remain available."""
        return await call("stop")

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True
        )
    )
    async def resume_control() -> CallToolResult:
        """Explicitly re-enable input after an emergency stop. Observe the screen before acting."""
        return await call("resume")

    return server
