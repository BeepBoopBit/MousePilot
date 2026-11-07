"""Check Git's publication set and built Python archives for common private artifacts.

This narrow guard complements review/secret scanning; it is not a general secret detector.
Reads indexed blobs (not unstaged file contents), so results match what would be committed.
"""

import argparse
import fnmatch
import re
import subprocess
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

PRIVATE_DIRS = {"captures", ".venv", ".git", "__pycache__", ".ruff_cache", "build", "dist"}
PRIVATE_ROOT_FILES = {
    "devices.toml",
    "mcp-config.json",
    "target-state.json",
    "mousepilot-device-id.txt",
    "mouse-device-id.txt",
    "audit-requirements.txt",
}
# These patterns detect likely credentials/personal paths without embedding any real values.
SENSITIVE = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{40,}"),
    re.compile(rb"/data/" + rb"dev/projects/[^\s\"\']+"),
    re.compile(rb"C:\\\\Users\\\\(?!Public(?:\\\\|/))[^\\\\/\s]+", re.I),
)


def check_name(name):
    parts = PurePosixPath(name).parts
    lowered = [part.casefold() for part in parts]
    assistant_dirs = {".claude", ".codex", ".cursor", ".windsurf", ".continue", ".agents"}
    assistant_files = (
        "agents.md",
        "agents.*.md",
        "claude.md",
        "claude.*.md",
        "codex.md",
        "gemini.md",
        "qwen.md",
        ".cursorrules",
        ".windsurfrules",
        ".mcp.json",
    )
    if any(part in assistant_dirs for part in lowered) or any(
        fnmatch.fnmatchcase(lowered[-1], pattern) for pattern in assistant_files if lowered
    ):
        return True
    leaf = parts[-1] if parts else ""
    return (
        any(part in PRIVATE_DIRS for part in parts)
        or (len(parts) == 1 and leaf in PRIVATE_ROOT_FILES)
        or leaf.endswith("-token.txt")
        or leaf.endswith((".pyc", ".log", ".pem", ".key", ".p12", ".pfx"))
        or leaf == ".env"
        or (leaf.startswith(".env.") and leaf != ".env.example")
    )


def check_content(data):
    return any(pattern.search(data) for pattern in SENSITIVE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifacts",
        type=Path,
        help="Also inspect wheels and Python source archives in this directory",
    )
    args = parser.parse_args()
    files = subprocess.check_output(["git", "ls-files", "-z"]).split(b"\0")
    failures = []
    count = 0
    for entry in filter(None, files):
        name = entry.decode()
        data = subprocess.check_output(["git", "show", ":" + name])
        if check_name(name) or check_content(data):
            failures.append(name)
        count += 1
    if count == 0:
        raise SystemExit(
            "No indexed files; stage the intended public files before running this check"
        )
    archive_count = 0
    if args.artifacts:
        for path in args.artifacts.glob("*"):
            if path.suffix == ".whl":
                with zipfile.ZipFile(path) as archive:
                    for name in archive.namelist():
                        if check_name(name) or check_content(archive.read(name)):
                            failures.append(f"{path.name}:{name}")
                archive_count += 1
            elif path.name.endswith(".tar.gz"):
                with tarfile.open(path) as archive:
                    for member in archive.getmembers():
                        if not member.isfile():
                            continue
                        name = "/".join(PurePosixPath(member.name).parts[1:])
                        data = archive.extractfile(member).read()
                        if check_name(name) or check_content(data):
                            failures.append(f"{path.name}:{name}")
                archive_count += 1
    if failures:
        raise SystemExit("Review these files before publication:\n" + "\n".join(failures))
    print(
        f"Checked {count} indexed files and {archive_count} Python archives; no matching private artifacts found"
    )


if __name__ == "__main__":
    main()
