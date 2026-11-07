"""Optional Windows tray controls; desktop actions remain in Controller."""

import sys
import threading

import pystray
from PIL import Image, ImageDraw


def start_tray(controller, server, lease):
    def image(paused):
        bitmap = Image.new("RGB", (64, 64), "#222222")
        draw = ImageDraw.Draw(bitmap)
        draw.rounded_rectangle((16, 6, 48, 58), radius=14, fill="#e79b38" if paused else "#4dbb83")
        draw.line((32, 8, 32, 29), fill="white", width=3)
        return bitmap

    def toggle(icon, item):
        try:
            controller.execute(
                {"command": "resume" if controller.desktop.stopped.is_set() else "stop"}
            )
            if controller.desktop.stopped.is_set():
                controller.desktop.release_all()
        except Exception as exc:
            print(f"Tray control failed: {exc}", file=sys.stderr)
        icon.update_menu()

    def quit_server(icon, item):
        controller.desktop.stopped.set()
        controller.desktop.release_all()
        server.shutdown()

    icon = pystray.Icon(
        "mousepilot-server",
        image(False),
        "MousePilot server",
        menu=pystray.Menu(
            pystray.MenuItem(
                lambda item: (
                    "Resume input" if controller.desktop.stopped.is_set() else "Pause input"
                ),
                toggle,
            ),
            pystray.MenuItem("Emergency stop: Ctrl+Alt+Shift+F11", None, enabled=False),
            pystray.MenuItem("Quit server", quit_server),
        ),
    )
    icon.run_detached()
    done = threading.Event()

    def update():
        previous = None
        while not done.wait(0.5):
            paused = controller.desktop.stopped.is_set()
            with lease.lock:
                connected = bool(lease.session and lease.clock() < lease.deadline)
            state = (paused, connected)
            if state != previous:
                icon.icon = image(paused)
                icon.title = f"MousePilot server: {'paused' if paused else 'enabled'}; {'connected' if connected else 'idle'}"
                icon.update_menu()
                previous = state

    threading.Thread(target=update, daemon=True, name="tray-status").start()

    def close():
        done.set()
        icon.stop()

    return close
