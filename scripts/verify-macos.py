"""Native MCP checks. Run only with macos-fixture.py open on the selected Mac."""

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def read_state(host):
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        host,
        "cat ~/mousepilot/captures/mac-target-state.json",
    ]
    return json.loads(subprocess.check_output(command, text=True, timeout=10))


async def main(args):
    output = Path("captures")
    output.mkdir(exist_ok=True)
    passed = []
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

            async def call(name, values=None, error=None):
                result = await session.call_tool(name, values or {})
                data = result.structuredContent
                if error:
                    assert result.isError and data["error"]["code"] == error, result
                else:
                    assert not result.isError, result
                return data

            async def observed(predicate, label):
                for _ in range(30):
                    state = await asyncio.to_thread(read_state, args.ssh_host)
                    if predicate(state):
                        passed.append(label)
                        print("Passed:", label, flush=True)
                        return state
                    await asyncio.sleep(0.1)
                raise AssertionError(f"{label}: {state}")

            def point(frame, target):
                left, top, right, bottom = frame["desktop_bounds"]
                width, height = frame["image_size"]
                return [
                    round((target[0] - left) * width / (right - left)),
                    round((target[1] - top) * height / (bottom - top)),
                ]

            async def frame():
                return await call("current_screen")

            async def click(target):
                state = await asyncio.to_thread(read_state, args.ssh_host)
                image = await frame()
                x, y = point(image, state["targets"][target])
                await call("click", dict(x=x, y=y, screenshot_id=image["screenshot_id"]))
                return image

            info = await call("device_info")
            assert info["platform"] == "macos" and all(info["permissions"].values()), info
            image = await frame()
            assert (
                image["coordinate_space"] == "screenshot_pixels"
                and image["desktop_coordinate_space"] == "desktop-points"
            )
            # Save a screenshot from an explicit separate CLI capture when desired; MCP
            # puts the image in content blocks rather than structuredContent.
            passed.append("identity, permissions, Retina screenshot through MCP and SSH")
            windows = await call("list_windows", {"title": "MousePilot macOS test target"})
            assert len(windows["windows"]) == 1, windows
            await call("focus_window", {"window_id": windows["windows"][0]["window_id"]})
            passed.append("Accessibility window enumeration and verified focus")
            initial = await asyncio.to_thread(read_state, args.ssh_host)
            await click("button")
            await observed(lambda s: s["clicks"] == initial["clicks"] + 1, "native click")
            await click("input")
            await call("hotkey", {"keys": ["cmd", "a"]})
            await call("type_text", {"text": "hello watermelon 😀"})
            await observed(
                lambda s: s["text"] == "hello watermelon 😀" and s["submits"] == initial["submits"],
                "Unicode and emoji without Enter",
            )
            await call("hotkey", {"keys": ["cmd", "a"]})
            await call("type_text", {"text": "replacement"})
            await call("press_key", {"key": "backspace"})
            await observed(lambda s: s["text"] == "replacemen", "Command chord and Backspace")
            await click("drag")
            before = await asyncio.to_thread(read_state, args.ssh_host)
            await call("scroll", {"steps": -3})
            await observed(lambda s: s["vertical"] != before["vertical"], "vertical scroll")
            await call("scroll", {"steps": 3, "axis": "horizontal"})
            await observed(lambda s: s["horizontal"] != before["horizontal"], "horizontal scroll")
            image = await frame()
            start, end = [point(image, before["targets"][key]) for key in ("drag", "drag_end")]
            await call(
                "drag",
                dict(
                    from_x=start[0],
                    from_y=start[1],
                    to_x=end[0],
                    to_y=end[1],
                    screenshot_id=image["screenshot_id"],
                    duration=0.3,
                ),
            )
            await observed(lambda s: s["drags"] > before["drags"], "native drag and release")
            image = await frame()
            state = await asyncio.to_thread(read_state, args.ssh_host)
            x, y = point(image, state["targets"]["button"])
            crop = await call(
                "crop_screen",
                dict(
                    screenshot_id=image["screenshot_id"],
                    x=x - 30,
                    y=y - 20,
                    width=60,
                    height=40,
                    output_width=600,
                ),
            )
            await call(
                "click",
                dict(
                    x=crop["image_size"][0] // 2,
                    y=crop["image_size"][1] // 2,
                    screenshot_id=crop["screenshot_id"],
                ),
            )
            await observed(
                lambda s: s["clicks"] == initial["clicks"] + 2,
                "fresh Retina crop and coordinate mapping",
            )
            await call("screen_overview")
            passed.append("monitor overview")
            await call("stop_control")
            await call("press_key", {"key": "space"}, error="paused")
            await call("resume_control")
            passed.append("pause blocks input and explicit resume")
            await call("hotkey", {"keys": ["ctrl", "alt", "shift", "f11"]})
            for _ in range(20):
                if (await call("device_info"))["paused"]:
                    break
                await asyncio.sleep(0.1)
            else:
                raise AssertionError("Emergency shortcut did not pause input")
            await call("resume_control")
            passed.append("emergency shortcut event tap")
            reset = await call("reset_control")
            assert reset["paused"]
            await call("resume_control")
            await call(
                "move_cursor",
                dict(x=0, y=0, screenshot_id=image["screenshot_id"]),
                error="stale_frame",
            )
            await frame()
            passed.append("reset pauses and invalidates observations")
            await call("release_control")
            status = await call("control_status")
            assert not status["owns_control"]
            passed.append("lease release")
    (output / "mac-native-results.json").write_text(json.dumps({"passed": passed}, indent=2) + "\n")
    print(f"{len(passed)} native checks passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="devices.toml")
    parser.add_argument("--device", default="mac")
    parser.add_argument("--ssh-host", default="mac")
    asyncio.run(main(parser.parse_args()))
