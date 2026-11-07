"""Device profiles and SSH tunnel lifecycle. Input requests are never retried."""

import json
import socket
import subprocess
import threading
import time
import tomllib
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

from .protocol import PROTOCOL_VERSION, ControlError

DEFAULT_CONFIG = Path.home() / ".config" / "mousepilot" / "devices.toml"


def profiles(path=DEFAULT_CONFIG):
    path = Path(path).expanduser().resolve()
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    devices = data.get("devices", {})
    for name, device in devices.items():
        for required in ("token_file", "expected_device_id"):
            if not device.get(required):
                raise ValueError(f"Device {name} is missing {required}")
        token_path = Path(device["token_file"]).expanduser()
        if not token_path.is_absolute():
            token_path = path.parent / token_path
        device["token_file"] = str(token_path)
    return devices


class Remote:
    def __init__(self, url, token_file, expected_device_id=None, display_aliases=None, lazy=False):
        parsed = urlparse(url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Use a loopback HTTP URL through an SSH tunnel")
        self.url = url
        self.token = Path(token_file).expanduser().read_text().strip()
        self.expected_device_id = expected_device_id
        self.display_aliases = display_aliases or {}
        self.lazy = lazy
        self.connect_lock = threading.RLock()
        self.session = None
        self.done = threading.Event()
        self.failure = None
        self.thread = None
        self.opener = build_opener(ProxyHandler({}))

    def request(self, args):
        headers = {
            "Authorization": "Bearer " + self.token,
            "Content-Type": "application/json",
        }
        if self.session:
            headers["X-Mouse-Session"] = self.session
        request = Request(self.url, data=json.dumps(args).encode(), headers=headers)
        try:
            with self.opener.open(request, timeout=15) as response:
                return json.load(response)
        except HTTPError as exc:
            try:
                error = json.load(exc)["error"]
                raise ControlError(error["code"], error["message"]) from exc
            except (ValueError, KeyError, TypeError):
                raise ControlError("http_error", f"Backend returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ControlError(
                "disconnected",
                "Device connection failed; inspect state before retrying input",
            ) from exc

    def verify(self):
        info = self.request({"command": "info"})
        expected = self.expected_device_id or info["device_id"]
        if info.get("device_id") != expected:
            raise ControlError("wrong_device", "Device identity does not match the profile")
        if info.get("protocol_version") != PROTOCOL_VERSION:
            raise ControlError("protocol_mismatch", "Client and server protocol versions differ")
        return expected

    def _start_heartbeat(self, lease_seconds):
        self.done = threading.Event()
        stop_event = self.done
        interval = min(20, lease_seconds / 3)

        def heartbeat():
            while not stop_event.wait(interval):
                try:
                    self.request({"command": "heartbeat"})
                except Exception as exc:
                    if not stop_event.is_set():
                        self.failure = exc
                    return

        self.thread = threading.Thread(target=heartbeat, daemon=True)
        self.thread.start()

    def _stop_heartbeat(self):
        self.done.set()
        if self.thread:
            self.thread.join(timeout=16)
            self.thread = None

    def connect(self):
        with self.connect_lock:
            if self.session:
                return self
            expected = self.verify()
            result = self.request(
                {
                    "command": "connect",
                    "expected_device_id": expected,
                    "protocol_version": PROTOCOL_VERSION,
                }
            )
            self.session = result["session"]
            self.failure = None
            self._start_heartbeat(result["lease_seconds"])
            return self

    def reset_control(self):
        with self.connect_lock:
            self._stop_heartbeat()
            try:
                expected = self.verify()
                result = self.request(
                    {
                        "command": "reset",
                        "expected_device_id": expected,
                        "protocol_version": PROTOCOL_VERSION,
                    }
                )
            except Exception as exc:
                self.failure = exc
                raise
            self.session = result.pop("session")
            self.failure = None
            self._start_heartbeat(result["lease_seconds"])
            return {
                **result,
                "owns_control": True,
                "next_step": "Capture a fresh screen, then call resume_control explicitly before input.",
            }

    def release_control(self):
        with self.connect_lock:
            self._stop_heartbeat()
            try:
                if self.session:
                    self.request({"command": "disconnect"})
            except Exception as exc:
                self.failure = exc
                raise
            else:
                self.failure = None
            finally:
                self.session = None
            return {"owns_control": False, "released": True}

    def execute(self, args):
        op = args.get("command")
        if op == "reset":
            return self.reset_control()
        if op == "release":
            return self.release_control()
        public = op in ("info", "displays", "control_status", "stop")
        if not public:
            if self.failure:
                raise ControlError(
                    "control_lost",
                    "Control connection lost or revoked; inspect control_status and reset explicitly. Input was not retried.",
                ) from self.failure
            if self.lazy and not self.session:
                self.connect()
        if op in ("screen", "displays", "overview"):
            args = {**args, "aliases": self.display_aliases}
        try:
            return self.request(args)
        except ControlError as exc:
            if not public and exc.code in ("session_expired", "disconnected"):
                self.failure = exc
            raise

    def close(self):
        try:
            self.release_control()
        except Exception:
            pass  # A failed disconnect is recovered by lease expiry or an explicit reset.


@contextmanager
def connection(
    device=None,
    config=DEFAULT_CONFIG,
    url=None,
    token_file="mousepilot-token.txt",
    acquire=True,
    lazy=False,
):
    process = None
    remote = None
    try:
        expected = None
        display_aliases = {}
        if device:
            entries = profiles(config)
            if device not in entries:
                raise ValueError(f"Unknown device {device}; run devices list")
            profile = entries[device]
            display_aliases = profile.get("display_aliases", {})
            token_file, expected = profile["token_file"], profile["expected_device_id"]
            if "ssh_host" in profile:
                host = profile["ssh_host"]
                if (
                    not isinstance(host, str)
                    or not host
                    or host.startswith("-")
                    or any(c.isspace() for c in host)
                ):
                    raise ValueError("ssh_host must be an SSH alias or user@host")
                port = profile.get("remote_port", 8765)
                if type(port) is not int or not 1 <= port <= 65535:
                    raise ValueError("remote_port must be between 1 and 65535")
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    local_port = sock.getsockname()[1]
                process = subprocess.Popen(
                    [
                        "ssh",
                        "-N",
                        "-T",
                        "-o",
                        "BatchMode=yes",
                        "-o",
                        "ExitOnForwardFailure=yes",
                        "-o",
                        "ConnectTimeout=10",
                        "-o",
                        "ServerAliveInterval=15",
                        "-o",
                        "ServerAliveCountMax=2",
                        "-L",
                        f"127.0.0.1:{local_port}:127.0.0.1:{port}",
                        host,
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                )
                url = f"http://127.0.0.1:{local_port}"
                deadline = time.monotonic() + 12
                while True:
                    if process.poll() is not None:
                        raise ControlError(
                            "ssh_failed",
                            "SSH tunnel exited; check SSH access and host configuration",
                        )
                    try:
                        with socket.create_connection(("127.0.0.1", local_port), timeout=0.2):
                            break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise ControlError("ssh_failed", "SSH tunnel startup timed out")
                        time.sleep(0.05)
            else:
                url = profile.get("url")
        if not url:
            raise ValueError("Select --device NAME or --url http://127.0.0.1:PORT")
        remote = Remote(url, token_file, expected, display_aliases, lazy=lazy)
        if acquire:
            remote.connect()
        else:
            remote.verify()
        yield remote
    finally:
        if remote:
            remote.close()
        if process:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
