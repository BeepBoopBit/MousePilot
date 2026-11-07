import tempfile
import unittest
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.testclient import TestClient

from mousepilot.http_mcp import load_http_token, make_http_app


class HTTPMCPTests(unittest.TestCase):
    def setUp(self):
        self.mcp = FastMCP("http-test")
        self.app = make_http_app(self.mcp, "t" * 64)
        self.headers = {
            "Authorization": "Bearer " + "t" * 64,
            "Accept": "application/json, text/event-stream",
        }

    def test_requires_bearer_even_without_browser_origin(self):
        with TestClient(self.app, base_url="http://127.0.0.1:8766") as client:
            self.assertEqual(client.get("/mcp").status_code, 401)
            self.assertEqual(
                client.post("/mcp", headers={"Authorization": "Bearer wrong"}).status_code, 401
            )

    def test_rejects_untrusted_web_origins_with_valid_token(self):
        with TestClient(self.app, base_url="http://127.0.0.1:8766") as client:
            for origin in ["https://example.com", "http://localhost:9000", "null"]:
                response = client.get("/mcp", headers={**self.headers, "Origin": origin})
                self.assertEqual(response.status_code, 403)

    def test_browser_preflight_and_session_header(self):
        with TestClient(self.app, base_url="http://127.0.0.1:8766") as client:
            response = client.options(
                "/mcp",
                headers={
                    "Origin": "http://localhost:8080",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type,mcp-session-id",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.headers["access-control-allow-origin"], "http://localhost:8080"
            )
            response = client.post(
                "/mcp",
                headers={**self.headers, "Origin": "http://localhost:8080"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("mcp-session-id", response.headers)
            self.assertIn("Mcp-Session-Id", response.headers["access-control-expose-headers"])

    def test_nonlocal_origins_are_not_configurable(self):
        for origin in ["*", "https://example.com", "http://localhost:8080/other"]:
            with self.assertRaises(ValueError):
                make_http_app(self.mcp, "t" * 64, [origin])

    def test_token_persists_without_being_printed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "http-token.txt"
            first = load_http_token(path)
            self.assertEqual(first, load_http_token(path))
            self.assertEqual(len(first), 64)

    def test_real_tool_images_survive_http_transport(self):
        import base64
        import io

        from helpers import FakeDesktop
        from PIL import Image

        from mousepilot.controller import Controller
        from mousepilot.mcp_server import create_mcp

        controller = Controller(FakeDesktop(), "test", "test")

        class Adapter:
            def execute(self, args):
                return controller.execute(args)

        app = make_http_app(create_mcp(Adapter(), "test"), "t" * 64)
        with TestClient(app, base_url="http://127.0.0.1:8766") as client:
            result = client.post(
                "/mcp",
                headers=self.headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                },
            )
            headers = {
                **self.headers,
                "Mcp-Session-Id": result.headers["mcp-session-id"],
                "Mcp-Protocol-Version": "2025-03-26",
            }
            client.post(
                "/mcp",
                headers=headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )

            def tool(name, args, id):
                r = client.post(
                    "/mcp",
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": id,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": args},
                    },
                )
                self.assertEqual(r.status_code, 200)
                data = r.json()["result"]
                self.assertFalse(data.get("isError"))
                return data

            screen = tool("current_screen", {}, 2)
            self.assertEqual(screen["content"][0]["type"], "image")
            with Image.open(io.BytesIO(base64.b64decode(screen["content"][0]["data"]))) as image:
                self.assertEqual(image.size, (1280, 800))
            preview = tool(
                "preview_target",
                {"x": 640, "y": 400, "screenshot_id": screen["structuredContent"]["screenshot_id"]},
                3,
            )
            self.assertEqual(sum(c["type"] == "image" for c in preview["content"]), 2)
