"""Coordinates are always pixels in the returned screenshot."""

import math

from .protocol import ControlError


def map_point(x, y, image_size, bounds):
    width, height = image_size
    if not (0 <= x < width and 0 <= y < height):
        raise ControlError(
            "out_of_bounds",
            f"Point ({x}, {y}) is outside the {width}x{height} screenshot. "
            f"Use screenshot pixels: x=0..{width - 1}, y=0..{height - 1}; "
            "do not pass desktop/window bounds. No input was sent.",
        )
    left, top, right, bottom = bounds
    return (
        left + min(right - left - 1, int(x * (right - left) / width)),
        top + min(bottom - top - 1, int(y * (bottom - top) / height)),
    )


def image_point(point, image_size, bounds):
    left, top, right, bottom = bounds
    width, height = image_size
    x, y = (
        round((point[0] - left) * width / (right - left)),
        round((point[1] - top) * height / (bottom - top)),
    )
    if left <= point[0] < right:
        x = min(width - 1, max(0, x))
    if top <= point[1] < bottom:
        y = min(height - 1, max(0, y))
    return [x, y]


def image_rect(rect, image_size, bounds):
    """Clipped half-open rectangle in screenshot pixels, or None if outside."""
    left, top, right, bottom = bounds
    x1, y1 = max(left, rect[0]), max(top, rect[1])
    x2, y2 = min(right, rect[2]), min(bottom, rect[3])
    if x1 >= x2 or y1 >= y2:
        return None
    width, height = image_size
    return [
        max(0, math.floor((x1 - left) * width / (right - left))),
        max(0, math.floor((y1 - top) * height / (bottom - top))),
        min(width, math.ceil((x2 - left) * width / (right - left))),
        min(height, math.ceil((y2 - top) * height / (bottom - top))),
    ]
