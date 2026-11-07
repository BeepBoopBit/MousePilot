import unittest

from mousepilot.geometry import map_point
from mousepilot.protocol import ControlError


class GeometryTests(unittest.TestCase):
    def test_scaled_center(self):
        self.assertEqual(map_point(640, 360, (1280, 720), (0, 0, 1920, 1080)), (960, 540))

    def test_negative_monitor_origin(self):
        self.assertEqual(map_point(0, 0, (1280, 720), (-1920, 0, 0, 1080)), (-1920, 0))

    def test_bounds(self):
        for point in [(-1, 0), (1280, 0), (0, 720)]:
            with self.assertRaises(ControlError):
                map_point(*point, (1280, 720), (0, 0, 1920, 1080))

    def test_last_pixel(self):
        self.assertEqual(map_point(1919, 1079, (1920, 1080), (0, 0, 1920, 1080)), (1919, 1079))
