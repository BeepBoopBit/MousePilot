"""Safety and coordinate invariants run on all hosts without loading Cocoa."""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from helpers import FakeDesktop
from PIL import Image

from mousepilot.controller import Controller
from mousepilot.geometry import map_point
from mousepilot.macos import Desktop, key_code
from mousepilot.protocol import ControlError


class MacTests(unittest.TestCase):
    def desktop(self):
        desktop = Desktop.__new__(Desktop)
        desktop.stopped = threading.Event()
        desktop.native_lock = threading.RLock()
        desktop.held_keys = set()
        desktop.held_buttons = set()
        desktop.Q = SimpleNamespace(
            kCGEventFlagMaskControl=1,
            kCGEventFlagMaskAlternate=2,
            kCGEventFlagMaskShift=4,
            kCGEventFlagMaskCommand=8,
            kCGHIDEventTap=0,
            CGEventCreateKeyboardEvent=lambda source, key, down: (key, down),
            CGEventSetFlags=Mock(),
            CGEventPost=Mock(),
            CGEventKeyboardSetUnicodeString=Mock(),
        )
        return desktop

    def test_failed_key_release_stays_tracked_for_retry(self):
        desktop = self.desktop()
        desktop.key(55, True)
        desktop.Q.CGEventPost.side_effect = RuntimeError("failed")
        with self.assertRaises(RuntimeError):
            desktop.key(55, False)
        self.assertIn((55, None), desktop.held_keys)
        desktop.Q.CGEventPost.side_effect = None
        desktop.release_all()
        self.assertFalse(desktop.held_keys)
        self.assertEqual(desktop.Q.CGEventSetFlags.call_args.args[1], 0)

    def test_invalid_hotkey_does_not_emit_input(self):
        desktop = self.desktop()
        for keys in [["cmd", "bad-key"], ["cmd", "command", "a"], ["a", "b"]]:
            with self.assertRaises(ValueError):
                desktop.hotkey(keys)
        desktop.Q.CGEventPost.assert_not_called()
        self.assertEqual(key_code("command"), key_code("cmd"))

    def test_failed_hotkey_releases_all_tracked_keys(self):
        desktop = self.desktop()

        def post(tap, event):
            if event == (0, True):
                raise RuntimeError("failed key down")

        desktop.Q.CGEventPost.side_effect = post
        with self.assertRaises(RuntimeError):
            desktop.hotkey(["cmd", "shift", "a"])
        self.assertFalse(desktop.held_keys)
        self.assertEqual(desktop.Q.CGEventPost.call_args_list[-3].args[1], (0, False))

    def test_unicode_never_injects_enter_and_cleanup_is_idempotent(self):
        desktop = self.desktop()
        desktop.type_text("hello 😀")
        events = [call.args[1] for call in desktop.Q.CGEventPost.call_args_list]
        self.assertTrue(all(code == 0 for code, down in events))
        count = len(events)
        desktop.release_all()
        self.assertEqual(desktop.Q.CGEventPost.call_count, count)
        self.assertFalse(desktop.held_keys)
        self.assertTrue(
            any(
                c.args[1:] == (2, "😀")
                for c in desktop.Q.CGEventKeyboardSetUnicodeString.call_args_list
            )
        )

    def test_permissions_block_input_before_any_event(self):
        desktop = self.desktop()
        desktop.check_session = lambda: None
        desktop.permissions = lambda: dict(
            accessibility=True, post_events=True, input_monitoring=True, emergency_hotkey=False
        )
        with self.assertRaises(ControlError) as caught:
            desktop.check_ready()
        self.assertEqual(caught.exception.code, "permission_required")
        desktop.Q.CGEventPost.assert_not_called()

    def test_retina_capture_maps_image_pixels_to_logical_desktop_points(self):
        desktop = FakeDesktop()
        desktop.displays[0]["bounds"] = [-100, 0, 900, 600]
        desktop.capture = lambda bounds: Image.new("RGB", (2000, 1200), "white")
        controller = Controller(desktop, "test", "Retina")
        result = controller.execute({"command": "screen", "width": 1000})
        frame = controller.frame(result["screenshot_id"])
        size = frame["image_size"]
        self.assertEqual(
            map_point(size[0] // 2, size[1] // 2, size, frame["desktop_bounds"]), (400, 300)
        )

    def test_locked_or_inactive_console_session_is_rejected(self):
        desktop = self.desktop()
        desktop.Q.kCGSessionOnConsoleKey = "console"
        desktop.Q.kCGSessionLoginDoneKey = "logged_in"
        for session in [
            None,
            {},
            {"console": False, "logged_in": True},
            {"console": True, "logged_in": False},
            {"console": True, "logged_in": True, "CGSSessionScreenIsLocked": True},
        ]:
            desktop.Q.CGSessionCopyCurrentDictionary = lambda: session
            with self.assertRaises(ControlError) as caught:
                desktop.check_session()
            self.assertEqual(caught.exception.code, "desktop_unavailable")
        desktop.Q.CGSessionCopyCurrentDictionary = lambda: {"console": True, "logged_in": True}
        desktop.check_session()
