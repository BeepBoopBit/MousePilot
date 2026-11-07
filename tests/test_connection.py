import json
import tempfile
import threading
import unittest
from pathlib import Path

from helpers import FakeDesktop

from mousepilot.client import Remote, connection
from mousepilot.controller import Controller
from mousepilot.protocol import ControlError
from mousepilot.server import Lease, make_server


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.token = Path(self.temp.name) / "token"
        self.token.write_text("x" * 64)
        self.desktop = FakeDesktop()
        self.server = make_server(Controller(self.desktop, "test-id", "test"), "x" * 64, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def test_exclusive_control_and_disconnect(self):
        a = Remote(self.url, self.token, "test-id").connect()
        try:
            with self.assertRaisesRegex(ControlError, "Another client"):
                Remote(self.url, self.token, "test-id").connect()
            a.execute({"command": "type", "text": "hello"})
        finally:
            a.close()
        b = Remote(self.url, self.token, "test-id").connect()
        b.close()
        self.assertEqual(self.desktop.actions, [("type", "hello")])

    def test_wrong_identity(self):
        with self.assertRaisesRegex(ControlError, "identity"):
            Remote(self.url, self.token, "other").connect()
        self.assertEqual(self.desktop.actions, [])

    def test_wrong_token(self):
        self.token.write_text("wrong")
        with self.assertRaisesRegex(ControlError, "Invalid device token"):
            Remote(self.url, self.token).connect()

    def test_input_needs_session_stop_does_not(self):
        remote = Remote(self.url, self.token)
        with self.assertRaises(ControlError):
            remote.execute({"command": "type", "text": "hello"})
        remote.execute({"command": "stop"})
        self.assertTrue(self.desktop.stopped.is_set())

    def test_profile_relative_token_and_identity(self):
        config = Path(self.temp.name) / "devices.toml"
        config.write_text(
            f'[devices.test]\nurl = {json.dumps(self.url)}\ntoken_file = "token"\nexpected_device_id = "test-id"\n'
        )
        with connection("test", config=config) as remote:
            self.assertEqual(remote.execute({"command": "info"})["device_id"], "test-id")

    def test_observer_can_stop_while_another_client_owns_control(self):
        owner = Remote(self.url, self.token, "test-id").connect()
        try:
            with connection(url=self.url, token_file=self.token, acquire=False) as observer:
                observer.execute({"command": "stop"})
            self.assertTrue(self.desktop.stopped.is_set())
            with self.assertRaises(ControlError):
                owner.execute({"command": "type", "text": "must not type"})
        finally:
            owner.close()

    def test_non_loopback_rejected(self):
        with self.assertRaises(ValueError):
            Remote("http://example.com", self.token)


class LeaseTests(unittest.TestCase):
    def test_expiry_and_wrong_owner(self):
        now = [0]
        lease = Lease(ttl=10, clock=lambda: now[0])
        a = lease.acquire()
        lease.release("someone-else")
        with self.assertRaises(ControlError):
            lease.acquire()
        now[0] = 11
        b = lease.acquire()
        with self.assertRaises(ControlError):
            lease.check(a)
        lease.check(b)


class NoRetryTests(unittest.TestCase):
    def test_lost_input_response_is_never_retried(self):
        from unittest.mock import Mock
        from urllib.error import URLError

        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "token"
            token.write_text("x" * 64)
            remote = Remote("http://127.0.0.1:8765", token)
            opener = Mock()
            opener.open.side_effect = URLError("connection lost")
            remote.opener = opener
            with self.assertRaisesRegex(ControlError, "inspect state"):
                remote.execute({"command": "type", "text": "hello"})
            self.assertEqual(opener.open.call_count, 1)
