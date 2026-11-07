"""Programmatic observation overlays; drawing never sends desktop input."""

import base64
import io

from PIL import Image, ImageDraw, ImageFont


def decode(png):
    return Image.open(io.BytesIO(base64.b64decode(png))).convert("RGB")


def encode(image):
    output = io.BytesIO()
    image.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode()


def crosshair(image, point):
    x, y = point
    draw = ImageDraw.Draw(image)
    for color, width in [("black", 5), ("#ff4bd8", 2)]:
        draw.ellipse((x - 10, y - 10, x + 10, y + 10), outline=color, width=width)
        draw.line((x - 17, y, x + 17, y), fill=color, width=width)
        draw.line((x, y - 17, x, y + 17), fill=color, width=width)


def preview(png, point, radius):
    image = decode(png)
    x, y = point
    region = [
        max(0, x - radius),
        max(0, y - radius),
        min(image.width, x + radius + 1),
        min(image.height, y + radius + 1),
    ]
    zoom = image.crop(region)
    scale = min(640 / zoom.width, 640 / zoom.height)
    zoom = zoom.resize(
        (round(zoom.width * scale), round(zoom.height * scale)), Image.Resampling.LANCZOS
    )
    target = [round((x - region[0]) * scale), round((y - region[1]) * scale)]
    crosshair(zoom, target)
    crosshair(image, point)
    return encode(image), encode(zoom), region, list(zoom.size), target


def elements(png, rows):
    image = decode(png)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=15)
    for row in rows:
        x1, y1, x2, y2 = row["image_bounds"]
        draw.rectangle((x1, y1, x2 - 1, y2 - 1), outline="#ffdd4a", width=2)
        text = str(row["label"])
        box = draw.textbbox((0, 0), text, font=font)
        width = box[2] - box[0] + 8
        tx, ty = min(x1, max(0, image.width - width)), max(0, y1 - 22)
        draw.rectangle(
            (tx, ty, tx + width, min(image.height - 1, ty + 21)), fill="#ffdd4a", outline="black"
        )
        draw.text((tx + 4, ty), text, font=font, fill="black")
    return encode(image)
