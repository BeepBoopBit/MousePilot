"""Explicit live reset/takeover test using only the dedicated Windows test window.

Requires a v0.4.1+ backend and scripts/start-test-target.ps1 running in ~/mousepilot.
Intentionally revokes the current controller; run only when takeover is authorized.
"""

import argparse
import asyncio
import base64
import json
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from windows_fixture import read_state

from mousepilot.client import connection
from mousepilot.protocol import ControlError


def point(frame, target):
    left, top, right, bottom = frame["desktop_bounds"]
    width, height = frame["image_size"]
    return int((target[0] - left) * width / (right - left)), int(
        (target[1] - top) * height / (bottom - top)
    )


async def run(args):
    output = Path("captures")
    output.mkdir(exist_ok=True)
    checks = []

    async def state_when(predicate):
        deadline = time.monotonic() + 10
        while True:
            try:
                state = await asyncio.to_thread(read_state, args.ssh_host)
            except RuntimeError:
                if time.monotonic() > deadline:
                    raise
                await asyncio.sleep(0.2)
                continue
            if predicate(state):
                return state
            if time.monotonic() > deadline:
                raise AssertionError(f"Fixture observation timed out: {state}")
            await asyncio.sleep(0.1)

    with connection(args.device, args.config, acquire=False) as owner:
        await asyncio.to_thread(owner.execute, {"command": "reset"})
        await asyncio.to_thread(owner.execute, {"command": "resume"})
        old_frame = await asyncio.to_thread(owner.execute, {"command": "screen"})
        before = await state_when(lambda state: not state["left_button_down"])
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
        async with stdio_client(parameters) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert len(tools.tools) == 19

                async def call(name, values=None):
                    result = await session.call_tool(name, values or {})
                    assert not result.isError, (name, result.content)
                    return result

                status = (await call("control_status")).structuredContent
                assert status["active"] and not status["owns_control"]
                blocked = await session.call_tool("current_screen", {})
                assert (
                    blocked.isError and blocked.structuredContent["error"]["code"] == "device_busy"
                )
                checks.append("MCP starts and recovery tools remain available while device is busy")
                x, y = point(old_frame, before["targets"]["drag"])
                dragging = asyncio.create_task(
                    asyncio.to_thread(
                        owner.execute,
                        {
                            "command": "drag",
                            "from_x": x,
                            "from_y": y,
                            "to_x": x + 80,
                            "to_y": y + 20,
                            "frame": old_frame["screenshot_id"],
                            "duration": 5.0,
                        },
                    )
                )
                await state_when(
                    lambda state: (
                        state["left_button_down"]
                        and state["mouse_down_events"] == before["mouse_down_events"] + 1
                    )
                )
                started = time.monotonic()
                reset = await call("reset_control")
                elapsed = time.monotonic() - started
                assert reset.structuredContent["paused"] and reset.structuredContent["owns_control"]
                assert "session" not in reset.structuredContent
                try:
                    await dragging
                    raise AssertionError("Drag completed rather than being interrupted")
                except ControlError as exc:
                    assert exc.code == "paused", exc.code
                after = await state_when(
                    lambda state: (
                        not state["left_button_down"]
                        and state["mouse_up_events"] == before["mouse_up_events"] + 1
                    )
                )
                assert after["mouse_down_events"] == before["mouse_down_events"] + 1
                checks.append("reset interrupts native drag and releases mouse exactly once")
                paused = await session.call_tool(
                    "type_text", {"text": "must not type while paused"}
                )
                assert paused.isError and paused.structuredContent["error"]["code"] == "paused"
                fresh = await call("current_screen")
                try:
                    await asyncio.to_thread(
                        owner.execute, {"command": "type", "text": "revoked client must not type"}
                    )
                    raise AssertionError("Revoked client injected text")
                except ControlError as exc:
                    assert exc.code == "session_expired", exc.code
                owner.close()
                assert (await call("control_status")).structuredContent["owns_control"]
                checks.append("revoked input and stale disconnect cannot affect new owner")
                await call("resume_control")
                stale = await session.call_tool(
                    "move_cursor", {"x": 0, "y": 0, "screenshot_id": old_frame["screenshot_id"]}
                )
                assert stale.isError and stale.structuredContent["error"]["code"] == "stale_frame"
                checks.append(
                    "input stays paused until explicit resume; old screenshot IDs are invalid"
                )
                state = await state_when(lambda state: not state["left_button_down"])
                x, y = point(fresh.structuredContent, state["targets"]["input"])
                await call(
                    "click",
                    {"x": x, "y": y, "screenshot_id": fresh.structuredContent["screenshot_id"]},
                )
                await call("hotkey", {"keys": ["ctrl", "a"]})
                await call("type_text", {"text": "reset recovery"})
                await state_when(lambda state: state["text"] == "reset recovery")
                screenshot = await call("current_screen")
                (output / "control-reset-recovered.png").write_bytes(
                    base64.b64decode(screenshot.content[0].data)
                )
                await call("release_control")
                status = (await call("control_status")).structuredContent
                assert not status["active"] and not status["paused"]
                checks.append(
                    "fresh input works and explicit release frees device without expiry wait"
                )
        report = {
            "passed": True,
            "tools": 19,
            "reset_response_seconds": round(elapsed, 3),
            "checks": checks,
        }
        (output / "control-reset-verification.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="devices.toml")
    parser.add_argument("--device", default="windows")
    parser.add_argument("--ssh-host", default="windows")
    asyncio.run(run(parser.parse_args()))
