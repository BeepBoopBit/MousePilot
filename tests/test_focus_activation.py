import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from mousepilot.protocol import ControlError
from mousepilot.windows import Desktop


class FocusActivationTests(unittest.TestCase):
    def setUp(self):
        self.desktop = Desktop.__new__(Desktop)
        self.desktop.native_lock = threading.RLock()
        self.desktop.stopped = threading.Event()
        self.identity = {"handle": 7, "process_id": 42}
        self.window = {
            "_identity": self.identity,
            "bounds": [100, 100, 700, 500],
            "minimized": False,
        }
        self.foreground = 8
        self.desktop.window_info = Mock(side_effect=lambda handle: dict(self.window))
        self.desktop.api = SimpleNamespace(
            GetForegroundWindow=lambda: self.foreground,
            SetForegroundWindow=Mock(),
            WindowFromPoint=Mock(return_value=7),
            GetAncestor=Mock(return_value=7),
            SendMessageTimeoutW=Mock(),
        )
        self.desktop.wait_foreground = Mock(side_effect=[False, True])
        self.desktop.hotkey = Mock()
        self.desktop.move = Mock()
        self.desktop.click = Mock(side_effect=self.activate)

    def activate(self, button, count):
        self.foreground = 7

    def test_denial_uses_only_verified_caption_or_straight_border(self):
        for hit, method in ((2, "verified_title_bar_click"), (12, "verified_border_click")):
            with self.subTest(hit=hit):
                self.setUp()
                self.desktop.activation_hit = Mock(return_value=hit)
                result = self.desktop.focus_window(self.identity)
                self.assertEqual(result["focus_method"], method)
                self.assertTrue(result["activation_click"])
                self.desktop.click.assert_called_once_with("left", 1)
                self.assertEqual(self.foreground, 7)

    def test_api_success_does_not_click(self):
        self.desktop.wait_foreground = Mock(return_value=True)
        result = self.desktop.focus_window(self.identity)
        self.assertEqual(result["focus_method"], "api")
        self.desktop.click.assert_not_called()
        self.desktop.move.assert_not_called()

    def test_disabling_fallback_never_moves_or_clicks(self):
        with self.assertRaises(ControlError):
            self.desktop.focus_window(self.identity, allow_input=False)
        self.desktop.click.assert_not_called()
        self.desktop.move.assert_not_called()
        self.desktop.hotkey.assert_not_called()

    def test_covered_frame_uses_one_keyboard_shortcut_without_clicking(self):
        self.desktop.activation_hit = Mock(return_value=None)
        result = self.desktop.focus_window(self.identity)
        self.assertEqual(result["focus_method"], "keyboard_assisted_api")
        self.desktop.hotkey.assert_called_once_with(["alt", "escape"])
        self.desktop.click.assert_not_called()
        self.desktop.move.assert_not_called()

    def test_failed_keyboard_activation_is_not_reported_as_success(self):
        self.desktop.activation_hit = Mock(return_value=None)
        self.desktop.wait_foreground = Mock(return_value=False)
        with self.assertRaisesRegex(ControlError, "shortcut was sent"):
            self.desktop.focus_window(self.identity)
        self.desktop.hotkey.assert_called_once()
        self.desktop.click.assert_not_called()

    def test_rechecks_coverage_after_moving_pointer(self):
        self.desktop.activation_hit = Mock(side_effect=[2, None])
        with self.assertRaisesRegex(ControlError, "became covered"):
            self.desktop.focus_window(self.identity)
        self.desktop.click.assert_not_called()

    def test_rejects_window_movement_before_click(self):
        self.desktop.activation_hit = Mock(return_value=12)
        self.desktop.move.side_effect = lambda *point: self.window.update(
            bounds=[110, 100, 710, 500]
        )
        with self.assertRaises(ControlError):
            self.desktop.focus_window(self.identity)
        self.desktop.click.assert_not_called()

    def test_activation_click_must_be_confirmed(self):
        self.desktop.activation_hit = Mock(return_value=2)
        self.desktop.wait_foreground = Mock(return_value=False)
        with self.assertRaisesRegex(ControlError, "click was sent"):
            self.desktop.focus_window(self.identity)
        self.desktop.click.assert_called_once()

    def test_native_hit_test_rejects_content_buttons_and_other_windows(self):
        for hit in (1, 3, 8, 9, 13, 14, 16, 17, 20):

            def respond(*args):
                args[-1]._obj.value = hit
                return 1

            self.desktop.api.SendMessageTimeoutW.side_effect = respond
            self.assertIsNone(self.desktop.activation_hit(7, (400, 102)))
        self.desktop.api.GetAncestor.return_value = 8
        self.desktop.api.SendMessageTimeoutW.reset_mock()
        self.assertIsNone(self.desktop.activation_hit(7, (400, 102)))
        self.desktop.api.SendMessageTimeoutW.assert_not_called()

    def test_paused_focus_never_sends_input(self):
        self.desktop.stopped.set()
        with self.assertRaises(ControlError):
            self.desktop.focus_window(self.identity)
        self.desktop.click.assert_not_called()
        self.desktop.move.assert_not_called()
