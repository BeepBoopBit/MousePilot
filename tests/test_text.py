import unittest

from mousepilot.text import utf16_units


class TextTests(unittest.TestCase):
    def test_plain_text(self):
        self.assertEqual(utf16_units("watermelon"), list(map(ord, "watermelon")))

    def test_surrogate_pair(self):
        self.assertEqual(utf16_units("😀"), [0xD83D, 0xDE00])

    def test_reject_controls(self):
        for text in ["", "hello\n", "hello\r", "\t", "\x00", "\u2028"]:
            with self.assertRaises(ValueError):
                utf16_units(text)
