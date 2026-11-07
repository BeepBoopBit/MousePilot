"""Real Windows restart and SSH-drop tests. Does not lock, sleep, reboot, or change displays.

Requires the dedicated test target and project installed at ~/mousepilot on Windows.
Kills only tunnels it starts. A lost client holds the production 90-second lease
until expiration, so this test intentionally takes about two minutes.
"""

import argparse
import asyncio
import base64
import json
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from windows_fixture import read_state

from mousepilot.client import Remote, profiles
from mousepilot.protocol import ControlError


def powershell(host, code):
    code = "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); " + code
    encoded = base64.b64encode(code.encode("utf-16-le")).decode()
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            host,
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        capture_output=True,
        timeout=45,
        check=True,
    )
    return result.stdout.decode("utf-8-sig").strip()


@contextmanager
def tunnel(profile):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
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
            "-L",
            f"127.0.0.1:{port}:127.0.0.1:{profile.get('remote_port', 8765)}",
            profile["ssh_host"],
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 12
        while True:
            if process.poll() is not None:
                raise RuntimeError("Owned test tunnel failed to start")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError("Test tunnel startup timeout")
                time.sleep(0.05)
        yield process, f"http://127.0.0.1:{port}"
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def point(frame, desktop_point):
    left, top, right, bottom = frame["desktop_bounds"]
    width, height = frame["image_size"]
    return int((desktop_point[0] - left) * width / (right - left)), int(
        (desktop_point[1] - top) * height / (bottom - top)
    )


def run(args):
    profile = profiles(args.config)[args.device]
    host = profile["ssh_host"]
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "checks": [],
        "not_tested": [
            "lock/unlock",
            "sleep/wake",
            "reboot/login",
            "monitor unplug/replug",
            "DPI changes",
        ],
    }
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)

    def record(name, **evidence):
        report["checks"].append({"name": name, "passed": True, **evidence})
        destination.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Passed: {name}", flush=True)

    def remote(url):
        return Remote(
            url,
            profile["token_file"],
            profile["expected_device_id"],
            profile.get("display_aliases"),
        )

    def wait_state(predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while True:
            state = read_state(host)
            if predicate(state):
                return state
            if time.monotonic() > deadline:
                raise AssertionError(f"Fixture observation timed out: {state}")
            time.sleep(0.1)

    def verify_recovery(client, label):
        baseline = read_state(host)
        frame = client.execute({"command": "screen"})
        x, y = point(frame, baseline["targets"]["button"])
        client.execute({"command": "click", "x": x, "y": y, "frame": frame["screenshot_id"]})
        wait_state(lambda state: state["clicks"] == baseline["clicks"] + 1)
        frame = client.execute({"command": "screen"})
        x, y = point(frame, baseline["targets"]["input"])
        client.execute({"command": "click", "x": x, "y": y, "frame": frame["screenshot_id"]})
        # Only the dedicated test field is focused; neither command presses Enter.
        client.execute({"command": "hotkey", "keys": ["ctrl", "a"]})
        client.execute({"command": "type", "text": label})
        wait_state(lambda state: state["text"] == label)
        record(label + " fresh screenshot, click, and text recovery")

    try:
        initial = wait_state(lambda state: "left_button_down" in state and "run_id" in state)
        report["fixture_run_id"] = initial["run_id"]
        with tunnel(profile) as (_, url):
            old = remote(url).connect()
            try:
                identity = old.execute({"command": "info"})["device_id"]
                old_frame = old.execute({"command": "screen"})["screenshot_id"]
                old_window = old.execute(
                    {"command": "windows", "title": "MousePilot verification target"}
                )["windows"][0]["window_id"]
                print("Restarting the packaged Windows backend...", flush=True)
                powershell(
                    host,
                    '& "$env:USERPROFILE\\mousepilot\\scripts\\start-server.ps1" -Executable "$env:USERPROFILE\\mousepilot\\dist\\mousepilot-server.exe"',
                )
                assert old.request({"command": "info"})["device_id"] == identity
                record("device identity survives server restart")
                try:
                    old.request({"command": "type", "text": "MUST NOT TYPE"})
                    raise AssertionError("Old control session was accepted after restart")
                except ControlError as exc:
                    assert exc.code == "session_expired", exc.code
                record("pre-restart control session is rejected")
            finally:
                old.close()
            recovered = remote(url).connect()
            try:
                for command, code in [
                    ({"command": "move", "x": 0, "y": 0, "frame": old_frame}, "stale_frame"),
                    ({"command": "focus", "window_id": old_window}, "stale_window"),
                ]:
                    try:
                        recovered.execute(command)
                        raise AssertionError("Pre-restart observation was accepted")
                    except ControlError as exc:
                        assert exc.code == code, exc.code
                assert read_state(host)["text"] != "MUST NOT TYPE"
                record("pre-restart screenshot and window IDs are rejected without input")
                verify_recovery(recovered, "restart recovery")
            finally:
                recovered.close()
        # A second, exclusively owned tunnel is killed during native input.
        with tunnel(profile) as (process, url):
            lost = remote(url).connect()
            try:
                before = read_state(host)
                frame = lost.execute({"command": "screen"})
                x, y = point(frame, before["targets"]["drag"])
                with ThreadPoolExecutor(max_workers=1) as executor:
                    started = time.monotonic()
                    future = executor.submit(
                        lost.execute,
                        {
                            "command": "drag",
                            "from_x": x,
                            "from_y": y,
                            "to_x": x + 80,
                            "to_y": y + 20,
                            "frame": frame["screenshot_id"],
                            "duration": 5.0,
                        },
                    )
                    wait_state(
                        lambda state: (
                            state["mouse_down_events"] == before["mouse_down_events"] + 1
                            and state["left_button_down"]
                        ),
                        timeout=4,
                    )
                    assert not future.done(), (
                        "Drag finished before the disconnect could be injected"
                    )
                    print(
                        "Dropping only the owned test SSH tunnel while left mouse is down...",
                        flush=True,
                    )
                    process.terminate()
                    process.wait(timeout=5)
                    dropped = time.monotonic()
                    try:
                        future.result(timeout=16)
                        raise AssertionError("Lost input response incorrectly reported success")
                    except ControlError as exc:
                        assert exc.code == "disconnected", exc.code
                    after = wait_state(
                        lambda state: (
                            state["mouse_up_events"] == before["mouse_up_events"] + 1
                            and not state["left_button_down"]
                        )
                    )
                    assert after["mouse_down_events"] == before["mouse_down_events"] + 1
                    assert after["drags"] == before["drags"] + 1
                    assert not after["right_button_down"] and not after["middle_button_down"]
                    released = time.monotonic()
                    record(
                        "SSH loss is reported and native drag releases the mouse button",
                        configured_duration_seconds=5,
                        observed_release_within_seconds=round(released - started, 2),
                        tunnel_dropped_after_seconds=round(dropped - started, 2),
                        mouse_down_delta=1,
                        mouse_up_delta=1,
                    )
            finally:
                lost.close()  # The dead tunnel cannot send disconnect; the production lease must expire.
        with tunnel(profile) as (_, url):
            replacement = remote(url)
            try:
                replacement.connect()
                raise AssertionError("Lost controller lease was unexpectedly bypassed")
            except ControlError as exc:
                assert exc.code == "device_busy", exc.code
            record("replacement controller is blocked while lost lease remains active")
            print("Waiting for the real 90-second control lease to expire...", flush=True)
            last_notice = 0
            deadline = started + 105
            while True:
                try:
                    replacement.connect()
                    break
                except ControlError as exc:
                    if exc.code != "device_busy" or time.monotonic() > deadline:
                        raise
                    elapsed = time.monotonic() - started
                    if elapsed - last_notice >= 15:
                        print(
                            f"Lease recovery: {elapsed:.0f}s elapsed; input has not been replayed.",
                            flush=True,
                        )
                        last_notice = elapsed
                    time.sleep(2)
            try:
                state = read_state(host)
                assert state["mouse_down_events"] == before["mouse_down_events"] + 1
                assert state["mouse_up_events"] == before["mouse_up_events"] + 1
                assert not state["left_button_down"]
                record(
                    "production lease expires and reconnect does not replay the drag",
                    reconnected_after_seconds=round(time.monotonic() - started, 2),
                )
                verify_recovery(replacement, "SSH recovery")
            finally:
                replacement.close()

        # Confirm an actual MCP adapter can initialize and observe after both failures.
        async def verify_mcp():
            params = StdioServerParameters(
                command=sys.executable,
                args=[
                    "-m",
                    "mousepilot.cli",
                    "--config",
                    str(Path(args.config).resolve()),
                    "--device",
                    args.device,
                    "mcp",
                ],
            )
            async with stdio_client(params) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    info = await session.call_tool("device_info", {})
                    screen = await session.call_tool("current_screen", {})
                    assert not info.isError and not screen.isError
                    assert info.structuredContent["device_id"] == identity
                    assert screen.content[0].type == "image"
                    Path("captures/lifecycle-recovered.png").write_bytes(
                        base64.b64decode(screen.content[0].data)
                    )
                    return len(tools.tools)

        count = asyncio.run(verify_mcp())
        record("MCP adapter reconnects and returns a real screenshot", tools=count)
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["failure"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        destination.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="devices.toml")
    parser.add_argument("--device", default="windows")
    parser.add_argument("--output", default="captures/lifecycle-verification.json")
    run(parser.parse_args())
