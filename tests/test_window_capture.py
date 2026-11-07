import unittest

from helpers import FakeDesktop

from mousepilot.controller import Controller
from mousepilot.protocol import ControlError


class WindowCaptureTests(unittest.TestCase):
    def setUp(self):
        self.desktop = FakeDesktop()
        self.controller = Controller(self.desktop, "test", "test")
        self.window_id = self.call("windows")["windows"][0]["window_id"]
        self.call("focus", window_id=self.window_id)
        self.desktop.actions.clear()

    def call(self, command, **args):
        return self.controller.execute({"command": command, **args})

    def capture(self):
        return self.call("window_capture", window_id=self.window_id)

    def test_window_listing_labels_edges_and_dimensions(self):
        row = self.call("windows")["windows"][0]
        self.assertEqual(row["bounds_format"], "left_top_right_bottom")
        self.assertEqual(row["position_desktop"], {"x": 100, "y": 100})
        self.assertEqual(row["size_desktop"], {"width": 400, "height": 400})

    def test_info_updates_position_size_and_monitor(self):
        self.desktop.displays.append(
            {"id": "left", "primary": False, "bounds": [-1920, 0, 0, 1200]}
        )
        self.desktop.window["bounds"] = [-600, 20, -100, 420]
        result = self.call("window_info", window_id=self.window_id)
        self.assertEqual([result[k] for k in ("x", "y", "width", "height")], [-600, 20, 500, 400])
        self.assertEqual(result["display_ids"], ["left"])
        self.assertTrue(result["foreground"])

    def test_window_pixels_map_to_desktop(self):
        self.desktop.window["bounds"] = [200, 100, 1800, 900]
        frame = self.capture()
        self.assertEqual(frame["image_size"], [1280, 640])
        result = self.call("click", frame=frame["screenshot_id"], x=640, y=320)
        self.assertEqual(result["target_desktop"], [1000, 500])

    def test_offscreen_edges_clipped(self):
        self.desktop.window["bounds"] = [-100, -50, 500, 500]
        frame = self.capture()
        self.assertEqual(frame["desktop_bounds"], [0, 0, 500, 500])
        self.assertEqual(frame["window_bounds"], [-100, -50, 500, 500])

    def test_moved_resized_minimized_and_background_reject_without_input(self):
        for change in (
            {"bounds": [200, 100, 600, 500]},
            {"bounds": [100, 100, 600, 500]},
            {"minimized": True},
            {"foreground": False},
        ):
            with self.subTest(change=change):
                self.setUp()
                frame = self.capture()
                self.desktop.window.update(change)
                with self.assertRaisesRegex(ControlError, "Window moved"):
                    self.call("click", frame=frame["screenshot_id"], x=10, y=10)
                self.assertEqual(self.desktop.actions, [])

    def test_derived_crops_and_previews_retain_guard(self):
        frame = self.capture()
        crop = self.call("crop", frame=frame["screenshot_id"], x=0, y=0, width=100, height=100)
        preview = self.call("preview", frame=crop["screenshot_id"], x=50, y=50)
        self.desktop.window["bounds"] = [101, 100, 501, 500]
        for image in (frame, crop, preview):
            with self.assertRaises(ControlError):
                self.call("move", frame=image["screenshot_id"], x=10, y=10)
        self.assertEqual(self.desktop.actions, [])

    def test_changes_during_capture_discard_image(self):
        capture = self.desktop.capture

        def changing(bounds):
            image = capture(bounds)
            self.desktop.window["bounds"] = [200, 100, 600, 500]
            return image

        self.desktop.capture = changing
        with self.assertRaises(ControlError):
            self.capture()
        self.assertFalse(self.controller.frames)

    def test_closed_or_replaced_window_rejected(self):
        frame = self.capture()
        self.desktop.window["_identity"] = {"handle": 2}
        with self.assertRaises(ControlError):
            self.call("window_info", window_id=self.window_id)
        with self.assertRaises(ControlError):
            self.call("click", frame=frame["screenshot_id"], x=10, y=10)
        self.assertEqual(self.desktop.actions, [])

    def test_capture_requires_focus_and_supports_pause(self):
        self.desktop.window["foreground"] = False
        with self.assertRaises(ControlError):
            self.capture()
        self.desktop.window["foreground"] = True
        self.desktop.stopped.set()
        self.assertIn("png_base64", self.capture())
        self.assertIn("width", self.call("window_info", window_id=self.window_id))
