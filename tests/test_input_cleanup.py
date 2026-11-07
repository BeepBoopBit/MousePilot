import threading
import unittest

from mousepilot.protocol import ControlError
from mousepilot.windows import Desktop


class InputCleanupTests(unittest.TestCase):
    def setUp(self):
        self.desktop = Desktop.__new__(Desktop)
        self.desktop.stopped = threading.Event()
        self.desktop.native_lock = threading.RLock()
        self.desktop.held_keys = set()
        self.desktop.held_buttons = set()
        self.events = []
        self.desktop.inject = self.events.append

    def test_invalid_hotkey_does_not_press_modifiers(self):
        with self.assertRaises(ValueError):
            self.desktop.hotkey(["ctrl", "unsupported-key"])
        self.assertEqual(self.events, [])

    def test_hotkey_failure_releases_modifiers(self):
        def inject(event):
            self.events.append(event)
            if event.ki.wVk == 65 and event.ki.dwFlags == 0:
                raise ControlError("input_failed", "test failure")

        self.desktop.inject = inject
        with self.assertRaises(ControlError):
            self.desktop.hotkey(["ctrl", "shift", "a"])
        self.assertFalse(self.desktop.held_keys)
        self.assertEqual(
            [(e.ki.wVk, e.ki.dwFlags) for e in self.events[-3:]], [(65, 2), (16, 2), (17, 2)]
        )

    def test_interrupted_drag_releases_button(self):
        moves = []

        def move(x, y, **kwargs):
            moves.append((x, y))
            if len(moves) > 1:
                self.desktop.stopped.set()

        self.desktop.move = move
        with self.assertRaises(ControlError):
            self.desktop.drag((0, 0), (100, 100), 0.1, "left")
        self.assertFalse(self.desktop.held_buttons)
        self.assertEqual([event.mi.dwFlags for event in self.events], [2, 4])

    def test_type_never_emits_enter(self):
        self.desktop.type_text("hello 😀")
        self.assertTrue(all(event.ki.wVk == 0 for event in self.events))
        self.assertTrue(all(event.ki.dwFlags in (4, 6) for event in self.events))
        self.assertFalse(self.desktop.held_keys)

    def test_horizontal_wheel_uses_native_hwheel_flag(self):
        self.desktop.scroll(-2, "horizontal")
        self.assertEqual(self.events[0].mi.dwFlags, 0x1000)
        self.assertEqual(self.events[0].mi.mouseData, (-240) & 0xFFFFFFFF)

    def test_focus_denial_is_not_reported_as_success(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        identity = {"handle": 7, "process_id": 42, "title": "Test"}
        self.desktop.window_info = lambda handle: {"_identity": identity, "minimized": False}
        self.desktop.api = SimpleNamespace(
            GetForegroundWindow=lambda: 8, SetForegroundWindow=lambda handle: False
        )
        with patch("mousepilot.windows.time.monotonic", side_effect=[0, 1]):
            with self.assertRaisesRegex(ControlError, "did not grant foreground"):
                self.desktop.focus_window(identity, allow_input=False)

    def test_stale_window_is_rejected_before_focus_attempt(self):
        self.desktop.window_info = lambda handle: None
        with self.assertRaisesRegex(ControlError, "closed or changed"):
            self.desktop.focus_window({"handle": 7})

    def test_emergency_release_and_operation_finally_are_idempotent(self):
        self.desktop.button("left", True)
        self.desktop.key(17, True)
        self.desktop.release_all()
        self.desktop.button("left", False)
        self.desktop.key(17, False)
        self.desktop.release_all()
        self.assertEqual(len(self.events), 4)
        self.assertFalse(self.desktop.held_buttons)
        self.assertFalse(self.desktop.held_keys)
