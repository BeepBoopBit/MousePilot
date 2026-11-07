import base64
import io
import json
import unittest
from unittest.mock import Mock

from helpers import FakeDesktop
from PIL import Image

from mousepilot.controller import Controller
from mousepilot.protocol import ControlError


class AccessibleDesktop(FakeDesktop):
    def __init__(self):
        super().__init__()
        self.window["foreground"] = True
        self.items = [
            {
                "name": "Close",
                "role": "Button",
                "bounds": [450, 110, 490, 140],
                "_identity": {"runtime_id": [1, 2], "bounds": [450, 110, 490, 140]},
            }
        ]
        self.validate_element = Mock()
        self.validate_element_window = Mock()

    def list_elements(self, window, limit):
        return {"elements": self.items[:limit], "truncated": False}


class TargetingTests(unittest.TestCase):
    def setUp(self):
        self.desktop = AccessibleDesktop()
        self.now = 0
        self.controller = Controller(self.desktop, "test", "test", clock=lambda: self.now)
        self.image = self.controller.execute({"command": "screen"})
        self.frame = self.image["screenshot_id"]

    def discover(self):
        window = self.controller.execute({"command": "windows"})["windows"][0]
        return self.controller.execute(
            {"command": "elements", "window_id": window["window_id"], "frame": self.frame}
        )

    def test_empty_discovery_returns_window_image_and_visual_guidance(self):
        self.desktop.items = []
        result = self.discover()
        self.assertEqual(result["interaction_mode"], "visual")
        self.assertEqual(result["accessibility_status"], "no_controls")
        self.assertEqual(result["elements"], [])
        self.assertIn("png_base64", result)
        self.assertEqual(result["desktop_bounds"], [100, 100, 500, 500])
        self.assertIn("type_text", result["next_step"])
        self.assertIn("preview_target", result["next_step"])
        self.assertFalse(self.desktop.actions)

    def test_visual_fallback_handles_window_images_smaller_than_minimum_width_option(self):
        self.desktop.items = []
        self.desktop.window["bounds"] = [100, 100, 140, 140]
        window = self.controller.execute({"command": "windows"})["windows"][0]
        frame = self.controller.execute(
            {"command": "window_capture", "window_id": window["window_id"]}
        )
        result = self.controller.execute(
            {
                "command": "elements",
                "window_id": window["window_id"],
                "frame": frame["screenshot_id"],
            }
        )
        self.assertEqual(result["image_size"], [40, 40])
        self.assertEqual(result["interaction_mode"], "visual")
        self.assertFalse(self.desktop.actions)

    def test_provider_failure_has_visual_fallback_but_focus_errors_do_not(self):
        for code in ("accessibility_unavailable", "accessibility_timeout"):
            with self.subTest(code=code):
                self.desktop.list_elements = Mock(
                    side_effect=ControlError(code, "provider failure")
                )
                result = self.discover()
                self.assertEqual(result["fallback_reason"], code)
                self.assertEqual(result["accessibility_status"], "unavailable")
                self.assertIn("png_base64", result)
        self.desktop.list_elements = Mock(
            side_effect=ControlError("window_not_foreground", "focus first")
        )
        with self.assertRaises(ControlError):
            self.discover()
        self.assertFalse(self.desktop.actions)

    def test_visual_fallback_requires_foreground_window(self):
        self.desktop.items = []
        self.desktop.window["foreground"] = False
        with self.assertRaises(ControlError):
            self.discover()
        self.assertFalse(self.desktop.actions)

    def test_partial_discovery_describes_missing_field_fallback(self):
        result = self.discover()
        self.assertEqual(result["accessibility_status"], "available")
        self.assertIn("partial", result["coverage_note"])
        self.assertIn("type_text", result["next_step"])
        self.assertTrue(result["elements"])
        self.assertFalse(self.desktop.actions)

    def test_specific_out_of_bounds_error_has_limits_and_never_moves(self):
        for x, y in [(1570, 230), (-1, 0), (0, 800)]:
            with self.assertRaises(ControlError) as caught:
                self.controller.execute({"command": "click", "frame": self.frame, "x": x, "y": y})
            self.assertEqual(caught.exception.code, "out_of_bounds")
            self.assertIn("1280x800", str(caught.exception))
            self.assertIn("No input", str(caught.exception))
        self.assertFalse(self.desktop.actions)

    def test_cursor_outside_capture_is_null_and_spaces_are_explicit(self):
        self.desktop.cursor = [2999, 426]
        result = self.controller.execute({"command": "screen"})
        self.assertIsNone(result["cursor"]["image"])
        self.assertFalse(result["cursor"]["inside_capture"])
        self.assertEqual(result["coordinate_space"], "screenshot_pixels")
        self.assertEqual(result["valid_coordinates"], {"x": [0, 1279], "y": [0, 799]})
        result = self.controller.execute(
            {"command": "click", "frame": self.frame, "x": 1047, "y": 153}
        )
        self.assertEqual(result["cursor_desktop"], [1570, 229])
        self.assertEqual(result["target_image"], [1047, 153])
        self.assertEqual(result["cursor_image"], [1047, 153])
        self.assertEqual(result["input_coordinate_space"], "screenshot_pixels")
        self.assertFalse(result["outcome_verified"])

    def test_windows_supply_image_bounds_only_for_requested_frame(self):
        result = self.controller.execute({"command": "windows", "frame": self.frame})
        window = result["windows"][0]
        self.assertEqual(window["image_bounds"], [66, 66, 334, 334])
        self.assertEqual(window["desktop_bounds"], window["bounds"])
        self.assertIn("does not indicate", result["window_id_note"])

    def test_preview_is_fresh_observation_no_input_and_zoom_is_nonactionable(self):
        self.desktop.stopped.set()
        self.desktop.capture = lambda bounds: Image.new("RGB", (1920, 1200), "blue")
        result = self.controller.execute(
            {"command": "preview", "frame": self.frame, "x": 1279, "y": 799}
        )
        self.assertNotEqual(result["screenshot_id"], self.frame)
        self.assertEqual(result["parent_screenshot_id"], self.frame)
        self.assertFalse(result["pointer_moved"])
        self.assertFalse(result["clicked"])
        self.assertFalse(result["preview"]["actionable"])
        self.assertEqual(result["target_desktop"], [1918, 1198])
        for key in ["png_base64", "preview_png_base64"]:
            with Image.open(io.BytesIO(base64.b64decode(result[key]))) as im:
                im.load()
                self.assertEqual(im.getpixel((0, 0)), (0, 0, 255))
        self.assertFalse(self.desktop.actions)

    def test_element_click_uses_bound_frame_and_revalidates_before_input(self):
        result = self.discover()
        row = result["elements"][0]
        self.assertEqual(row["label"], 1)
        self.assertEqual(row["name"], "Close")
        self.assertNotIn("runtime_id", json.dumps(row))
        clicked = self.controller.execute(
            {"command": "element_click", "element_id": row["element_id"]}
        )
        self.desktop.validate_element.assert_called_once()
        self.assertEqual(self.desktop.actions[-1], ("click", "left", 1))
        self.assertEqual(clicked["screenshot_id"], result["screenshot_id"])
        self.assertFalse(clicked["outcome_verified"])

    def test_changed_or_covered_control_never_receives_input(self):
        row = self.discover()["elements"][0]
        self.desktop.validate_element.side_effect = ControlError(
            "accessibility_unavailable", "Control changed"
        )
        with self.assertRaises(ControlError):
            self.controller.execute({"command": "element_click", "element_id": row["element_id"]})
        self.assertFalse(self.desktop.actions)

    def test_paused_element_click_and_expired_elements_never_inject(self):
        row = self.discover()["elements"][0]
        self.desktop.stopped.set()
        with self.assertRaises(ControlError):
            self.controller.execute({"command": "element_click", "element_id": row["element_id"]})
        self.desktop.stopped.clear()
        self.now = 121
        with self.assertRaises(ControlError) as caught:
            self.controller.execute({"command": "element_click", "element_id": row["element_id"]})
        self.assertEqual(caught.exception.code, "stale_element")
        self.assertFalse(self.desktop.actions)

    def test_reset_invalidates_elements(self):
        row = self.discover()["elements"][0]
        self.controller.reset_control()
        self.desktop.stopped.clear()
        with self.assertRaises(ControlError) as caught:
            self.controller.execute({"command": "element_click", "element_id": row["element_id"]})
        self.assertEqual(caught.exception.code, "stale_element")
        self.assertFalse(self.desktop.actions)

    def test_elements_outside_capture_are_not_offered(self):
        self.desktop.items[0]["bounds"] = [-900, 10, -500, 40]
        result = self.discover()
        self.assertEqual(result["elements"], [])
