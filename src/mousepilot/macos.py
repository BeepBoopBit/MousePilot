"""Native macOS 14+ desktop backend using ScreenCaptureKit, Quartz, and Accessibility.

Desktop bounds are global Quartz points (top-left origin), not Retina pixels.
The controller maps actual returned-image pixels onto these bounds.
"""

import io
import math
import platform
import sys
import threading
import time

from .protocol import ControlError
from .text import utf16_units

KEYS = {
    "a": 0,
    "s": 1,
    "d": 2,
    "f": 3,
    "h": 4,
    "g": 5,
    "z": 6,
    "x": 7,
    "c": 8,
    "v": 9,
    "b": 11,
    "q": 12,
    "w": 13,
    "e": 14,
    "r": 15,
    "y": 16,
    "t": 17,
    "1": 18,
    "2": 19,
    "3": 20,
    "4": 21,
    "6": 22,
    "5": 23,
    "9": 25,
    "7": 26,
    "8": 28,
    "0": 29,
    "o": 31,
    "u": 32,
    "i": 34,
    "p": 35,
    "enter": 36,
    "l": 37,
    "j": 38,
    "k": 40,
    "n": 45,
    "m": 46,
    "tab": 48,
    "space": 49,
    "backspace": 51,
    "escape": 53,
    "cmd": 55,
    "shift": 56,
    "alt": 58,
    "ctrl": 59,
    "f1": 122,
    "f2": 120,
    "f3": 99,
    "f4": 118,
    "f5": 96,
    "f6": 97,
    "f7": 98,
    "f8": 100,
    "f9": 101,
    "f10": 109,
    "f11": 103,
    "home": 115,
    "pageup": 116,
    "delete": 117,
    "end": 119,
    "pagedown": 121,
    "left": 123,
    "right": 124,
    "down": 125,
    "up": 126,
}
ALIASES = {"command": "cmd", "win": "cmd", "option": "alt", "control": "ctrl"}


def key_code(name):
    name = ALIASES.get(name.lower(), name.lower())
    if name not in KEYS:
        raise ValueError(f"Unsupported macOS key: {name}")
    return KEYS[name]


def rect_bounds(rect):
    return [
        round(rect.origin.x),
        round(rect.origin.y),
        round(rect.origin.x + rect.size.width),
        round(rect.origin.y + rect.size.height),
    ]


class Desktop:
    emergency_hotkey = "Ctrl+Option+Shift+F11"

    def __init__(self):
        if sys.platform != "darwin":
            raise RuntimeError("macOS backend requires macOS")
        if int(platform.mac_ver()[0].split(".")[0]) < 14:
            raise RuntimeError("MousePilot requires macOS 14 or newer")
        import AppKit
        import ApplicationServices
        import CoreFoundation
        import Foundation
        import Quartz
        import ScreenCaptureKit

        self.Q, self.AX, self.CF = Quartz, ApplicationServices, CoreFoundation
        self.AppKit, self.Foundation, self.SC = AppKit, Foundation, ScreenCaptureKit
        self.stopped = threading.Event()
        self.native_lock = threading.RLock()
        self.held_keys = set()
        self.held_buttons = set()
        self.hotkey_ready = threading.Event()
        self.listener_done = threading.Event()
        self.tap = None
        self.hotkey_loop = None

    def activate(self):
        pass  # Quartz coordinates are global logical points; no DPI virtualization.

    def permissions(self):
        return {
            "screen_recording": bool(self.Q.CGPreflightScreenCaptureAccess()),
            "accessibility": bool(self.AX.AXIsProcessTrusted()),
            "post_events": bool(self.Q.CGPreflightPostEventAccess()),
            "input_monitoring": bool(self.Q.CGPreflightListenEventAccess()),
            "emergency_hotkey": self.hotkey_ready.is_set(),
        }

    def request_permissions(self):
        self.AX.AXIsProcessTrustedWithOptions({self.AX.kAXTrustedCheckOptionPrompt: True})
        self.Q.CGRequestScreenCaptureAccess()
        self.Q.CGRequestPostEventAccess()
        self.Q.CGRequestListenEventAccess()

    def check_session(self):
        session = self.Q.CGSessionCopyCurrentDictionary()
        if (
            not session
            or not session.get(self.Q.kCGSessionOnConsoleKey, False)
            or not session.get(self.Q.kCGSessionLoginDoneKey, False)
            or session.get("CGSSessionScreenIsLocked", False)
        ):
            raise ControlError(
                "desktop_unavailable", "macOS desktop session is unavailable or locked"
            )

    def check_ready(self):
        self.check_stop()
        self.check_session()
        permission = self.permissions()
        if not all(
            permission[k]
            for k in ("accessibility", "post_events", "input_monitoring", "emergency_hotkey")
        ):
            raise ControlError(
                "permission_required",
                "Enable Accessibility and Input Monitoring for MousePilot in System Settings > Privacy & Security; wait for the emergency hotkey to become ready",
            )

    def check_capture_ready(self):
        self.check_session()
        if not self.Q.CGPreflightScreenCaptureAccess():
            raise ControlError(
                "permission_required",
                "Enable Screen & System Audio Recording for MousePilot in System Settings > Privacy & Security, then relaunch MousePilot if requested",
            )

    def info(self):
        error, ids, count = self.Q.CGGetActiveDisplayList(64, None, None)
        if error or not count:
            raise ControlError("desktop_unavailable", "Could not enumerate macOS displays")
        primary = self.Q.CGMainDisplayID()
        displays = []
        for display_id in ids[:count]:
            rect = self.Q.CGDisplayBounds(display_id)
            mode = self.Q.CGDisplayCopyDisplayMode(display_id)
            pixels = [
                self.Q.CGDisplayModeGetPixelWidth(mode),
                self.Q.CGDisplayModeGetPixelHeight(mode),
            ]
            serial = self.Q.CGDisplaySerialNumber(display_id)
            stable_name = f"mac-display-{self.Q.CGDisplayVendorNumber(display_id)}-{self.Q.CGDisplayModelNumber(display_id)}-{serial or display_id}"
            displays.append(
                {
                    "id": "primary" if display_id == primary else str(display_id),
                    "native_id": int(display_id),
                    "device_name": stable_name,
                    "primary": display_id == primary,
                    "bounds": rect_bounds(rect),
                    "pixel_size": pixels,
                    "scale_percent": round(100 * pixels[0] / rect.size.width),
                }
            )
        displays.sort(key=lambda d: (not d["primary"], d["id"]))
        position = self.Q.CGEventGetLocation(self.Q.CGEventCreate(None))
        return {
            "platform": "macos",
            "coordinate_space": "desktop-points",
            "displays": displays,
            "bounds": displays[0]["bounds"],
            "cursor": [round(position.x), round(position.y)],
            "permissions": self.permissions(),
            "emergency_hotkey": self.emergency_hotkey,
        }

    def capture(self, bounds):
        from PIL import Image

        self.check_capture_ready()
        display = next(
            (
                d
                for d in self.info()["displays"]
                if d["bounds"][0] <= bounds[0]
                and d["bounds"][1] <= bounds[1]
                and d["bounds"][2] >= bounds[2]
                and d["bounds"][3] >= bounds[3]
            ),
            None,
        )
        if display is None:
            raise ControlError(
                "display_changed", "Capture rectangle no longer belongs to one display"
            )
        complete = threading.Event()
        result = {}

        def content_ready(content, error):
            result.update(content=content, error=error)
            complete.set()

        self.SC.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(
            False, True, content_ready
        )
        if not complete.wait(10) or result.get("error") or not result.get("content"):
            raise ControlError(
                "capture_failed",
                "ScreenCaptureKit could not enumerate displays; check Screen Recording permission",
            )
        screen = next(
            (d for d in result["content"].displays() if d.displayID() == display["native_id"]), None
        )
        if screen is None:
            raise ControlError("display_changed", "ScreenCaptureKit display disappeared")
        filter_ = self.SC.SCContentFilter.alloc().initWithDisplay_excludingWindows_(screen, [])
        config = self.SC.SCStreamConfiguration.alloc().init()
        left, top, right, bottom = bounds
        dl, dt, dr, db = display["bounds"]
        config.setWidth_(max(1, math.ceil((right - left) * display["pixel_size"][0] / (dr - dl))))
        config.setHeight_(max(1, math.ceil((bottom - top) * display["pixel_size"][1] / (db - dt))))
        config.setSourceRect_(
            self.Q.CGRectMake(
                left - display["bounds"][0], top - display["bounds"][1], right - left, bottom - top
            )
        )
        config.setShowsCursor_(False)
        complete.clear()
        result.clear()

        def image_ready(image, error):
            result.update(image=image, error=error)
            complete.set()

        self.SC.SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
            filter_, config, image_ready
        )
        if not complete.wait(10) or result.get("error") or not result.get("image"):
            raise ControlError(
                "capture_failed",
                "ScreenCaptureKit screenshot failed; check permissions and desktop state",
            )
        data = self.Foundation.NSMutableData.data()
        destination = self.Q.CGImageDestinationCreateWithData(data, "public.png", 1, None)
        self.Q.CGImageDestinationAddImage(destination, result["image"], None)
        if not self.Q.CGImageDestinationFinalize(destination):
            raise ControlError("capture_failed", "Could not encode macOS screenshot")
        return Image.open(io.BytesIO(bytes(data))).convert("RGB")

    def check_stop(self):
        if self.stopped.is_set():
            raise ControlError("paused", "Desktop input is paused; resume explicitly")

    def _flags(self, excluding=None):
        mapping = {
            59: self.Q.kCGEventFlagMaskControl,
            58: self.Q.kCGEventFlagMaskAlternate,
            56: self.Q.kCGEventFlagMaskShift,
            55: self.Q.kCGEventFlagMaskCommand,
        }
        flags = 0
        for code, text in self.held_keys:
            if (code, text) != excluding:
                flags |= mapping.get(code, 0)
        return flags

    def _post(self, event, flags=None):
        if event is None:
            raise ControlError("input_failed", "Could not create macOS input event")
        self.Q.CGEventSetFlags(event, self._flags() if flags is None else flags)
        self.Q.CGEventPost(self.Q.kCGHIDEventTap, event)

    def _mouse_event(self, position, button, down=None):
        constants = {
            "left": (
                self.Q.kCGMouseButtonLeft,
                self.Q.kCGEventLeftMouseDown,
                self.Q.kCGEventLeftMouseUp,
                self.Q.kCGEventLeftMouseDragged,
            ),
            "right": (
                self.Q.kCGMouseButtonRight,
                self.Q.kCGEventRightMouseDown,
                self.Q.kCGEventRightMouseUp,
                self.Q.kCGEventRightMouseDragged,
            ),
            "middle": (
                self.Q.kCGMouseButtonCenter,
                self.Q.kCGEventOtherMouseDown,
                self.Q.kCGEventOtherMouseUp,
                self.Q.kCGEventOtherMouseDragged,
            ),
        }
        number, press, release, drag = constants[button]
        return self.Q.CGEventCreateMouseEvent(
            None, drag if down is None else press if down else release, position, number
        )

    def move(self, x, y, verify=True):
        with self.native_lock:
            self.check_stop()
            event = (
                self._mouse_event((x, y), next(iter(self.held_buttons)))
                if self.held_buttons
                else self.Q.CGEventCreateMouseEvent(
                    None, self.Q.kCGEventMouseMoved, (x, y), self.Q.kCGMouseButtonLeft
                )
            )
            self._post(event)
            deadline = time.monotonic() + 0.2
            while True:
                actual = self.info()["cursor"]
                if not verify or actual == [x, y]:
                    return actual
                self.check_stop()
                if time.monotonic() > deadline:
                    raise ControlError("cursor_mismatch", f"Requested {[x, y]}, observed {actual}")
                time.sleep(0.005)

    def button(self, button, down, count=1):
        with self.native_lock:
            if not down and button not in self.held_buttons:
                return
            if down:
                self.check_stop()
                self.held_buttons.add(button)
            position = self.Q.CGEventGetLocation(self.Q.CGEventCreate(None))
            event = self._mouse_event(position, button, down)
            self.Q.CGEventSetIntegerValueField(event, self.Q.kCGMouseEventClickState, count)
            self._post(event)
            if not down:
                self.held_buttons.discard(button)

    def click(self, button, count=1):
        for index in range(count):
            try:
                self.button(button, True, index + 1)
            finally:
                self.button(button, False, index + 1)
            if index + 1 < count:
                self.stopped.wait(0.05)

    def scroll(self, steps, axis="vertical"):
        with self.native_lock:
            self.check_stop()
            event = self.Q.CGEventCreateScrollWheelEvent(
                None,
                self.Q.kCGScrollEventUnitLine,
                2,
                steps if axis == "vertical" else 0,
                -steps if axis == "horizontal" else 0,
            )
            self._post(event)

    def key(self, code, down, text=None):
        with self.native_lock:
            entry = (code, text)
            if not down and entry not in self.held_keys:
                return
            if down:
                self.check_stop()
                self.held_keys.add(entry)
            event = self.Q.CGEventCreateKeyboardEvent(None, code, down)
            if text is not None:
                self.Q.CGEventKeyboardSetUnicodeString(
                    event, len(text.encode("utf-16-le")) // 2, text
                )
            self._post(event, self._flags(excluding=entry) if not down else None)
            if not down:
                self.held_keys.discard(entry)

    def type_text(self, text):
        utf16_units(text)
        for char in text:
            try:
                self.key(0, True, char)
            finally:
                self.key(0, False, char)

    def press_key(self, name):
        code = key_code(name)
        try:
            self.key(code, True)
        finally:
            self.key(code, False)

    def hotkey(self, keys):
        names = [ALIASES.get(k.lower(), k.lower()) for k in keys]
        if len(set(names)) != len(names) or any(
            k not in ("ctrl", "alt", "shift", "cmd") for k in names[:-1]
        ):
            raise ValueError('Use unique modifiers followed by a key, e.g. ["cmd", "a"]')
        codes = [key_code(k) for k in names]
        try:
            for code in codes:
                self.key(code, True)
        finally:
            self.release_all()

    def drag(self, start, end, duration, button):
        self.move(*start)
        try:
            self.button(button, True)
            steps = max(2, round(duration / 0.01))
            started = time.monotonic()
            for i in range(1, steps + 1):
                self.move(
                    *(round(a + (b - a) * i / steps) for a, b in zip(start, end)), verify=i == steps
                )
                self.stopped.wait(max(0, started + duration * i / steps - time.monotonic()))
                self.check_stop()
        finally:
            self.button(button, False)

    def release_all(self):
        with self.native_lock:
            errors = []
            for button in list(self.held_buttons):
                try:
                    self.button(button, False)
                except Exception as exc:
                    errors.append(str(exc))
            for code, text in sorted(self.held_keys, key=lambda item: item[0] in (55, 56, 58, 59)):
                try:
                    self.key(code, False, text)
                except Exception as exc:
                    errors.append(str(exc))
            if errors:
                raise ControlError("cleanup_failed", "; ".join(errors))

    def _attribute(self, element, name, default=None):
        error, value = self.AX.AXUIElementCopyAttributeValue(element, name, None)
        return default if error else value

    def _value(self, value, kind):
        if value is None:
            return None
        success, result = self.AX.AXValueGetValue(value, kind, None)
        return result if success else None

    def list_windows(self):
        self.check_session()
        if not self.AX.AXIsProcessTrusted():
            raise ControlError(
                "permission_required", "Enable Accessibility for MousePilot to inspect windows"
            )
        front = self.AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        windows = []
        for app in self.AppKit.NSWorkspace.sharedWorkspace().runningApplications():
            if (
                app.isTerminated()
                or app.activationPolicy() == self.AppKit.NSApplicationActivationPolicyProhibited
            ):
                continue
            pid = app.processIdentifier()
            element = self.AX.AXUIElementCreateApplication(pid)
            self.AX.AXUIElementSetMessagingTimeout(element, 0.5)
            focused = self._attribute(element, self.AX.kAXFocusedWindowAttribute)
            for window in self._attribute(element, self.AX.kAXWindowsAttribute, []):
                title = str(self._attribute(window, self.AX.kAXTitleAttribute, ""))
                pos = self._value(
                    self._attribute(window, self.AX.kAXPositionAttribute),
                    self.AX.kAXValueCGPointType,
                )
                size = self._value(
                    self._attribute(window, self.AX.kAXSizeAttribute), self.AX.kAXValueCGSizeType
                )
                if not title or pos is None or size is None:
                    continue
                launched = app.launchDate()
                windows.append(
                    {
                        "title": title,
                        "process_id": pid,
                        "class_name": str(
                            self._attribute(window, self.AX.kAXSubroleAttribute, "AXWindow")
                        ),
                        "bounds": [
                            round(pos.x),
                            round(pos.y),
                            round(pos.x + size.width),
                            round(pos.y + size.height),
                        ],
                        "minimized": bool(
                            self._attribute(window, self.AX.kAXMinimizedAttribute, False)
                        ),
                        "foreground": bool(
                            front
                            and front.processIdentifier() == pid
                            and focused
                            and self.CF.CFEqual(focused, window)
                        ),
                        "_identity": {
                            "pid": pid,
                            "window": window,
                            "title": title,
                            "launched": launched.timeIntervalSince1970() if launched else None,
                        },
                    }
                )
                if len(windows) >= 512:
                    return windows
        return windows

    def focus_window(self, identity, allow_input=True):
        self.check_stop()
        app = self.AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(
            identity["pid"]
        )
        if not app or app.isTerminated():
            raise ControlError("stale_window", "Application exited; list windows again")
        launched = app.launchDate()
        if (launched.timeIntervalSince1970() if launched else None) != identity["launched"]:
            raise ControlError("stale_window", "Application identity changed; list windows again")
        element = self.AX.AXUIElementCreateApplication(identity["pid"])
        window = next(
            (
                w
                for w in self._attribute(element, self.AX.kAXWindowsAttribute, [])
                if self.CF.CFEqual(w, identity["window"])
            ),
            None,
        )
        if (
            window is None
            or str(self._attribute(window, self.AX.kAXTitleAttribute, "")) != identity["title"]
        ):
            raise ControlError("stale_window", "Window closed or changed; list windows again")
        self.AX.AXUIElementSetAttributeValue(window, self.AX.kAXMinimizedAttribute, False)
        self.AX.AXUIElementPerformAction(window, self.AX.kAXRaiseAction)
        self.AX.AXUIElementSetAttributeValue(element, self.AX.kAXFocusedWindowAttribute, window)
        from .macos_ui import call_main

        call_main(
            lambda: app.activateWithOptions_(self.AppKit.NSApplicationActivateIgnoringOtherApps)
        )
        deadline = time.monotonic() + 1
        while True:
            front = self.AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
            focused = self._attribute(element, self.AX.kAXFocusedWindowAttribute)
            if (
                front
                and front.processIdentifier() == identity["pid"]
                and focused
                and self.CF.CFEqual(focused, window)
            ):
                return
            self.check_stop()
            if time.monotonic() > deadline:
                raise ControlError(
                    "focus_denied", "macOS did not confirm the requested foreground window"
                )
            self.stopped.wait(0.02)

    def start_emergency_hotkey(self):
        def listen():
            Q, CF = self.Q, self.CF
            while not self.listener_done.wait(0.5):
                if not Q.CGPreflightListenEventAccess():
                    continue

                def callback(proxy, type_, event, context):
                    if type_ in (Q.kCGEventTapDisabledByTimeout, Q.kCGEventTapDisabledByUserInput):
                        Q.CGEventTapEnable(self.tap, True)
                    elif type_ == Q.kCGEventKeyDown:
                        flags = Q.CGEventGetFlags(event)
                        required = (
                            Q.kCGEventFlagMaskControl
                            | Q.kCGEventFlagMaskAlternate
                            | Q.kCGEventFlagMaskShift
                        )
                        if (
                            Q.CGEventGetIntegerValueField(event, Q.kCGKeyboardEventKeycode) == 103
                            and flags & required == required
                        ):
                            self.stopped.set()
                            threading.Thread(target=self._emergency_release, daemon=True).start()
                    return event

                mask = 1 << Q.kCGEventKeyDown
                self.tap = Q.CGEventTapCreate(
                    Q.kCGSessionEventTap,
                    Q.kCGHeadInsertEventTap,
                    Q.kCGEventTapOptionListenOnly,
                    mask,
                    callback,
                    None,
                )
                if self.tap is None:
                    continue
                self._tap_callback = callback
                self.hotkey_loop = CF.CFRunLoopGetCurrent()
                source = CF.CFMachPortCreateRunLoopSource(None, self.tap, 0)
                CF.CFRunLoopAddSource(self.hotkey_loop, source, CF.kCFRunLoopCommonModes)
                Q.CGEventTapEnable(self.tap, True)
                self.hotkey_ready.set()
                CF.CFRunLoopRun()
                self.hotkey_ready.clear()
                return

        threading.Thread(target=listen, daemon=True, name="macos-emergency-hotkey").start()

    def _emergency_release(self):
        try:
            self.release_all()
        except Exception as exc:
            print(f"Emergency release failed: {exc}", file=sys.stderr)

    def close(self):
        self.listener_done.set()
        if self.hotkey_loop:
            self.CF.CFRunLoopStop(self.hotkey_loop)
