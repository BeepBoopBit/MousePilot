"""Win32 capture and input. Must run in the interactive user's desktop session."""

import base64
import ctypes as c
import json
import subprocess
import sys
import threading
import time
from ctypes import wintypes as w
from pathlib import Path

from .protocol import ControlError
from .text import utf16_units

KEYS = {
    "enter": 13,
    "tab": 9,
    "escape": 27,
    "backspace": 8,
    "delete": 46,
    "left": 37,
    "up": 38,
    "right": 39,
    "down": 40,
    "home": 36,
    "end": 35,
    "pageup": 33,
    "pagedown": 34,
    "space": 32,
    "ctrl": 17,
    "alt": 18,
    "shift": 16,
    "win": 91,
}
EXTENDED = {33, 34, 35, 36, 37, 38, 39, 40, 46, 91}
KEYS.update({f"f{i}": 111 + i for i in range(1, 12)})
BUTTONS = {"left": (2, 4), "right": (8, 16), "middle": (32, 64)}


class MouseInput(c.Structure):
    _fields_ = [
        ("dx", w.LONG),
        ("dy", w.LONG),
        ("mouseData", w.DWORD),
        ("dwFlags", w.DWORD),
        ("time", w.DWORD),
        ("dwExtraInfo", c.c_size_t),
    ]


class KeyboardInput(c.Structure):
    _fields_ = [
        ("wVk", w.WORD),
        ("wScan", w.WORD),
        ("dwFlags", w.DWORD),
        ("time", w.DWORD),
        ("dwExtraInfo", c.c_size_t),
    ]


class InputUnion(c.Union):
    _fields_ = [("mi", MouseInput), ("ki", KeyboardInput)]


class Input(c.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", w.DWORD), ("u", InputUnion)]


class MonitorInfo(c.Structure):
    _fields_ = [
        ("cbSize", w.DWORD),
        ("rcMonitor", w.RECT),
        ("rcWork", w.RECT),
        ("dwFlags", w.DWORD),
        ("szDevice", w.WCHAR * 32),
    ]


def key_code(key):
    key = key.lower()
    if key in KEYS:
        return KEYS[key]
    if len(key) == 1 and key.isascii() and key.isalnum():
        return ord(key.upper())
    raise ValueError(f"Unsupported key: {key}")


class Desktop:
    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("Desktop backend requires Windows; use --device or --url from Linux")
        self.api = c.WinDLL("user32", use_last_error=True)
        self.api.SetThreadDpiAwarenessContext.argtypes = [c.c_void_p]
        self.api.SetThreadDpiAwarenessContext.restype = c.c_void_p
        self.api.SendInput.argtypes = [w.UINT, c.POINTER(Input), c.c_int]
        self.api.SendInput.restype = w.UINT
        self.api.GetCursorPos.argtypes = [c.POINTER(w.POINT)]
        self.api.SetCursorPos.argtypes = [c.c_int, c.c_int]
        self.api.GetMonitorInfoW.argtypes = [w.HANDLE, c.POINTER(MonitorInfo)]
        self.api.OpenInputDesktop.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.api.OpenInputDesktop.restype = w.HANDLE
        self.api.CloseDesktop.argtypes = [w.HANDLE]
        self.api.GetUserObjectInformationW.argtypes = [
            w.HANDLE,
            c.c_int,
            c.c_void_p,
            w.DWORD,
            c.POINTER(w.DWORD),
        ]
        self.api.WindowFromPoint.argtypes = [w.POINT]
        self.api.WindowFromPoint.restype = w.HWND
        self.api.GetAncestor.argtypes = [w.HWND, w.UINT]
        self.api.GetAncestor.restype = w.HWND
        self.api.SendMessageTimeoutW.argtypes = [
            w.HWND,
            w.UINT,
            c.c_size_t,
            c.c_ssize_t,
            w.UINT,
            w.UINT,
            c.POINTER(c.c_size_t),
        ]
        self.api.SendMessageTimeoutW.restype = c.c_ssize_t
        self.api.GetForegroundWindow.restype = w.HWND
        for name in ("IsWindow", "IsWindowVisible", "IsIconic", "SetForegroundWindow"):
            getattr(self.api, name).argtypes = [w.HWND]
            getattr(self.api, name).restype = w.BOOL
        self.api.GetWindowTextLengthW.argtypes = [w.HWND]
        self.api.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
        self.api.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
        self.api.GetWindowRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
        self.api.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
        self.api.GetWindowThreadProcessId.restype = w.DWORD
        self.api.ShowWindow.argtypes = [w.HWND, c.c_int]
        self.shcore = c.WinDLL("shcore", use_last_error=True)
        self.shcore.GetScaleFactorForMonitor.argtypes = [w.HANDLE, c.POINTER(c.c_int)]
        self.shcore.GetScaleFactorForMonitor.restype = c.c_long
        self.stopped = threading.Event()
        self.native_lock = threading.RLock()
        self.held_keys = set()
        self.held_buttons = set()
        self.activate()

    def activate(self):
        if not self.api.SetThreadDpiAwarenessContext(c.c_void_p(-4)):
            raise c.WinError(c.get_last_error())

    def check_ready(self):
        if self.stopped.is_set():
            raise ControlError("paused", "Desktop input is paused; resume explicitly")
        self.check_capture_ready()

    def check_capture_ready(self):
        handle = self.api.OpenInputDesktop(0, False, 1)
        if not handle:
            raise ControlError("desktop_unavailable", "Input desktop is inaccessible or locked")
        try:
            name = c.create_unicode_buffer(256)
            size = w.DWORD()
            if not self.api.GetUserObjectInformationW(
                handle, 2, name, c.sizeof(name), c.byref(size)
            ):
                raise c.WinError(c.get_last_error())
            if name.value.lower() != "default":
                raise ControlError(
                    "desktop_unavailable",
                    "Secure or non-default input desktop is active",
                )
        finally:
            self.api.CloseDesktop(handle)

    def info(self):
        p = w.POINT()
        if not self.api.GetCursorPos(c.byref(p)):
            raise c.WinError(c.get_last_error())
        displays = []
        errors = []
        callback_type = c.WINFUNCTYPE(w.BOOL, w.HANDLE, w.HDC, c.POINTER(w.RECT), w.LPARAM)

        def enumerate_monitor(handle, dc, rect, data):
            info = MonitorInfo(cbSize=c.sizeof(MonitorInfo))
            if not self.api.GetMonitorInfoW(handle, c.byref(info)):
                errors.append(c.get_last_error())
                return False
            r = info.rcMonitor
            primary = bool(info.dwFlags & 1)
            scale = c.c_int()
            if self.shcore.GetScaleFactorForMonitor(handle, c.byref(scale)) != 0:
                errors.append(0)
                return False
            displays.append(
                {
                    "id": "primary" if primary else info.szDevice,
                    "device_name": info.szDevice,
                    "primary": primary,
                    "scale_percent": scale.value,
                    "bounds": [r.left, r.top, r.right, r.bottom],
                }
            )
            return True

        self.api.EnumDisplayMonitors.argtypes = [
            w.HDC,
            c.POINTER(w.RECT),
            callback_type,
            w.LPARAM,
        ]
        if (
            not self.api.EnumDisplayMonitors(None, None, callback_type(enumerate_monitor), 0)
            or errors
        ):
            raise RuntimeError("Could not enumerate displays")
        displays.sort(key=lambda d: (not d["primary"], d["id"]))
        return {
            "displays": displays,
            "bounds": displays[0]["bounds"],
            "cursor": [p.x, p.y],
            "coordinate_space": "physical-pixels",
        }

    def capture(self, bounds):
        from PIL import ImageGrab

        self.check_capture_ready()
        return ImageGrab.grab(bbox=tuple(bounds), all_screens=True)

    def check_stop(self):
        if self.stopped.is_set():
            raise ControlError("paused", "Input stopped; inspect the UI before continuing")

    def move(self, x, y, verify=True):
        with self.native_lock:
            self.check_stop()
            if not self.api.SetCursorPos(x, y):
                raise ControlError(
                    "input_blocked",
                    f"Windows refused cursor movement (SetCursorPos, error {c.get_last_error()}). No click was sent. Check the input desktop and foreground app privileges; do not retry different coordinates.",
                )
            actual = self.info()["cursor"]
            if verify and actual != [x, y]:
                raise ControlError("cursor_mismatch", f"Requested {[x, y]}, observed {actual}")
            return actual

    def inject(self, event):
        if self.api.SendInput(1, c.byref(event), c.sizeof(Input)) != 1:
            raise ControlError("input_failed", "Input injection failed; inspect before retrying")

    def button(self, button, down):
        with self.native_lock:
            if not down and button not in self.held_buttons:
                return
            if down:
                self.check_stop()
                self.held_buttons.add(button)
            self.inject(
                Input(
                    type=0,
                    mi=MouseInput(0, 0, 0, BUTTONS[button][0 if down else 1], 0, 0),
                )
            )
            if not down:
                self.held_buttons.discard(button)

    def click(self, button, count=1):
        for i in range(count):
            try:
                self.button(button, True)
            finally:
                self.button(button, False)
            if i + 1 < count:
                if self.stopped.wait(0.05):
                    self.check_stop()

    def scroll(self, steps, axis="vertical"):
        with self.native_lock:
            self.check_stop()
            self.inject(
                Input(
                    type=0,
                    mi=MouseInput(
                        0,
                        0,
                        (steps * 120) & 0xFFFFFFFF,
                        0x1000 if axis == "horizontal" else 0x800,
                        0,
                        0,
                    ),
                )
            )

    def key(self, code, down, unicode=False):
        with self.native_lock:
            entry = (code, unicode)
            if not down and entry not in self.held_keys:
                return
            if down:
                self.check_stop()
                self.held_keys.add(entry)
            flags = (4 if unicode else (1 if code in EXTENDED else 0)) | (0 if down else 2)
            self.inject(
                Input(
                    type=1,
                    ki=KeyboardInput(0 if unicode else code, code if unicode else 0, flags, 0, 0),
                )
            )
            if not down:
                self.held_keys.discard(entry)

    def type_text(self, text):
        for unit in utf16_units(text):
            try:
                self.key(unit, True, unicode=True)
            finally:
                self.key(unit, False, unicode=True)

    def press_key(self, key):
        code = key_code(key)
        try:
            self.key(code, True)
        finally:
            self.key(code, False)

    def hotkey(self, keys):
        names = [k.lower() for k in keys]
        if len(set(names)) != len(names) or any(
            k not in ("ctrl", "alt", "shift", "win") for k in names[:-1]
        ):
            raise ValueError('Use unique modifiers followed by one key, e.g. ["ctrl", "a"]')
        codes = [key_code(k) for k in names]
        try:
            for code in codes:
                self.key(code, True)
        finally:
            for code in reversed(codes):
                if (code, False) in self.held_keys:
                    self.key(code, False)

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
        errors = []
        with self.native_lock:
            for button in list(self.held_buttons):
                try:
                    self.button(button, False)
                except Exception as exc:
                    errors.append(str(exc))
            for code, unicode in list(self.held_keys):
                try:
                    self.key(code, False, unicode)
                except Exception as exc:
                    errors.append(str(exc))
        if errors:
            raise ControlError("cleanup_failed", "; ".join(errors))

    def start_emergency_hotkey(self):
        ready = threading.Event()
        failures = []

        def listen():
            if not self.api.RegisterHotKey(None, 1, 0x4000 | 2 | 1 | 4, 0x7A):
                # Ctrl+Alt+Shift+F11. F12 is reserved by Windows.
                failures.append("Could not register Ctrl+Alt+Shift+F11 emergency hotkey")
                ready.set()
                return
            ready.set()
            message = w.MSG()
            try:
                while self.api.GetMessageW(c.byref(message), None, 0, 0) > 0:
                    if message.message == 0x312:
                        self.stopped.set()
                        try:
                            self.release_all()
                        except Exception as exc:
                            print(
                                f"Emergency input cleanup failed: {exc}",
                                file=sys.stderr,
                            )
            finally:
                self.api.UnregisterHotKey(None, 1)

        threading.Thread(target=listen, daemon=True, name="emergency-hotkey").start()
        if not ready.wait(5) or failures:
            raise RuntimeError(
                failures[0] if failures else "Emergency hotkey registration timed out"
            )

    def window_info(self, handle):
        if not self.api.IsWindow(handle) or not self.api.IsWindowVisible(handle):
            return None
        length = min(4096, self.api.GetWindowTextLengthW(handle))
        if length <= 0:
            return None
        title = c.create_unicode_buffer(length + 1)
        if not self.api.GetWindowTextW(handle, title, length + 1):
            return None
        class_name = c.create_unicode_buffer(256)
        if not self.api.GetClassNameW(handle, class_name, 256):
            return None
        rect = w.RECT()
        if not self.api.GetWindowRect(handle, c.byref(rect)):
            return None
        process_id = w.DWORD()
        thread_id = self.api.GetWindowThreadProcessId(handle, c.byref(process_id))
        identity = {
            "handle": handle,
            "process_id": process_id.value,
            "thread_id": thread_id,
            "class_name": class_name.value,
            "title": title.value,
        }
        return {
            "title": title.value,
            "process_id": process_id.value,
            "class_name": class_name.value,
            "bounds": [rect.left, rect.top, rect.right, rect.bottom],
            "minimized": bool(self.api.IsIconic(handle)),
            "foreground": self.api.GetForegroundWindow() == handle,
            "_identity": identity,
        }

    def list_windows(self):
        self.check_capture_ready()
        windows = []
        errors = []
        callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

        def enumerate_window(handle, data):
            try:
                window = self.window_info(handle)
                if window:
                    windows.append(window)
                return len(windows) < 512
            except Exception as exc:
                errors.append(str(exc))
                return False

        self.api.EnumWindows.argtypes = [callback_type, w.LPARAM]
        success = self.api.EnumWindows(callback_type(enumerate_window), 0)
        if errors or (not success and len(windows) < 512):
            raise ControlError("window_enumeration_failed", "Could not enumerate desktop windows")
        return windows

    def wait_foreground(self, handle, timeout=0.5):
        deadline = time.monotonic() + timeout
        while self.api.GetForegroundWindow() != handle:
            self.check_stop()
            if time.monotonic() >= deadline:
                return False
            self.stopped.wait(0.02)
        self.check_stop()
        return True

    def activation_hit(self, handle, point):
        x, y = point
        if not (-32768 <= x <= 32767 and -32768 <= y <= 32767):
            return None
        owner = self.api.WindowFromPoint(w.POINT(x, y))
        if not owner or self.api.GetAncestor(owner, 2) != handle:
            return None
        result = c.c_size_t()
        packed = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
        if not self.api.SendMessageTimeoutW(handle, 0x84, 0, packed, 3, 75, c.byref(result)):
            return None
        # Caption or straight resize borders: never content, buttons, or corners.
        return result.value if result.value in (2, 10, 11, 12, 15) else None

    def activation_point(self, handle, bounds):
        left, top, right, bottom = bounds
        ratios = (0.5, 0.35, 0.65)
        points = [
            (left + int((right - left) * ratio), top + offset)
            for offset in (16, 24, 2, 4)
            for ratio in ratios
        ]
        points += [
            (left + int((right - left) * ratio), bottom - offset)
            for offset in (3, 5)
            for ratio in ratios
        ]
        points += [
            (x, top + int((bottom - top) * ratio))
            for x in (left + 2, right - 3)
            for ratio in ratios
        ]
        for point in points:
            if not (left <= point[0] < right and top <= point[1] < bottom):
                continue
            self.check_stop()
            hit = self.activation_hit(handle, point)
            if hit is not None:
                return point, hit
        return None

    def focus_window(self, identity, allow_input=True):
        with self.native_lock:
            self.check_stop()
            handle = identity["handle"]
            current = self.window_info(handle)
            if current is None or current["_identity"] != identity:
                raise ControlError(
                    "stale_window", "Window closed or changed; call list_windows again"
                )
            if current["minimized"]:
                self.api.ShowWindow(handle, 9)
            if self.api.GetForegroundWindow() == handle:
                return {"focus_method": "already_foreground", "activation_click": False}
            self.api.SetForegroundWindow(handle)
            if self.wait_foreground(handle):
                return {"focus_method": "api", "activation_click": False}
            if allow_input:
                current = self.window_info(handle)
                if current is None or current["_identity"] != identity or current["minimized"]:
                    raise ControlError(
                        "stale_window", "Window changed during activation; list windows again"
                    )
                bounds = list(current["bounds"])
                candidate = self.activation_point(handle, bounds)
                if candidate:
                    point, hit = candidate
                    self.move(*point)
                    current = self.window_info(handle)
                    if (
                        current is None
                        or current["_identity"] != identity
                        or current["bounds"] != bounds
                        or current["minimized"]
                        or self.activation_hit(handle, point) != hit
                    ):
                        raise ControlError(
                            "focus_denied",
                            "Activation target moved or became covered; no click was sent. Capture the monitor and inspect before retrying.",
                        )
                    if self.api.GetForegroundWindow() == handle:
                        return {"focus_method": "already_foreground", "activation_click": False}
                    self.click("left", 1)
                    if self.wait_foreground(handle, timeout=0.75):
                        return {
                            "focus_method": "verified_title_bar_click"
                            if hit == 2
                            else "verified_border_click",
                            "activation_click": True,
                            "activation_target_desktop": list(point),
                        }
                    raise ControlError(
                        "focus_denied",
                        "Activation click was sent but foreground focus was not confirmed. Inspect the current screen; do not repeat focus_window blindly.",
                    )
                # A fully covered window has no safe frame point to click. Use one
                # standard Windows window-switch shortcut, then request the exact target.
                self.hotkey(["alt", "escape"])
                if self.stopped.wait(0.1):
                    self.check_stop()
                current = self.window_info(handle)
                if current is None or current["_identity"] != identity:
                    raise ControlError(
                        "stale_window",
                        "Window changed after activation shortcut; inspect the screen",
                    )
                self.api.SetForegroundWindow(handle)
                if self.wait_foreground(handle, timeout=0.75):
                    return {
                        "focus_method": "keyboard_assisted_api",
                        "activation_click": False,
                        "activation_shortcut": ["alt", "escape"],
                    }
                raise ControlError(
                    "focus_denied",
                    "Activation shortcut was sent but foreground focus was not confirmed. Inspect the current screen; do not repeat focus_window blindly.",
                )
            raise ControlError(
                "focus_denied",
                "Windows did not grant foreground focus. Input fallbacks are disabled; no activation click or shortcut was sent. Use current_screen on the target monitor, visually identify a safe activation point, preview_target then click; verify focus before capture_window. Do not repeatedly call focus_window.",
            )

    def validate_element_window(self, identity):
        self.check_capture_ready()
        current = self.window_info(identity["handle"])
        if current is None or current["_identity"] != identity:
            raise ControlError(
                "stale_window", "Window closed or identity changed; list windows and elements again"
            )
        if current["minimized"] or not current["foreground"]:
            raise ControlError(
                "window_not_foreground",
                "Focus the target window, take a fresh screenshot, then list_elements again",
            )
        return current

    def _uia(self, args):
        payload = base64.b64encode(json.dumps(args).encode()).decode()
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(Path(__file__).with_name("uia.ps1")),
                    "-Request",
                    payload,
                ],
                capture_output=True,
                timeout=7,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            raise ControlError(
                "accessibility_timeout",
                "UI Automation provider did not respond in time. No input was sent.",
            ) from None
        except OSError:
            raise ControlError(
                "accessibility_unavailable",
                "Windows PowerShell UI Automation worker is unavailable",
            ) from None
        try:
            response = json.loads(result.stdout.decode("utf-8-sig"))
        except (ValueError, UnicodeError):
            raise ControlError(
                "accessibility_unavailable", "UI Automation worker failed; no input was sent"
            ) from None
        if not isinstance(response, dict) or response.get("error"):
            raise ControlError(
                "accessibility_unavailable",
                "UI Automation could not inspect/revalidate the control; it may be changed, covered, elevated, or unsupported. No input was sent. Do not guess coordinates from window bounds; use capture_window and preview_target, or stop if the target cannot be identified.",
            )
        return response

    def list_elements(self, identity, limit):
        self.validate_element_window(identity)
        result = self._uia(
            {
                "operation": "list",
                "handle": identity["handle"],
                "process_id": identity["process_id"],
                "limit": limit,
            }
        )
        self.validate_element_window(identity)
        return result

    def validate_element(self, window, identity, point):
        self._uia(
            {
                "operation": "validate",
                "handle": window["handle"],
                "process_id": window["process_id"],
                "identity": identity,
                "point": list(point),
            }
        )
        self.validate_element_window(window)
