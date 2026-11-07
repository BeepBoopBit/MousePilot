import base64
import copy
import io
import unittest

from helpers import FakeDesktop
from PIL import Image

from mousepilot.controller import Controller
from mousepilot.protocol import ControlError


class DisplayTests(unittest.TestCase):
    def setUp(self):
        self.desktop = FakeDesktop()
        self.desktop.displays = [
            {
                "id": "primary",
                "device_name": "DEVICE1",
                "primary": True,
                "scale_percent": 125,
                "bounds": [0, 0, 1920, 1080],
            },
            {
                "id": "DEVICE2",
                "device_name": "DEVICE2",
                "primary": False,
                "scale_percent": 100,
                "bounds": [-1080, -600, 0, 1320],
            },
        ]
        self.desktop.cursor = [-500, 0]
        self.controller = Controller(self.desktop, "test", "test")
        self.aliases = {"main": "DEVICE1", "portrait": "DEVICE2"}

    def test_list_labels_orientation_and_cursor(self):
        displays = self.controller.execute({"command": "displays", "aliases": self.aliases})[
            "displays"
        ]
        self.assertEqual(displays[0]["label"], "main")
        self.assertEqual(displays[0]["resolution"], [1920, 1080])
        self.assertEqual(displays[0]["scale_percent"], 125)
        self.assertEqual(displays[1]["orientation"], "portrait")
        self.assertTrue(displays[1]["contains_cursor"])
        self.assertFalse(displays[0]["contains_cursor"])

    def test_alias_capture_maps_to_negative_origin(self):
        frame = self.controller.execute(
            {"command": "screen", "display_id": "portrait", "width": 540, "aliases": self.aliases}
        )
        self.assertEqual(frame["display_id"], "DEVICE2")
        self.assertEqual(frame["display_label"], "portrait")
        self.controller.execute(
            {"command": "move", "x": 270, "y": 300, "frame": frame["screenshot_id"]}
        )
        self.assertEqual(self.desktop.cursor, [-540, 0])

    def test_overview_layout_is_navigation_only(self):
        result = self.controller.execute({"command": "overview", "aliases": self.aliases})
        image = Image.open(io.BytesIO(base64.b64decode(result["png_base64"])))
        self.assertEqual(image.size, (1600, 1000))
        self.assertFalse(result["actionable"])
        self.assertNotIn("screenshot_id", result)
        self.assertEqual(len(self.controller.frames), 0)
        main, portrait = [d["overview_bounds"] for d in result["displays"]]
        self.assertLess(portrait[0], main[0])
        self.assertLess(portrait[1], main[1])
        self.assertLessEqual(abs(portrait[2] - main[0]), 1)
        for x1, y1, x2, y2 in (main, portrait):
            self.assertTrue(0 <= x1 < x2 <= 1600 and 0 <= y1 < y2 <= 1000)

    def test_disconnected_alias_fails_without_fallback(self):
        self.desktop.displays = self.desktop.displays[:1]
        with self.assertRaisesRegex(ControlError, "unavailable"):
            self.controller.execute(
                {"command": "screen", "display_id": "portrait", "aliases": self.aliases}
            )
        self.assertEqual(self.desktop.actions, [])

    def test_shadowing_alias_rejected(self):
        with self.assertRaisesRegex(ControlError, "shadow"):
            self.controller.execute({"command": "screen", "aliases": {"primary": "DEVICE2"}})

    def test_topology_change_during_overview_rejected(self):
        original = self.desktop.capture

        def capture(bounds):
            image = original(bounds)
            self.desktop.displays = copy.deepcopy(self.desktop.displays)
            self.desktop.displays[0]["scale_percent"] = 150
            return image

        self.desktop.capture = capture
        with self.assertRaisesRegex(ControlError, "configuration changed"):
            self.controller.execute({"command": "overview"})

    def test_overview_available_while_paused(self):
        self.desktop.stopped.set()
        self.assertFalse(self.controller.execute({"command": "overview"})["actionable"])
