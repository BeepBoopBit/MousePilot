import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from mousepilot.server import make_server


class ResponseDisconnectTests(unittest.TestCase):
    def test_disconnect_at_any_response_stage_does_not_replay_action(self):
        for error in (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, TimeoutError):
            for stage in ("send_response", "send_header", "end_headers", "body"):
                with self.subTest(error=error.__name__, stage=stage):
                    desktop = Mock()
                    controller = SimpleNamespace(
                        desktop=desktop, execute=Mock(return_value={"executed": True})
                    )
                    server = make_server(controller, "test-token", port=0)
                    try:
                        handler = server.RequestHandlerClass.__new__(server.RequestHandlerClass)
                        payload = json.dumps({"command": "stop"}).encode()
                        handler.connection = SimpleNamespace(settimeout=lambda seconds: None)
                        handler.headers = {
                            "Authorization": "Bearer test-token",
                            "Content-Length": str(len(payload)),
                        }
                        handler.path = "/"
                        handler.rfile = io.BytesIO(payload)
                        handler.wfile = Mock()
                        for method in ("send_response", "send_header", "end_headers"):
                            setattr(handler, method, Mock())
                        target = handler.wfile.write if stage == "body" else getattr(handler, stage)
                        target.side_effect = error("PRIVATE_DIAGNOSTIC_MUST_NOT_BE_LOGGED")
                        with self.assertLogs("mousepilot_server.audit", level="WARNING") as logs:
                            handler.do_POST()
                        self.assertTrue(handler.close_connection)
                        controller.execute.assert_called_once()
                        self.assertIn("operation=stop response_delivery=failed", logs.output[0])
                        self.assertNotIn("PRIVATE_DIAGNOSTIC", str(logs.output))
                    finally:
                        server.server_close()
