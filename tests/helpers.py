import threading

from PIL import Image

from mousepilot.protocol import ControlError


class FakeDesktop:
    def __init__(self):
        self.stopped = threading.Event()
        self.displays = [{"id": "primary", "primary": True, "bounds": [0, 0, 1920, 1200]}]
        self.cursor = [0, 0]
        self.actions = []
        self.drag_started = threading.Event()
        self.window = {
            "title": "Test editor",
            "process_id": 42,
            "class_name": "test",
            "bounds": [100, 100, 500, 500],
            "foreground": False,
            "minimized": False,
            "_identity": {"handle": 1, "process_id": 42, "title": "Test editor"},
        }

    def activate(self):
        pass

    def info(self):
        return {
            "displays": self.displays,
            "bounds": self.displays[0]["bounds"],
            "cursor": self.cursor,
        }

    def capture(self, bounds):
        return Image.new("RGB", (bounds[2] - bounds[0], bounds[3] - bounds[1]), "white")

    def check_ready(self):
        if self.stopped.is_set():
            raise ControlError("paused", "Paused")

    def move(self, x, y):
        self.cursor = [x, y]
        self.actions.append(("move", x, y))

    def click(self, button, count):
        self.actions.append(("click", button, count))

    def type_text(self, text):
        self.actions.append(("type", text))

    def release_all(self):
        pass

    def drag(self, start, end, duration, button):
        self.drag_started.set()
        if self.stopped.wait(3):
            raise ControlError("paused", "Input stopped")
        raise AssertionError("Stop did not interrupt the test drag")

    def list_windows(self):
        return [dict(self.window)]

    def focus_window(self, identity, allow_input=True):
        if identity != self.window["_identity"]:
            raise ControlError("stale_window", "Window changed")
        self.window["foreground"] = True

    def scroll(self, steps, axis="vertical"):
        self.actions.append(("scroll", steps, axis))
