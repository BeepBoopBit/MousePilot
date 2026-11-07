import copy
import unittest

from helpers import FakeDesktop

from mousepilot.controller import Controller
from mousepilot.protocol import ControlError


class PrecisionTests(unittest.TestCase):
    def setUp(self):
        self.desktop = FakeDesktop()
        self.desktop.displays.append(
            {"id": "left", "bounds": [-1920, 0, 0, 1200], "primary": False}
        )
        self.now = 0
        self.controller = Controller(self.desktop, "test", "test", clock=lambda: self.now)
        self.frame = self.controller.execute({"command": "screen"})["screenshot_id"]

    def test_crop_has_own_mapping(self):
        crop = self.controller.execute(
            {
                "command": "crop",
                "frame": self.frame,
                "x": 100,
                "y": 100,
                "width": 200,
                "height": 100,
            }
        )
        self.assertEqual(crop["desktop_bounds"], [150, 150, 450, 300])
        self.assertEqual(crop["image_size"], [1280, 640])
        self.assertEqual(crop["parent_screenshot_id"], self.frame)
        self.controller.execute(
            {"command": "move", "frame": crop["screenshot_id"], "x": 640, "y": 320}
        )
        self.assertEqual(self.desktop.cursor, [300, 225])

    def test_crop_edge_and_invalid_rectangle(self):
        result = self.controller.execute(
            {
                "command": "crop",
                "frame": self.frame,
                "x": 1279,
                "y": 799,
                "width": 1,
                "height": 1,
                "output_width": 100,
            }
        )
        self.assertEqual(result["desktop_bounds"][2:], [1920, 1200])
        with self.assertRaisesRegex(ControlError, "inside"):
            self.controller.execute(
                {
                    "command": "crop",
                    "frame": self.frame,
                    "x": 1279,
                    "y": 799,
                    "width": 2,
                    "height": 1,
                }
            )

    def test_crop_resource_limit_keeps_aspect_ratio(self):
        result = self.controller.execute(
            {
                "command": "crop",
                "frame": self.frame,
                "x": 0,
                "y": 0,
                "width": 1,
                "height": 800,
                "output_width": 4096,
            }
        )
        w, h = result["image_size"]
        self.assertLessEqual(h, 8192)
        self.assertLessEqual(w * h, 16_010_000)

    def test_crop_invalidated_by_layout_change(self):
        self.desktop.displays = copy.deepcopy(self.desktop.displays)
        self.desktop.displays[1]["bounds"][0] = -1600
        with self.assertRaisesRegex(ControlError, "configuration changed"):
            self.controller.execute(
                {
                    "command": "crop",
                    "frame": self.frame,
                    "x": 0,
                    "y": 0,
                    "width": 100,
                    "height": 100,
                }
            )

    def test_cross_monitor_drag_maps_each_endpoint(self):
        destination = self.controller.execute({"command": "screen", "display_id": "left"})
        calls = []
        self.desktop.drag = lambda *args: calls.append(args)
        self.controller.execute(
            {
                "command": "drag",
                "from_x": 100,
                "from_y": 100,
                "to_x": 100,
                "to_y": 100,
                "frame": self.frame,
                "to_frame": destination["screenshot_id"],
            }
        )
        self.assertEqual(calls, [((150, 150), (-1770, 150), 0.5, "left")])

    def test_expired_destination_never_starts_drag(self):
        calls = []
        self.desktop.drag = lambda *args: calls.append(args)
        with self.assertRaises(ControlError):
            self.controller.execute(
                {
                    "command": "drag",
                    "from_x": 1,
                    "from_y": 1,
                    "to_x": 1,
                    "to_y": 1,
                    "frame": self.frame,
                    "to_frame": "missing",
                }
            )
        self.assertFalse(calls)

    def test_window_filter_expiration_and_identity_change(self):
        self.assertEqual(
            self.controller.execute({"command": "windows", "title": "absent"})["windows"], []
        )
        window = self.controller.execute({"command": "windows", "title": "EDITOR"})["windows"][0]
        self.assertNotIn("_identity", window)
        self.controller.execute({"command": "focus", "window_id": window["window_id"]})
        self.assertTrue(self.desktop.window["foreground"])
        self.desktop.window["_identity"] = {"handle": 1, "process_id": 99}
        with self.assertRaises(ControlError):
            self.controller.execute({"command": "focus", "window_id": window["window_id"]})
        self.now = 121
        with self.assertRaisesRegex(ControlError, "expired"):
            self.controller.execute({"command": "focus", "window_id": window["window_id"]})

    def test_pause_allows_observations_but_not_focus(self):
        self.desktop.stopped.set()
        window = self.controller.execute({"command": "windows"})["windows"][0]
        self.controller.execute(
            {"command": "crop", "frame": self.frame, "x": 0, "y": 0, "width": 100, "height": 100}
        )
        with self.assertRaisesRegex(ControlError, "Paused"):
            self.controller.execute({"command": "focus", "window_id": window["window_id"]})
