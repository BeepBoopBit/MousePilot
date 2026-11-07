"""Loopback-only authenticated backend with an exclusive, expiring control lease."""

import argparse
import json
import logging
import math
import secrets
import socket
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pydantic import ValidationError

from .controller import Controller
from .protocol import PROTOCOL_VERSION, ControlError

logger = logging.getLogger("mousepilot_server.audit")


class Lease:
    def __init__(self, ttl=90, clock=time.monotonic):
        self.ttl, self.clock = ttl, clock
        self.session = None
        self.deadline = 0
        self.lock = threading.Lock()
        self.resetting = False

    def acquire(self):
        with self.lock:
            if self.resetting:
                raise ControlError("reset_in_progress", "Control reset is in progress")
            if self.session and self.clock() < self.deadline:
                raise ControlError("device_busy", "Another client controls this device")
            self.session = secrets.token_hex(32)
            self.deadline = self.clock() + self.ttl
            return self.session

    def check(self, session):
        with self.lock:
            if (
                self.resetting
                or not session
                or not self.session
                or not secrets.compare_digest(session, self.session)
                or self.clock() >= self.deadline
            ):
                raise ControlError(
                    "session_expired",
                    "Control session expired; reconnect before issuing input",
                )
            self.deadline = self.clock() + self.ttl

    def release(self, session):
        with self.lock:
            if session and self.session and secrets.compare_digest(session, self.session):
                self.session = None

    def status(self, session):
        with self.lock:
            active = bool(self.session and self.clock() < self.deadline)
            return {
                "active": active,
                "owns_control": bool(
                    active and session and secrets.compare_digest(session, self.session)
                ),
                "expires_in_seconds": max(0, math.ceil(self.deadline - self.clock()))
                if active
                else 0,
                "resetting": self.resetting,
            }

    def begin_reset(self):
        with self.lock:
            if self.resetting:
                raise ControlError("reset_in_progress", "Another reset is already running")
            self.resetting = True
            self.session = None
            self.deadline = 0

    def finish_reset(self, claim=True):
        with self.lock:
            if claim:
                self.session = secrets.token_hex(32)
                self.deadline = self.clock() + self.ttl
            self.resetting = False
            return self.session


def make_server(controller, token, port=8765, lease=None):
    lease = lease or Lease()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Do not log tokens, typed text, screenshots, or raw request data.
            pass

        def do_POST(self):
            started = time.monotonic()
            self.connection.settimeout(10)
            status = 200
            operation = "unknown"
            error_code = None
            try:
                auth = self.headers.get("Authorization", "")
                if not secrets.compare_digest(auth, "Bearer " + token):
                    raise ControlError("unauthorized", "Invalid device token")
                if self.path != "/":
                    raise ControlError("not_found", "Unknown endpoint")
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 65536:
                    raise ControlError("invalid_request", "Request must contain 1 to 65536 bytes")
                args = json.loads(self.rfile.read(size))
                if not isinstance(args, dict):
                    raise ControlError("invalid_request", "Request must be an object")
                op = args.get("command")
                operation = (
                    op
                    if op
                    in (
                        "connect",
                        "control_status",
                        "reset",
                        "heartbeat",
                        "disconnect",
                        "info",
                        "screen",
                        "crop",
                        "preview",
                        "elements",
                        "element_click",
                        "windows",
                        "window_info",
                        "window_capture",
                        "focus",
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
                    )
                    else "unknown"
                )
                session = self.headers.get("X-Mouse-Session", "")
                if op in ("connect", "reset"):
                    if set(args) != {
                        "command",
                        "expected_device_id",
                        "protocol_version",
                    }:
                        raise ControlError("invalid_request", "Invalid connection request")
                    if args["expected_device_id"] != controller.device_id:
                        raise ControlError(
                            "wrong_device", "Device identity does not match the profile"
                        )
                    if args["protocol_version"] != PROTOCOL_VERSION:
                        raise ControlError(
                            "protocol_mismatch",
                            "Client and server protocol versions differ",
                        )
                    if op == "reset":
                        lease.begin_reset()
                        try:
                            controller.reset_control()
                        except BaseException:
                            lease.finish_reset(claim=False)
                            raise
                        new_session = lease.finish_reset()
                    else:
                        new_session = lease.acquire()
                    result = {
                        "session": new_session,
                        "lease_seconds": lease.ttl,
                        "device_id": controller.device_id,
                        "protocol_version": PROTOCOL_VERSION,
                    }
                    if op == "reset":
                        result.update(paused=True, observations_invalidated=True)
                elif op == "control_status":
                    if set(args) != {"command"}:
                        raise ControlError("invalid_request", "Invalid status request")
                    result = {
                        **lease.status(session),
                        "paused": controller.desktop.stopped.is_set(),
                        "device_id": controller.device_id,
                    }
                elif op == "heartbeat":
                    lease.check(session)
                    result = {"connected": True}
                elif op == "disconnect":
                    lease.release(session)
                    result = {"connected": False}
                else:
                    # Stop and device identity inspection remain available to authenticated clients.
                    if op not in ("info", "displays", "stop"):
                        lease.check(session)
                    # Recheck under the controller lock, fencing requests that passed the
                    # first check just before a concurrent reset revoked their session.
                    authorize = (
                        None if op in ("info", "displays", "stop") else lambda: lease.check(session)
                    )
                    result = controller.execute(args, authorize=authorize)
                    if op == "stop":
                        controller.desktop.release_all()
            except ControlError as exc:
                error_code = exc.code
                status = {"unauthorized": 401, "device_busy": 409, "busy": 409}.get(exc.code, 400)
                result = {"error": {"code": exc.code, "message": str(exc)}}
            except (ValueError, ValidationError, TypeError):
                # Validation details can contain message text; do not echo input back.
                status = 400
                error_code = "invalid_request"
                result = {
                    "error": {
                        "code": "invalid_request",
                        "message": "Invalid command or parameters",
                    }
                }
            except Exception as exc:
                status = 500
                error_code = "backend_error"
                result = {"error": {"code": "backend_error", "message": str(exc)}}
            if operation != "heartbeat":
                logger.info(
                    "operation=%s status=%s error=%s", operation, status, error_code or "none"
                )
            payload = json.dumps(result).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (ConnectionError, TimeoutError) as exc:
                # The operation may already have executed. Never retry it on a new socket.
                self.close_connection = True
                logger.warning(
                    "operation=%s response_delivery=failed elapsed_ms=%d cause=%s client_outcome=unknown input_not_retried=true",
                    operation,
                    round((time.monotonic() - started) * 1000),
                    type(exc).__name__,
                )

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def load_identity(path):
    path = Path(path)
    try:
        with path.open("x") as stream:
            stream.write(str(uuid.uuid4()))
    except FileExistsError:
        pass
    return str(uuid.UUID(path.read_text().strip()))


def serve(
    port=8765,
    token_file="mousepilot-token.txt",
    identity_file="mousepilot-device-id.txt",
    name=None,
    tray=False,
):
    if sys.platform == "darwin":
        from .macos import Desktop
    elif sys.platform == "win32":
        from .windows import Desktop
    else:
        raise RuntimeError("The device server supports Windows and macOS only")

    handler = RotatingFileHandler("mousepilot-server.log", maxBytes=1_000_000, backupCount=2)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    token_path = Path(token_file)
    try:
        with token_path.open("x") as stream:
            stream.write(secrets.token_hex(32))
        token_path.chmod(0o600)
    except FileExistsError:
        pass
    token = token_path.read_text().strip()
    if len(token) < 32 or not token.isascii():
        raise ValueError("Device token must contain at least 32 ASCII characters")
    desktop = Desktop()
    desktop.start_emergency_hotkey()
    controller = Controller(desktop, load_identity(identity_file), name or socket.gethostname())
    lease = Lease()
    server = make_server(controller, token, port, lease)
    close_tray = None
    if tray and sys.platform == "win32":
        from .tray import start_tray

        close_tray = start_tray(controller, server, lease)
    print(
        f"mousepilot-server {controller.device_id} listening on 127.0.0.1:{server.server_port}",
        flush=True,
    )
    print(
        "Emergency stop: Ctrl+Alt+Shift+F11. Resume explicitly with the client.",
        flush=True,
    )
    try:
        if sys.platform == "darwin":
            from .macos_ui import run

            run(controller, server, tray)
        else:
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if close_tray:
            close_tray()
        desktop.stopped.set()
        desktop.release_all()
        if hasattr(desktop, "close"):
            desktop.close()
        server.server_close()
        logger.removeHandler(handler)
        handler.close()


def main():
    parser = argparse.ArgumentParser(
        description="Windows/macOS desktop backend (run in the user session)"
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token-file", default="mousepilot-token.txt")
    parser.add_argument("--identity-file", default="mousepilot-device-id.txt")
    parser.add_argument("--name")
    parser.add_argument("--tray", action="store_true", help="Show local tray/menu controls")
    parser.add_argument(
        "--data-dir", type=Path, help="Directory for identity, token, and log files"
    )
    args = parser.parse_args()
    if args.data_dir:
        import os

        args.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chdir(args.data_dir)
    try:
        serve(args.port, args.token_file, args.identity_file, args.name, args.tray)
    except Exception as exc:
        logger.exception("Server startup or shutdown failed")
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
