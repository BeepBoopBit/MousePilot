"""Install the local private-file check. Preserve other hooks."""

import shlex
import subprocess
import sys
from pathlib import Path

MARKER = "# MousePilot private-file hook"


def install(root):
    root = Path(root).resolve()
    configured = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"], cwd=root, capture_output=True, text=True
    )
    if configured.returncode == 0:
        raise ValueError("A hook manager is configured. Add the file check to that manager.")
    hook_path = subprocess.check_output(
        ["git", "rev-parse", "--git-path", "hooks/pre-commit"], cwd=root, text=True
    ).strip()
    hook = Path(hook_path)
    if not hook.is_absolute():
        hook = root / hook
    if hook.exists() and MARKER not in hook.read_text():
        raise ValueError("Existing hook found. Add the file check to your hook manager.")
    checker = root / "scripts/check-public-files.py"
    if not checker.is_file():
        raise ValueError("Private-file checker not found in this checkout")
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(
        "#!/bin/sh\n"
        + MARKER
        + "\nexec "
        + shlex.quote(Path(sys.executable).as_posix())
        + " "
        + shlex.quote(checker.as_posix())
        + "\n"
    )
    hook.chmod(hook.stat().st_mode | 0o111)
    return hook


if __name__ == "__main__":
    try:
        print(f"Installed: {install(Path.cwd())}")
    except (ValueError, subprocess.CalledProcessError) as exc:
        sys.exit(str(exc))
