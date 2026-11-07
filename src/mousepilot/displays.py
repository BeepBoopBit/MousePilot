"""Display descriptions and a navigation-only desktop overview."""

import math

from PIL import Image, ImageDraw, ImageFont

from .protocol import ControlError


def describe(displays, cursor, aliases):
    selectors = {value for d in displays for value in (d["id"], d.get("device_name", d["id"]))}
    if set(aliases) & selectors:
        raise ControlError(
            "invalid_alias", "Display aliases must not shadow display IDs or device names"
        )
    result = []
    for index, display in enumerate(displays, 1):
        left, top, right, bottom = display["bounds"]
        names = sorted(
            name
            for name, target in aliases.items()
            if target in (display["id"], display.get("device_name"))
        )
        result.append(
            {
                **display,
                "number": index,
                "label": names[0] if names else f"Display {index}",
                "aliases": names,
                "resolution": [right - left, bottom - top],
                "orientation": "portrait" if bottom - top > right - left else "landscape",
                "contains_cursor": left <= cursor[0] < right and top <= cursor[1] < bottom,
            }
        )
    return result


def resolve(displays, selector, aliases):
    described = describe(displays, [0, 0], aliases)
    target = aliases.get(selector, selector)
    matches = [d for d in described if target in (d["id"], d.get("device_name"))]
    if len(matches) != 1:
        raise ControlError(
            "unknown_display", "Display or alias is unavailable; call list_displays again"
        )
    return matches[0]


def overview(displays, captures, width, height):
    left = min(d["bounds"][0] for d in displays)
    top = min(d["bounds"][1] for d in displays)
    right = max(d["bounds"][2] for d in displays)
    bottom = max(d["bounds"][3] for d in displays)
    scale = min((width - 32) / (right - left), (height - 64) / (bottom - top))
    canvas = Image.new("RGB", (width, height), "#171b22")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=14)
    draw.text(
        (16, 12),
        "Monitor overview - choose a display, then call current_screen",
        font=font,
        fill="white",
    )
    layout = []
    for display, image in zip(displays, captures):
        dl, dt, dr, db = display["bounds"]
        x, y = 16 + round((dl - left) * scale), 48 + round((dt - top) * scale)
        w, h = max(1, round((dr - dl) * scale)), max(1, round((db - dt) * scale))
        canvas.paste(image.resize((w, h), Image.Resampling.LANCZOS), (x, y))
        color = "#68e0a0" if display["contains_cursor"] else "#a6b2c6"
        draw.rectangle((x, y, x + w - 1, y + h - 1), outline=color, width=2)
        title = f"{display['number']}: {display['label']}" + (
            " [primary]" if display.get("primary") else ""
        )
        subtitle = f"{dr - dl}x{db - dt} | {display.get('scale_percent', '?')}%" + (
            " | cursor" if display["contains_cursor"] else ""
        )
        # Paint labels on a separate clipped tile so narrow monitors cannot overwrite neighbors.
        tile = Image.new("RGB", (w, min(h, 44)), "#202a38")
        label_draw = ImageDraw.Draw(tile)
        for line, text in enumerate((title, subtitle)):
            limit = max(1, math.floor((w - 8) / 9))
            label_draw.text((4, 3 + 19 * line), text[:limit], font=font, fill=color)
        canvas.paste(tile, (x, y))
        layout.append({**display, "overview_bounds": [x, y, x + w, y + h]})
    return canvas, layout
