"""Display observations and serialized input, independent of network transport."""

import base64
import io
import secrets
import threading
import time
from collections import OrderedDict
from datetime import UTC, datetime

from PIL import ImageDraw

from . import annotations
from .displays import describe, overview, resolve
from .geometry import image_point, image_rect, map_point
from .protocol import COMMANDS, PROTOCOL_VERSION, VERSION, ControlError, WindowCapture
from .text import utf16_units


class Controller:
    def __init__(self, desktop, device_id, name, frame_ttl=120, clock=time.monotonic):
        self.desktop = desktop
        self.device_id = device_id
        self.name = name
        self.frame_ttl = frame_ttl
        self.clock = clock
        self.frames = OrderedDict()
        self.windows = OrderedDict()
        self.elements = OrderedDict()
        self.lock = threading.Lock()

    def info(self):
        info = self.desktop.info()
        return {
            **info,
            "device_id": self.device_id,
            "name": self.name,
            "protocol_version": PROTOCOL_VERSION,
            "version": VERSION,
            "paused": self.desktop.stopped.is_set(),
            "capabilities": [
                "control_status",
                "reset",
                "preview",
                *(["elements", "element_click"] if hasattr(self.desktop, "list_elements") else []),
                "crop",
                "windows",
                "window_info",
                "window_capture",
                "focus",
                "cross_monitor_drag",
                "horizontal_scroll",
                "screen",
                "displays",
                "overview",
                "move",
                "click",
                "scroll",
                "type",
                "key",
                "hotkey",
                "drag",
                "stop",
                "resume",
            ],
        }

    def frame(self, frame_id):
        frame = self.frames.get(frame_id)
        if frame is None or self.clock() - frame["_time"] > self.frame_ttl:
            raise ControlError("stale_frame", "Screenshot expired or unknown; capture again")
        current = self.desktop.info()
        if current["displays"] != frame["_displays"]:
            raise ControlError("display_changed", "Display configuration changed; capture again")
        if frame.get("_window_guard"):
            self.validate_window_frame(frame["_window_guard"])
        return frame

    def execute(self, args, authorize=None):
        command = COMMANDS.validate_python(args)
        op = command.command
        if op == "stop":
            self.desktop.stopped.set()
            return {"paused": True}
        if op in ("info", "displays"):
            self.desktop.activate()
            if op == "info":
                return self.info()
            info = self.desktop.info()
            return {
                "device_id": self.device_id,
                "displays": describe(info["displays"], info["cursor"], command.aliases),
                "bounds_coordinate_space": info.get("coordinate_space", "desktop-pixels"),
            }
        if not self.lock.acquire(blocking=False):
            raise ControlError("busy", "Another desktop operation is running")
        try:
            if authorize:
                authorize()
            self.desktop.activate()
            if op == "info":
                return self.info()
            if op == "resume":
                self.desktop.stopped.clear()
                return {"paused": False}
            if op == "overview":
                return self.overview(command)
            if op == "screen":
                return self.screen(command)
            if op == "crop":
                return self.crop(command)
            if op == "windows":
                return self.list_windows(command.title, command.frame)
            if op == "window_info":
                return self.get_window_info(command.window_id)
            if op == "window_capture":
                return self.capture_window(command)
            if op == "preview":
                return self.preview(command)
            if op == "elements":
                return self.list_elements(command)
            self.desktop.check_ready()
            action_frame = None
            target = None
            if op == "focus":
                focus_result = (
                    self.desktop.focus_window(
                        self.window_entry(command.window_id)["identity"],
                        allow_input=command.allow_input,
                    )
                    or {}
                )
            elif op == "element_click":
                return self.click_element(command)
            elif op in ("move", "click", "drag"):
                frame = self.frame(command.frame)
                action_frame = frame

                def point(x, y):
                    return map_point(x, y, frame["image_size"], frame["desktop_bounds"])

                if op == "drag":
                    start = point(command.from_x, command.from_y)
                    destination = self.frame(command.to_frame) if command.to_frame else frame
                    end = map_point(
                        command.to_x,
                        command.to_y,
                        destination["image_size"],
                        destination["desktop_bounds"],
                    )
                    action_frame = destination
                    target = end
                    self.desktop.drag(start, end, command.duration, command.button)
                else:
                    target = point(command.x, command.y)
                    if command.dry_run:
                        return {
                            "desktop_target": list(target),
                            "target_image": [command.x, command.y],
                            "coordinate_space": "screenshot_pixels",
                            "executed": False,
                        }
                    self.desktop.move(*target)
                    if op == "click":
                        self.desktop.click(command.button, command.count)
            elif op == "scroll":
                self.desktop.scroll(command.steps, command.axis)
            elif op == "type":
                utf16_units(command.text)  # Validate before injecting any input.
                self.desktop.type_text(command.text)
            elif op == "key":
                self.desktop.press_key(command.key)
            elif op == "hotkey":
                self.desktop.hotkey(command.keys)
            info = self.desktop.info()
            result = {
                "executed": True,
                "device_id": self.device_id,
                "cursor": info["cursor"],
            }
            result.update(
                cursor_desktop=result["cursor"],
                cursor_coordinate_space=info.get("coordinate_space", "desktop-pixels"),
                outcome_verified=op == "focus",
            )
            if action_frame:
                left, top, right, bottom = action_frame["desktop_bounds"]
                inside = left <= result["cursor"][0] < right and top <= result["cursor"][1] < bottom
                result.update(
                    cursor_image=image_point(
                        result["cursor"], action_frame["image_size"], action_frame["desktop_bounds"]
                    )
                    if inside
                    else None,
                    cursor_inside_capture=inside,
                    screenshot_id=action_frame["screenshot_id"],
                    target_desktop=list(target),
                    target_image=[command.to_x, command.to_y]
                    if op == "drag"
                    else [command.x, command.y],
                    input_coordinate_space="screenshot_pixels",
                    next_step="Capture a fresh screenshot to verify the UI result; executed means input was sent.",
                )
            if op == "focus":
                result.update(
                    window_id=command.window_id,
                    foreground_verified=True,
                    **focus_result,
                    next_step="Call capture_window with this window_id, then list_elements to choose a named element_id. Mouse coordinates are returned image pixels; do not convert to device resolution.",
                )
            if op == "type":
                result.update(characters=len(command.text), enter_pressed=False)
            return result
        finally:
            try:
                if op not in (
                    "screen",
                    "crop",
                    "preview",
                    "elements",
                    "windows",
                    "window_info",
                    "window_capture",
                    "overview",
                    "resume",
                ):
                    self.desktop.release_all()
            finally:
                self.lock.release()

    def reset_control(self):
        """Fence active input before clearing observations. Caller must revoke the lease first."""
        self.desktop.stopped.set()
        self.desktop.release_all()
        if not self.lock.acquire(timeout=10):
            raise ControlError(
                "reset_timeout", "Input remains paused; active operation did not stop in time"
            )
        try:
            self.desktop.stopped.set()
            self.desktop.release_all()
            self.frames.clear()
            self.windows.clear()
            self.elements.clear()
        finally:
            self.lock.release()

    def screen(self, command):
        before = self.desktop.info()
        display = resolve(before["displays"], command.display_id, command.aliases)
        bounds = display["bounds"]
        return self.capture_screen(
            before, display, bounds, command.width, command.grid, command.cursor_marker
        )

    def capture_screen(
        self,
        before,
        display,
        bounds,
        width,
        grid=False,
        cursor_marker=False,
        upscale=False,
        parent=None,
        exact_size=None,
        window_guard=None,
    ):
        if parent and not window_guard:
            window_guard = self.frame(parent).get("_window_guard")
        if window_guard:
            self.validate_window_frame(window_guard)
        image = self.desktop.capture(bounds)
        if window_guard:
            self.validate_window_frame(window_guard)
        if self.desktop.info()["displays"] != before["displays"]:
            raise ControlError("display_changed", "Display changed during capture; retry")
        if image.width > width or upscale:
            scale = min(
                width / image.width,
                8192 / image.height,
                (16_000_000 / (image.width * image.height)) ** 0.5,
            )
            image = image.resize(
                (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
            )
        if exact_size and image.size != tuple(exact_size):
            image = image.resize(tuple(exact_size))
        left, top, right, bottom = bounds
        cx, cy = before["cursor"]
        cursor = {
            "desktop": [cx, cy],
            "image": image_point([cx, cy], image.size, bounds)
            if left <= cx < right and top <= cy < bottom
            else None,
            "inside_capture": left <= cx < right and top <= cy < bottom,
        }
        draw = ImageDraw.Draw(image)
        if grid:
            for x in range(0, image.width, 100):
                draw.line((x, 0, x, image.height), fill="red")
                draw.text((x + 2, 2), str(x), fill="red")
            for y in range(0, image.height, 100):
                draw.line((0, y, image.width, y), fill="red")
                draw.text((2, y + 2), str(y), fill="red")
        if cursor_marker and cursor["inside_capture"]:
            x, y = cursor["image"]
            draw.ellipse((x - 7, y - 7, x + 7, y + 7), outline="magenta", width=2)
            draw.line((x - 10, y, x + 10, y), fill="magenta")
            draw.line((x, y - 10, x, y + 10), fill="magenta")
        frame_id = secrets.token_hex(16)
        metadata = {
            "device_id": self.device_id,
            "screenshot_id": frame_id,
            "display_id": display["id"],
            "display_label": display["label"],
            "display_aliases": display["aliases"],
            "image_size": list(image.size),
            "desktop_bounds": bounds,
            "coordinate_space": "screenshot_pixels",
            "desktop_coordinate_space": before.get("coordinate_space", "desktop-pixels"),
            "valid_coordinates": {"x": [0, image.width - 1], "y": [0, image.height - 1]},
            "coordinate_note": "Use x,y in this returned image. desktop_bounds and cursor.desktop are NOT click coordinates. A cursor outside capture has image=null.",
            "image_content_returned": True,
            "cursor": cursor,
            "captured_at": datetime.now(UTC).isoformat(),
            "expires_in_seconds": self.frame_ttl,
            "grid": grid,
            "cursor_marker": cursor_marker,
            "parent_screenshot_id": parent,
        }
        if window_guard:
            metadata.update(
                window_id=window_guard["window_id"],
                capture_kind="visible_window_region",
                window_bounds=window_guard["bounds"],
                window_note="Desktop pixels cropped to this window; overlapping windows may be visible. Window movement, resizing, minimization or lost focus invalidates this screenshot.",
            )
        self.frames[frame_id] = {
            **metadata,
            "_time": self.clock(),
            "_displays": before["displays"],
            "_window_guard": window_guard,
        }
        while len(self.frames) > 32:
            self.frames.popitem(last=False)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return {**metadata, "png_base64": base64.b64encode(buffer.getvalue()).decode()}

    def overview(self, command):
        before = self.desktop.info()
        displays = describe(before["displays"], before["cursor"], command.aliases)
        captures = [self.desktop.capture(d["bounds"]) for d in displays]
        if self.desktop.info()["displays"] != before["displays"]:
            raise ControlError(
                "display_changed", "Display configuration changed during overview; retry"
            )
        image, layout = overview(displays, captures, command.width, command.height)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return {
            "device_id": self.device_id,
            "kind": "display_overview",
            "actionable": False,
            "image_size": list(image.size),
            "displays": layout,
            "captured_at": datetime.now(UTC).isoformat(),
            "next_step": "Call current_screen with a display ID or alias before any mouse action.",
            "png_base64": base64.b64encode(buffer.getvalue()).decode(),
        }

    def crop(self, command):
        source = self.frame(command.frame)
        iw, ih = source["image_size"]
        if command.x + command.width > iw or command.y + command.height > ih:
            raise ControlError(
                "invalid_crop", "Crop rectangle must be inside the source screenshot"
            )
        left, top, right, bottom = source["desktop_bounds"]
        x1, y1 = map_point(command.x, command.y, source["image_size"], source["desktop_bounds"])
        x2 = min(right, max(x1 + 1, left + (command.x + command.width) * (right - left) // iw))
        y2 = min(bottom, max(y1 + 1, top + (command.y + command.height) * (bottom - top) // ih))
        before = self.desktop.info()
        if before["displays"] != source["_displays"]:
            raise ControlError("display_changed", "Display configuration changed; capture again")
        display = {
            "id": source["display_id"],
            "label": source["display_label"],
            "aliases": source["display_aliases"],
        }
        return self.capture_screen(
            before,
            display,
            [x1, y1, x2, y2],
            command.output_width,
            upscale=True,
            parent=command.frame,
        )

    def list_windows(self, title, frame_id=None):
        source = self.frame(frame_id) if frame_id else None
        space = self.desktop.info().get("coordinate_space", "desktop-pixels")
        result = []
        for window in self.desktop.list_windows():
            if title.casefold() not in window["title"].casefold():
                continue
            window = dict(window)
            identity = window.pop("_identity")
            window_id = secrets.token_hex(16)
            self.windows[window_id] = {"identity": identity, "time": self.clock()}
            left, top, right, bottom = window["bounds"]
            window.update(
                desktop_bounds=window["bounds"],
                bounds_coordinate_space=space,
                bounds_format="left_top_right_bottom",
                position_desktop={"x": left, "y": top},
                size_desktop={"width": right - left, "height": bottom - top},
            )
            if source:
                window["image_bounds"] = image_rect(
                    window["bounds"], source["image_size"], source["desktop_bounds"]
                )
                window["screenshot_id"] = frame_id
            result.append({**window, "window_id": window_id})
        while len(self.windows) > 512:
            self.windows.popitem(last=False)
        return {
            "device_id": self.device_id,
            "windows": result,
            "bounds_coordinate_space": space,
            "bounds_note": "bounds=[left,top,right,bottom], NOT [x,y,width,height]. Width=right-left; height=bottom-top. No device-resolution calculation is needed: focus_window then capture_window and use returned image pixels.",
            "window_id_note": "Window IDs are temporary observation references and may change on every listing; a changed ID does not indicate a new/reopened window.",
            "expires_in_seconds": self.frame_ttl,
        }

    def window_entry(self, window_id):
        entry = self.windows.get(window_id)
        if entry is None or self.clock() - entry["time"] > self.frame_ttl:
            raise ControlError(
                "stale_window", "Window ID expired or unknown; call list_windows again"
            )
        return entry

    def current_window(self, identity):
        for window in self.desktop.list_windows():
            if window["_identity"] == identity:
                return window
        raise ControlError("stale_window", "Window closed or changed; call list_windows again")

    def get_window_info(self, window_id):
        window = dict(self.current_window(self.window_entry(window_id)["identity"]))
        window.pop("_identity")
        left, top, right, bottom = window["bounds"]
        info = self.desktop.info()
        monitors = []
        for display in info["displays"]:
            dl, dt, dr, db = display["bounds"]
            area = max(0, min(right, dr) - max(left, dl)) * max(0, min(bottom, db) - max(top, dt))
            if area:
                monitors.append((area, display["id"]))
        monitors.sort(reverse=True)
        return {
            **window,
            "device_id": self.device_id,
            "window_id": window_id,
            "x": left,
            "y": top,
            "width": right - left,
            "height": bottom - top,
            "desktop_bounds": window["bounds"],
            "bounds_coordinate_space": info.get("coordinate_space", "desktop-pixels"),
            "display_id": monitors[0][1] if monitors else None,
            "display_ids": [item[1] for item in monitors],
            "coordinate_note": "Position and dimensions are desktop units, not screenshot click coordinates. Use capture_window for actionable image pixels.",
        }

    def validate_window_frame(self, guard):
        window = self.current_window(guard["identity"])
        if window["bounds"] != guard["bounds"] or window["minimized"] or not window["foreground"]:
            raise ControlError(
                "window_changed",
                "Window moved, resized, minimized, or lost focus; focus it and call capture_window again. No input was sent.",
            )

    def capture_window(self, command):
        window = self.get_window_info(command.window_id)
        if window["minimized"] or not window["foreground"]:
            raise ControlError(
                "window_not_ready",
                "Restore and focus the window with focus_window before capture_window",
            )
        before = self.desktop.info()
        displays = before["displays"]
        left, top, right, bottom = window["bounds"]
        bounds = [
            max(left, min(d["bounds"][0] for d in displays)),
            max(top, min(d["bounds"][1] for d in displays)),
            min(right, max(d["bounds"][2] for d in displays)),
            min(bottom, max(d["bounds"][3] for d in displays)),
        ]
        if not window["display_ids"] or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            raise ControlError("window_offscreen", "Window has no visible display region")
        display = resolve(displays, window["display_id"], {})
        guard = {
            "identity": self.window_entry(command.window_id)["identity"],
            "window_id": command.window_id,
            "bounds": list(window["bounds"]),
        }
        return self.capture_screen(
            before,
            display,
            bounds,
            command.width,
            command.grid,
            command.cursor_marker,
            window_guard=guard,
        )

    def refresh_frame(self, source):
        before = self.desktop.info()
        display = {
            "id": source["display_id"],
            "label": source["display_label"],
            "aliases": source["display_aliases"],
        }
        return self.capture_screen(
            before,
            display,
            source["desktop_bounds"],
            source["image_size"][0],
            upscale=True,
            parent=source["screenshot_id"],
            exact_size=source["image_size"],
        )

    def preview(self, command):
        source = self.frame(command.frame)
        map_point(command.x, command.y, source["image_size"], source["desktop_bounds"])
        result = self.refresh_frame(source)
        point = [command.x, command.y]
        full, zoom, region, size, zoom_point = annotations.preview(
            result["png_base64"], point, command.radius
        )
        result.update(
            png_base64=full,
            preview_png_base64=zoom,
            target_image=point,
            target_desktop=list(map_point(*point, result["image_size"], result["desktop_bounds"])),
            pointer_moved=False,
            clicked=False,
            preview={
                "actionable": False,
                "image_size": size,
                "source_image_bounds": region,
                "target_in_preview": zoom_point,
            },
            next_step="Inspect the crosshair. To click, use target_image and the NEW screenshot_id on the main image. The zoom inset is not actionable. If you cannot see the images, stop; metadata alone cannot locate controls.",
        )
        return result

    def visual_elements_fallback(self, command, source, reason):
        result = self.capture_window(
            WindowCapture(window_id=command.window_id, width=max(100, source["image_size"][0]))
        )
        result.update(
            elements=[],
            accessibility_status="no_controls" if reason == "no_controls" else "unavailable",
            interaction_mode="visual",
            fallback_reason=reason,
            truncated=False,
            next_step="No usable accessible controls were returned for this capture; this does not prove the app is unsupported. Inspect this fresh window image to locate the desired control visually. Use preview_target, then click with its NEW screenshot_id and target_image. After focusing a text field, type_text types without Enter. Do not guess from window bounds. If you cannot identify the target in the image, stop and ask the user.",
        )
        return result

    def list_elements(self, command):
        source = self.frame(command.frame)
        window = self.window_entry(command.window_id)["identity"]
        if not hasattr(self.desktop, "list_elements"):
            return self.visual_elements_fallback(command, source, "unsupported")
        try:
            native = self.desktop.list_elements(window, command.limit)
        except ControlError as exc:
            if exc.code not in (
                "accessibility_unavailable",
                "accessibility_timeout",
                "unsupported",
            ):
                raise
            return self.visual_elements_fallback(command, source, exc.code)
        if not native["elements"] and not native.get("truncated", False):
            return self.visual_elements_fallback(command, source, "no_controls")
        result = self.refresh_frame(source)
        self.desktop.validate_element_window(window)
        rows = []
        for item in native["elements"]:
            rect = image_rect(item["bounds"], result["image_size"], result["desktop_bounds"])
            if rect is None:
                continue
            element_id = secrets.token_hex(16)
            center = [(rect[0] + rect[2] - 1) // 2, (rect[1] + rect[3] - 1) // 2]
            point = map_point(*center, result["image_size"], result["desktop_bounds"])
            row = {
                "element_id": element_id,
                "label": len(rows) + 1,
                "name": item["name"],
                "role": item["role"],
                "image_bounds": rect,
                "center_image": center,
                "desktop_bounds": item["bounds"],
                "automation_id": item.get("automation_id", ""),
            }
            self.elements[element_id] = {
                "time": self.clock(),
                "frame": result["screenshot_id"],
                "window": window,
                "identity": item["_identity"],
                "target": point,
                "center": center,
            }
            rows.append(row)
        while len(self.elements) > 512:
            self.elements.popitem(last=False)
        result["png_base64"] = annotations.elements(result["png_base64"], rows)
        result.update(
            elements=rows,
            window_id=command.window_id,
            annotations="numbered_ui_automation_elements",
            accessibility_status="available" if rows else "no_controls_in_capture",
            interaction_mode="accessible_elements_or_visual",
            coverage_note="Discovery may be partial. Window buttons can be exposed while custom editor fields are absent. A missing control does not mean the app cannot be clicked or typed into.",
            truncated=native.get("truncated", False),
            next_step="If the desired control is listed, choose element_id and call click_element. If it is missing, inspect this screenshot visually, use preview_target then click using the NEW screenshot_id and target_image; after focusing a text field, type_text types without Enter. Do not invent element IDs or guess from window bounds. If you cannot see or identify the target, stop and ask the user. No OCR is used.",
        )
        return result

    def click_element(self, command):
        entry = self.elements.get(command.element_id)
        if entry is None or self.clock() - entry["time"] > self.frame_ttl:
            raise ControlError(
                "stale_element", "Element reference expired or unknown; call list_elements again"
            )
        frame = self.frame(entry["frame"])
        self.desktop.validate_element_window(entry["window"])
        self.desktop.validate_element(entry["window"], entry["identity"], entry["target"])
        self.desktop.check_ready()
        self.desktop.move(*entry["target"])
        self.desktop.click(command.button, command.count)
        return {
            "executed": True,
            "outcome_verified": False,
            "device_id": self.device_id,
            "element_id": command.element_id,
            "screenshot_id": entry["frame"],
            "target_image": entry["center"],
            "target_desktop": list(entry["target"]),
            "cursor_desktop": self.desktop.info()["cursor"],
            "cursor_coordinate_space": frame["desktop_coordinate_space"],
            "next_step": "Capture a fresh screenshot to verify the result; input sent does not prove the control action succeeded.",
        }
