import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from helpers import FakeDesktop

from mousepilot.client import Remote
from mousepilot.controller import Controller
from mousepilot.protocol import ControlError
from mousepilot.server import Lease, make_server


class ResetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.token = Path(self.temp.name) / "token"
        self.token.write_text("x" * 64)
        self.desktop = FakeDesktop()
        self.controller = Controller(self.desktop, "test-id", "test")
        self.lease = Lease()
        self.server = make_server(self.controller, "x" * 64, port=0, lease=self.lease)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.clients = []

    def remote(self, lazy=False, identity="test-id"):
        remote = Remote(self.url, self.token, identity, lazy=lazy)
        self.clients.append(remote)
        return remote

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def test_lazy_start_does_not_reserve_control(self):
        observer = self.remote(lazy=True)
        observer.verify()
        self.assertFalse(observer.execute({"command": "control_status"})["active"])
        owner = self.remote().connect()
        with self.assertRaisesRegex(ControlError, "Another client"):
            observer.execute({"command": "screen"})
        self.assertTrue(owner.execute({"command": "control_status"})["owns_control"])

    def test_reset_revokes_owner_invalidates_observations_and_leaves_paused(self):
        owner = self.remote(lazy=True).connect()
        frame = owner.execute({"command": "screen"})["screenshot_id"]
        window = owner.execute({"command": "windows"})["windows"][0]["window_id"]
        replacement = self.remote(lazy=True)
        result = replacement.execute({"command": "reset"})
        self.assertTrue(result["paused"])
        self.assertTrue(result["owns_control"])
        self.assertNotIn("session", json.dumps(result))
        with self.assertRaises(ControlError) as caught:
            owner.execute({"command": "resume"})
        self.assertEqual(caught.exception.code, "session_expired")
        with self.assertRaises(ControlError) as caught:
            owner.execute({"command": "type", "text": "must not reclaim"})
        self.assertEqual(caught.exception.code, "control_lost")
        self.assertFalse(owner.execute({"command": "control_status"})["owns_control"])
        with self.assertRaises(ControlError):
            replacement.execute({"command": "type", "text": "must remain paused"})
        replacement.execute({"command": "screen"})
        replacement.execute({"command": "resume"})
        for command in [
            {"command": "move", "x": 0, "y": 0, "frame": frame},
            {"command": "focus", "window_id": window},
        ]:
            with self.assertRaises(ControlError):
                replacement.execute(command)
        owner.close()  # Stale disconnect cannot release the new owner.
        self.assertTrue(replacement.execute({"command": "control_status"})["owns_control"])
        replacement.execute({"command": "type", "text": "new owner"})
        self.assertEqual(
            [a for a in self.desktop.actions if a[0] == "type"], [("type", "new owner")]
        )

    def test_reset_interrupts_inflight_drag_before_granting_new_lease(self):
        owner = self.remote().connect()
        frame = owner.execute({"command": "screen"})["screenshot_id"]
        replacement = self.remote(lazy=True)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                owner.execute,
                {
                    "command": "drag",
                    "from_x": 0,
                    "from_y": 0,
                    "to_x": 100,
                    "to_y": 100,
                    "frame": frame,
                },
            )
            self.assertTrue(self.desktop.drag_started.wait(2))
            reset = replacement.execute({"command": "reset"})
            self.assertTrue(reset["paused"])
            with self.assertRaises(ControlError):
                future.result(timeout=2)
        self.assertTrue(self.controller.lock.acquire(blocking=False))
        self.controller.lock.release()

    def test_identity_and_authentication_still_required_for_reset(self):
        owner = self.remote().connect()
        invalid = self.remote(identity="wrong-device")
        with self.assertRaises(ControlError):
            invalid.execute({"command": "reset"})
        invalid = self.remote()
        invalid.token = "wrong"
        with self.assertRaises(ControlError):
            invalid.execute({"command": "reset"})
        self.assertTrue(owner.execute({"command": "control_status"})["owns_control"])

    def test_cleanup_failure_keeps_input_paused_and_no_owner(self):
        owner = self.remote().connect()
        self.desktop.release_all = lambda: (_ for _ in ()).throw(
            ControlError("cleanup_failed", "test failure")
        )
        with self.assertRaises(ControlError):
            self.remote().execute({"command": "reset"})
        self.assertTrue(self.desktop.stopped.is_set())
        self.assertFalse(self.lease.status(None)["active"])
        self.assertFalse(self.lease.status(None)["resetting"])
        with self.assertRaises(ControlError):
            owner.execute({"command": "resume"})

    def test_release_allows_another_client_to_claim_without_reset(self):
        first = self.remote(lazy=True)
        first.execute({"command": "screen"})
        first.execute({"command": "release"})
        second = self.remote().connect()
        first.execute({"command": "release"})  # Does not reset/release somebody else.
        self.assertTrue(second.execute({"command": "control_status"})["owns_control"])

    def test_request_authorization_rechecked_under_controller_lock(self):
        owner = self.remote().connect()
        old_session = owner.session
        # Simulate a request passing the transport check just before reset.
        self.lease.check(old_session)
        replacement = self.remote()
        replacement.execute({"command": "reset"})
        replacement.execute({"command": "resume"})
        with self.assertRaises(ControlError):
            self.controller.execute(
                {"command": "type", "text": "stale queued request"},
                authorize=lambda: self.lease.check(old_session),
            )
        self.assertEqual(self.desktop.actions, [])

    def test_reset_blocks_competing_claims_until_cleanup_finishes(self):
        self.lease.begin_reset()
        with self.assertRaises(ControlError):
            self.lease.acquire()
        with self.assertRaises(ControlError):
            self.lease.begin_reset()
        self.lease.finish_reset(claim=False)
        self.lease.acquire()

    def test_late_heartbeat_failure_does_not_poison_replacement_session(self):
        client = self.remote()
        entered = threading.Event()
        finish = threading.Event()

        def delayed_request(args):
            entered.set()
            finish.wait(2)
            raise ControlError("session_expired", "late old-session response")

        client.request = delayed_request
        client._start_heartbeat(0.03)
        old_thread = client.thread
        self.assertTrue(entered.wait(1))
        client.done.set()
        client._start_heartbeat(60)
        finish.set()
        old_thread.join(timeout=1)
        self.assertFalse(old_thread.is_alive())
        self.assertIsNone(client.failure)
