import asyncio
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from helpers import FakeDesktop
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mousepilot.client import Remote
from mousepilot.controller import Controller
from mousepilot.mcp_server import create_mcp
from mousepilot.protocol import ControlError
from mousepilot.server import make_server


class MCPTests(unittest.TestCase):
    def test_tool_annotations(self):
        tools = asyncio.run(create_mcp(None, "test").list_tools())
        self.assertEqual(len(tools), 24)
        for tool in tools:
            with self.subTest(tool=tool.name):
                annotations = tool.model_dump(exclude_none=True).get("annotations", {})
                for hint in (
                    "readOnlyHint",
                    "destructiveHint",
                    "idempotentHint",
                    "openWorldHint",
                ):
                    self.assertIs(type(annotations.get(hint)), bool, hint)
                if annotations["readOnlyHint"]:
                    self.assertFalse(annotations["destructiveHint"])
                    self.assertTrue(annotations["idempotentHint"])
                else:
                    self.assertEqual(
                        annotations["idempotentHint"],
                        tool.name in {"release_control", "stop_control", "resume_control"},
                    )

    def test_stdio_tools_images_actions_and_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "token").write_text("x" * 64)
            desktop = FakeDesktop()
            server = make_server(Controller(desktop, "test-id", "test"), "x" * 64, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            (root / "devices.toml").write_text(
                f'[devices.test]\nurl="http://127.0.0.1:{server.server_port}"\n'
                'token_file="token"\nexpected_device_id="test-id"\n[devices.test.display_aliases]\nmain="primary"\n'
            )

            owner = Remote(
                f"http://127.0.0.1:{server.server_port}", root / "token", "test-id", lazy=True
            ).connect()

            async def run():
                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=[
                        "-m",
                        "mousepilot.cli",
                        "--config",
                        str(root / "devices.toml"),
                        "--device",
                        "test",
                        "mcp",
                    ],
                )
                async with stdio_client(parameters) as streams:
                    async with ClientSession(*streams) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        self.assertEqual(
                            {t.name for t in tools.tools},
                            {
                                "control_status",
                                "reset_control",
                                "release_control",
                                "device_info",
                                "current_screen",
                                "list_displays",
                                "crop_screen",
                                "preview_target",
                                "list_elements",
                                "click_element",
                                "list_windows",
                                "get_window_info",
                                "capture_window",
                                "focus_window",
                                "screen_overview",
                                "move_cursor",
                                "click",
                                "scroll",
                                "type_text",
                                "press_key",
                                "hotkey",
                                "drag",
                                "stop_control",
                                "resume_control",
                            },
                        )
                        status = await session.call_tool("control_status", {})
                        self.assertTrue(status.structuredContent["active"])
                        self.assertFalse(status.structuredContent["owns_control"])
                        blocked = await session.call_tool("current_screen", {})
                        self.assertTrue(blocked.isError)
                        self.assertEqual(blocked.structuredContent["error"]["code"], "device_busy")
                        reset = await session.call_tool("reset_control", {})
                        self.assertFalse(reset.isError)
                        self.assertNotIn("session", reset.structuredContent)
                        self.assertTrue(reset.structuredContent["paused"])
                        rejected = await session.call_tool("type_text", {"text": "must not type"})
                        self.assertTrue(rejected.isError)
                        with self.assertRaises(ControlError):
                            owner.execute(
                                {"command": "type", "text": "revoked client must not type"}
                            )
                        with self.assertRaises(ControlError):
                            owner.execute(
                                {"command": "type", "text": "revoked client must not reclaim"}
                            )
                        await session.call_tool("resume_control", {})
                        listing = await session.call_tool("list_displays", {})
                        self.assertEqual(
                            listing.structuredContent["displays"][0]["resolution"], [1920, 1200]
                        )
                        overview = await session.call_tool("screen_overview", {})
                        self.assertFalse(overview.isError)
                        self.assertEqual(overview.content[0].type, "image")
                        self.assertFalse(overview.structuredContent["actionable"])
                        self.assertEqual(overview.structuredContent["displays"][0]["label"], "main")
                        self.assertNotIn("screenshot_id", overview.structuredContent)
                        screen = await session.call_tool("current_screen", {"display_id": "main"})
                        self.assertFalse(screen.isError)
                        self.assertEqual(screen.content[0].type, "image")
                        self.assertEqual(screen.content[0].mimeType, "image/png")
                        frame = screen.structuredContent["screenshot_id"]
                        preview = await session.call_tool(
                            "preview_target", {"x": 1279, "y": 799, "screenshot_id": frame}
                        )
                        self.assertFalse(preview.isError)
                        self.assertEqual(sum(c.type == "image" for c in preview.content), 2)
                        self.assertFalse(preview.structuredContent["preview"]["actionable"])
                        self.assertNotIn("preview_png_base64", preview.structuredContent)

                        cropped = await session.call_tool(
                            "crop_screen",
                            {
                                "screenshot_id": frame,
                                "x": 100,
                                "y": 100,
                                "width": 200,
                                "height": 100,
                            },
                        )
                        self.assertFalse(cropped.isError)
                        self.assertEqual(cropped.content[0].type, "image")
                        self.assertEqual(
                            cropped.structuredContent["desktop_bounds"], [150, 150, 450, 300]
                        )
                        windows = await session.call_tool("list_windows", {"title": "editor"})
                        window = windows.structuredContent["windows"][0]
                        focused = await session.call_tool(
                            "focus_window", {"window_id": window["window_id"]}
                        )
                        self.assertFalse(focused.isError)
                        self.assertTrue(desktop.window["foreground"])
                        geometry = await session.call_tool(
                            "get_window_info", {"window_id": window["window_id"]}
                        )
                        self.assertEqual(geometry.structuredContent["width"], 400)
                        window_image = await session.call_tool(
                            "capture_window", {"window_id": window["window_id"]}
                        )
                        self.assertFalse(window_image.isError)
                        self.assertEqual(window_image.content[0].type, "image")
                        horizontal = await session.call_tool(
                            "scroll", {"steps": 2, "axis": "horizontal"}
                        )
                        self.assertFalse(horizontal.isError)
                        click = await session.call_tool(
                            "click", {"x": 640, "y": 400, "screenshot_id": frame}
                        )
                        self.assertFalse(click.isError)
                        typed = await session.call_tool("type_text", {"text": "hello"})
                        self.assertFalse(typed.structuredContent["enter_pressed"])
                        invalid = await session.call_tool(
                            "click", {"x": 1280, "y": 0, "screenshot_id": frame}
                        )
                        self.assertTrue(invalid.isError)
                        dragging = asyncio.create_task(
                            session.call_tool(
                                "drag",
                                {
                                    "from_x": 100,
                                    "from_y": 100,
                                    "to_x": 200,
                                    "to_y": 200,
                                    "screenshot_id": frame,
                                },
                            )
                        )
                        self.assertTrue(await asyncio.to_thread(desktop.drag_started.wait, 2))
                        await session.call_tool("stop_control", {})
                        interrupted = await dragging
                        self.assertTrue(interrupted.isError)
                        self.assertEqual(interrupted.structuredContent["error"]["code"], "paused")
                        paused = await session.call_tool("type_text", {"text": "must not type"})
                        self.assertTrue(paused.isError)
                        self.assertEqual(paused.structuredContent["error"]["code"], "paused")
                        await session.call_tool("resume_control", {})
                        released = await session.call_tool("release_control", {})
                        self.assertTrue(released.structuredContent["released"])
                        status = await session.call_tool("control_status", {})
                        self.assertFalse(status.structuredContent["active"])
                        return json.loads(typed.content[0].text)

            try:
                result = asyncio.run(run())
                self.assertEqual(result["characters"], 5)
                self.assertIn(("click", "left", 1), desktop.actions)
                self.assertEqual(
                    [a for a in desktop.actions if a[0] == "type"], [("type", "hello")]
                )
            finally:
                owner.close()
                server.shutdown()
                server.server_close()
                thread.join()
