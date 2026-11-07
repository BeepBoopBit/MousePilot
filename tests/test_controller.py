import copy
import unittest

from helpers import FakeDesktop
from pydantic import ValidationError

from mousepilot.controller import Controller
from mousepilot.protocol import ControlError


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.desktop = FakeDesktop()
        self.now = 0
        self.controller = Controller(self.desktop, "test-id", "test", clock=lambda: self.now)
        self.frame = self.controller.execute({"command": "screen"})["screenshot_id"]

    def test_scaled_click(self):
        self.controller.execute({"command": "click", "x": 640, "y": 400, "frame": self.frame})
        self.assertEqual(self.desktop.actions, [("move", 960, 600), ("click", "left", 1)])

    def test_invalid_points_never_move(self):
        for x in (-1, 1280, True, 2.5):
            with self.assertRaises((ControlError, ValidationError)):
                self.controller.execute({"command": "click", "x": x, "y": 0, "frame": self.frame})
        self.assertEqual(self.desktop.actions, [])

    def test_expired_frame(self):
        self.now = 121
        with self.assertRaisesRegex(ControlError, "expired"):
            self.controller.execute({"command": "move", "x": 0, "y": 0, "frame": self.frame})

    def test_changed_display(self):
        self.desktop.displays = copy.deepcopy(self.desktop.displays)
        self.desktop.displays[0]["bounds"][2] = 1600
        with self.assertRaisesRegex(ControlError, "configuration changed"):
            self.controller.execute({"command": "move", "x": 0, "y": 0, "frame": self.frame})

    def test_stop_blocks_input_but_allows_capture(self):
        self.controller.execute({"command": "stop"})
        with self.assertRaisesRegex(ControlError, "Paused"):
            self.controller.execute({"command": "type", "text": "hello"})
        self.controller.execute({"command": "screen"})
        self.controller.execute({"command": "resume"})
        self.controller.execute({"command": "type", "text": "hello"})
        self.assertEqual(self.desktop.actions, [("type", "hello")])

    def test_text_controls_rejected_before_backend(self):
        with self.assertRaises(ValueError):
            self.controller.execute({"command": "type", "text": "hello\n"})
        self.assertEqual(self.desktop.actions, [])

    def test_unknown_fields_rejected(self):
        with self.assertRaises(ValidationError):
            self.controller.execute({"command": "type", "text": "hello", "enter": True})

    def test_busy_operation_does_not_execute(self):
        self.controller.lock.acquire()
        try:
            with self.assertRaisesRegex(ControlError, "operation is running"):
                self.controller.execute({"command": "type", "text": "hello"})
            self.assertEqual(self.controller.execute({"command": "info"})["device_id"], "test-id")
            self.controller.execute({"command": "stop"})
            self.assertTrue(self.desktop.stopped.is_set())
        finally:
            self.controller.lock.release()
