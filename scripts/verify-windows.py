"""Explicit integration test: run only with scripts/test-target.ps1 open on Windows.

Uses the real MCP stdio transport and SSH profile. Inputs target only the fixture.
"""

import argparse
import asyncio
import base64
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from windows_fixture import read_state

from mousepilot.protocol import VERSION


async def main(args):
    output = Path("captures")
    output.mkdir(exist_ok=True)
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "mousepilot.cli",
            "--config",
            str(Path(args.config).resolve()),
            "--device",
            args.device,
            "mcp",
        ],
    )
    results = []
    async with stdio_client(parameters) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()

            async def call(name, values=None):
                result = await session.call_tool(name, values or {})
                if result.isError:
                    raise AssertionError(f"{name}: {result.content}")
                return result

            async def observed(predicate, label):
                for _ in range(30):
                    state = await asyncio.to_thread(read_state, args.ssh_host)
                    if predicate(state):
                        results.append(label)
                        print(f"Passed: {label}", flush=True)
                        return state
                    await asyncio.sleep(0.1)
                raise AssertionError(f"{label}: {state}")

            async def frame():
                return (await call("current_screen")).structuredContent

            def coords(metadata, target):
                left, top, right, bottom = metadata["desktop_bounds"]
                width, height = metadata["image_size"]
                return [
                    int((target[0] - left) * width / (right - left)),
                    int((target[1] - top) * height / (bottom - top)),
                ]

            async def click_target(name, count=1):
                state = await asyncio.to_thread(read_state, args.ssh_host)
                metadata = await frame()
                x, y = coords(metadata, state["targets"][name])
                await call(
                    "click",
                    {"x": x, "y": y, "screenshot_id": metadata["screenshot_id"], "count": count},
                )

            info = (await call("device_info")).structuredContent
            assert info["version"] == VERSION
            results.append("device identity and automatic SSH tunnel")
            initial = await asyncio.to_thread(read_state, args.ssh_host)
            await click_target("button")
            await observed(lambda state: state["clicks"] == initial["clicks"] + 1, "single click")
            await click_target("input")
            await call("hotkey", {"keys": ["ctrl", "a"]})
            await call("type_text", {"text": "hello watermelon 😀"})
            await observed(
                lambda state: state["text"] == "hello watermelon 😀", "Unicode text and emoji"
            )
            await call("hotkey", {"keys": ["ctrl", "a"]})
            await call("type_text", {"text": "replacement"})
            await observed(
                lambda state: state["text"] == "replacement", "Ctrl+A and replacement text"
            )
            await call("press_key", {"key": "end"})
            await call("press_key", {"key": "backspace"})
            await observed(lambda state: state["text"] == "replacemen", "End and Backspace keys")
            await call("press_key", {"key": "enter"})
            await observed(lambda state: "Return" in state["keys"], "explicit Enter key")
            before = await asyncio.to_thread(read_state, args.ssh_host)
            await click_target("drag", count=2)
            await observed(
                lambda state: state["double_clicks"] > before["double_clicks"], "double click"
            )
            await click_target("scroll")
            await call("scroll", {"steps": -3})
            await observed(lambda state: state["wheel_events"] > before["wheel_events"], "scroll")
            before = await asyncio.to_thread(read_state, args.ssh_host)
            metadata = await frame()
            x, y = coords(metadata, before["targets"]["drag"])
            await call(
                "drag",
                {
                    "from_x": x,
                    "from_y": y,
                    "to_x": x + 80,
                    "to_y": y + 20,
                    "screenshot_id": metadata["screenshot_id"],
                    "duration": 0.4,
                },
            )
            await observed(
                lambda state: state["drag_location"][0] > before["drag_location"][0] + 80,
                "drag and release",
            )
            # A crop is a fresh, independently actionable image.
            state = await asyncio.to_thread(read_state, args.ssh_host)
            metadata = await frame()
            bx, by = coords(metadata, state["targets"]["button"])
            cropped = await call(
                "crop_screen",
                {
                    "screenshot_id": metadata["screenshot_id"],
                    "x": bx - 40,
                    "y": by - 15,
                    "width": 80,
                    "height": 30,
                    "output_width": 800,
                },
            )
            crop_meta = cropped.structuredContent
            assert crop_meta["image_size"][0] == 800
            await call(
                "click",
                {
                    "x": 400,
                    "y": crop_meta["image_size"][1] // 2,
                    "screenshot_id": crop_meta["screenshot_id"],
                },
            )
            await observed(
                lambda current: current["clicks"] == state["clicks"] + 1,
                "fresh zoomed crop and crop-coordinate click",
            )
            (output / "windows-crop-verified.png").write_bytes(
                base64.b64decode(cropped.content[0].data)
            )
            windows = (
                await call("list_windows", {"title": "MousePilot verification target"})
            ).structuredContent["windows"]
            assert len(windows) == 1
            probes = (
                await call("list_windows", {"title": "MousePilot focus probe"})
            ).structuredContent["windows"]
            if probes:
                probe_result = await session.call_tool(
                    "focus_window", {"window_id": probes[0]["window_id"]}
                )
                if probe_result.isError:
                    assert probe_result.structuredContent["error"]["code"] == "focus_denied"
                    results.append("foreground switch explicitly denied by Windows")
                else:
                    assert (
                        await call("list_windows", {"title": "MousePilot focus probe"})
                    ).structuredContent["windows"][0]["foreground"]
                    results.append("foreground switch to separate test window")
            focused = await call("focus_window", {"window_id": windows[0]["window_id"]})
            assert focused.structuredContent["foreground_verified"]
            listing = (
                await call("list_windows", {"title": "MousePilot verification target"})
            ).structuredContent["windows"]
            assert listing[0]["foreground"]
            results.append("window enumeration and verified foreground focus")
            state = await asyncio.to_thread(read_state, args.ssh_host)
            await click_target("horizontal")
            await call("scroll", {"steps": 2, "axis": "horizontal"})
            await observed(
                lambda current: (
                    current["horizontal_wheel_events"] > state["horizontal_wheel_events"]
                ),
                "native horizontal wheel event",
            )
            # Move only the dedicated test window to another monitor, then restore it.
            primary = next(d for d in info["displays"] if d["primary"])
            destination = next(
                (
                    d
                    for d in info["displays"]
                    if not d["primary"] and d["bounds"][0] >= primary["bounds"][2]
                ),
                None,
            )
            if destination is None:
                destination = next(d for d in info["displays"] if not d["primary"])
            original_bounds = listing[0]["bounds"]
            start = [original_bounds[0] + 100, original_bounds[1] + 12]
            db = destination["bounds"]
            end = [db[0] + min(250, (db[2] - db[0]) // 3), db[1] + min(200, (db[3] - db[1]) // 3)]

            async def move_window(source_display, target_display, start, end):
                sf = (
                    await call("current_screen", {"display_id": source_display})
                ).structuredContent
                tf = (
                    await call("current_screen", {"display_id": target_display})
                ).structuredContent
                sx, sy = coords(sf, start)
                tx, ty = coords(tf, end)
                await call(
                    "drag",
                    {
                        "from_x": sx,
                        "from_y": sy,
                        "to_x": tx,
                        "to_y": ty,
                        "screenshot_id": sf["screenshot_id"],
                        "to_screenshot_id": tf["screenshot_id"],
                        "duration": 0.7,
                    },
                )

            await move_window(primary["id"], destination["id"], start, end)
            await asyncio.sleep(0.3)
            moved = (
                await call("list_windows", {"title": "MousePilot verification target"})
            ).structuredContent["windows"][0]
            assert abs(moved["bounds"][0] - original_bounds[0]) > 100
            new_start = [moved["bounds"][0] + 100, moved["bounds"][1] + 12]
            await move_window(destination["id"], primary["id"], new_start, start)
            await asyncio.sleep(0.3)
            restored = (
                await call("list_windows", {"title": "MousePilot verification target"})
            ).structuredContent["windows"][0]
            assert abs(restored["bounds"][0] - original_bounds[0]) < 10
            results.append("cross-monitor title-bar drag and return")
            # Window movement updates fixture target coordinates.
            await asyncio.sleep(0.2)
            # Observe another monitor and exercise its coordinate mapping without clicking.
            for display in info["displays"]:
                capture = await call("current_screen", {"display_id": display["id"], "width": 1280})
                image = capture.content[0]
                assert image.type == "image"
                if not display["primary"]:
                    metadata = capture.structuredContent
                    moved = await call(
                        "move_cursor",
                        {"x": 100, "y": 100, "screenshot_id": metadata["screenshot_id"]},
                    )
                    bounds = metadata["desktop_bounds"]
                    expected = [
                        bounds[0] + int(100 * (bounds[2] - bounds[0]) / metadata["image_size"][0]),
                        bounds[1] + int(100 * (bounds[3] - bounds[1]) / metadata["image_size"][1]),
                    ]
                    assert moved.structuredContent["cursor"] == expected
            results.append(
                f"capture all {len(info['displays'])} monitors and negative-origin movement"
            )
            await call("stop_control")
            stopped = await session.call_tool("type_text", {"text": "must not type"})
            assert stopped.isError and stopped.structuredContent["error"]["code"] == "paused"
            await call("current_screen")
            await call("resume_control")
            results.append("stop blocks input; observations and explicit resume work")
            # This invokes only the server's registered emergency shortcut.
            await call("hotkey", {"keys": ["ctrl", "alt", "shift", "f11"]})
            for _ in range(30):
                info = (await call("device_info")).structuredContent
                if info["paused"]:
                    break
                await asyncio.sleep(0.1)
            assert info["paused"], "Emergency hotkey did not pause input"
            await call("resume_control")
            results.append("Windows global emergency hotkey")
            await click_target("input")
            screenshot = await call("current_screen", {"cursor_marker": True})
            (output / "windows-mcp-verified.png").write_bytes(
                base64.b64decode(screenshot.content[0].data)
            )
    (output / "windows-verification.json").write_text(json.dumps({"passed": results}, indent=2))
    print(json.dumps({"passed": results}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="devices.toml")
    parser.add_argument("--device", default="windows")
    parser.add_argument("--ssh-host", default="windows")
    asyncio.run(main(parser.parse_args()))
