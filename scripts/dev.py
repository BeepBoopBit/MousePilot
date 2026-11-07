"""Run standard project commands. Do not start desktop services."""

import argparse
import ast
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def version(root=ROOT):
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    module = ast.parse((root / "src/mousepilot/protocol.py").read_text())
    backend = next(
        ast.literal_eval(n.value)
        for n in module.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in n.targets)
    )
    if project["version"] != backend:
        raise ValueError("Project and backend versions do not match")
    return project["version"]


def run(*args):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True)


def environment_python():
    path = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not path.is_file():
        raise ValueError("Development environment missing. Run the develop command.")
    return path


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_artifact(path, expected_version, manifest_path=None):
    path = Path(path).resolve()
    manifest_path = Path(manifest_path) if manifest_path else path.parent / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if (
        manifest.get("schema") != 1
        or manifest.get("project") != "mousepilot"
        or manifest.get("version") != expected_version
    ):
        raise ValueError("Package manifest does not match this project version")
    matches = [entry for entry in manifest["artifacts"] if entry["file"] == path.name]
    if len(matches) != 1 or digest(path) != matches[0]["sha256"]:
        raise ValueError("Artifact is missing from the manifest or its hash does not match")
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            metadata = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata) != 1:
                raise ValueError("Wheel metadata is missing or ambiguous")
            text = archive.read(metadata[0]).decode()
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path) as archive:
            metadata = [
                entry
                for entry in archive.getmembers()
                if len(Path(entry.name).parts) == 2 and entry.name.endswith("/PKG-INFO")
            ]
            if len(metadata) != 1:
                raise ValueError("Source archive metadata is missing or ambiguous")
            text = archive.extractfile(metadata[0]).read().decode()
    elif path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise ValueError("ZIP integrity check failed")
            names = archive.namelist()
            metadata = json.loads(archive.read("package-info.json"))
            if (
                metadata.get("project") != "mousepilot"
                or metadata.get("version") != expected_version
            ):
                raise ValueError("Native package metadata does not match this project version")
            if not any(
                name.endswith("mousepilot-server.exe") or "/MousePilot.app/" in "/" + name
                for name in names
            ):
                raise ValueError("Native package has no MousePilot application")
        return
    else:
        raise ValueError("Unsupported artifact format")
    metadata = Parser().parsestr(text)
    if metadata["Name"] != "mousepilot" or metadata["Version"] != expected_version:
        raise ValueError("Artifact metadata does not match this project version")


def package(python_only):
    current = version()
    run("uv", "build")
    if not python_only:
        if sys.platform == "win32":
            run("powershell.exe", "-NoProfile", "-File", ROOT / "scripts/build-windows.ps1")
        elif sys.platform == "darwin":
            run("sh", ROOT / "scripts/build-macos.sh")
    paths = [
        ROOT / "dist" / f"mousepilot-{current}-py3-none-any.whl",
        ROOT / "dist" / f"mousepilot-{current}.tar.gz",
    ]
    if not python_only and sys.platform in ("win32", "darwin"):
        name = (
            "mousepilot-windows-x64.zip"
            if sys.platform == "win32"
            else f"mousepilot-macos-{platform.machine()}.zip"
        )
        paths.append(ROOT / "dist" / name)
    manifest = {
        "schema": 1,
        "project": "mousepilot",
        "version": current,
        "artifacts": [{"file": path.name, "sha256": digest(path)} for path in paths],
    }
    target = ROOT / "dist/release-manifest.json"
    target.write_text(json.dumps(manifest, indent=2) + "\n")
    (ROOT / "dist/SHA256SUMS").write_text(
        "".join(f"{entry['sha256']}  {entry['file']}\n" for entry in manifest["artifacts"])
    )
    for path in paths:
        verify_artifact(path, current, target)
    run(environment_python(), ROOT / "scripts/check-public-files.py", "--artifacts", ROOT / "dist")
    print(f"Packages verified: {len(paths)}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    for name in ("help", "doctor", "develop", "check", "test"):
        sub.add_parser(name)
    build = sub.add_parser("build")
    build.add_argument("--release", action="store_true", help="Build Python distribution files")
    pack = sub.add_parser("package")
    pack.add_argument("--python-only", action="store_true")
    verify = sub.add_parser("verify")
    verify.add_argument("--artifact", type=Path, required=True)
    for name in ("install", "reinstall", "uninstall", "publish"):
        sub.add_parser(name)
    args = parser.parse_args(argv)
    if args.command in (None, "help"):
        parser.print_help()
        return 0
    if args.command in ("install", "reinstall", "uninstall", "publish"):
        print(
            f"{args.command} is not supported by this wrapper. See docs/configuration.md and docs/releasing.md.",
            file=sys.stderr,
        )
        return 2
    if args.command == "doctor":
        missing = [name for name in ("uv", "git") if not shutil.which(name)]
        print(f"MousePilot {version()}; Python {platform.python_version()}; host {sys.platform}")
        for name in ("uv", "git"):
            print(f"{name}: {'found' if name not in missing else 'missing'}")
        environment_python()
        return 1 if missing else 0
    if args.command == "develop":
        run("uv", "sync", "--locked")
    elif args.command == "check":
        python = environment_python()
        run(python, "-m", "ruff", "check", "src", "tests", "scripts")
        run(python, "-m", "ruff", "format", "--check", "src", "tests", "scripts")
        run(python, ROOT / "scripts/checks/check-docs.py", "--root", ROOT)
        run(python, ROOT / "scripts/check-public-files.py")
    elif args.command == "test":
        python = environment_python()
        run(python, "-m", "unittest", "discover", "-s", "tests")
        run(python, ROOT / "tests/tooling/checks/docs_test.py")
    elif args.command == "build":
        version()
        run("uv", "build")
    elif args.command == "package":
        package(args.python_only)
    elif args.command == "verify":
        verify_artifact(args.artifact, version())
        print("Artifact verified. Hashes do not prove publisher identity.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        ValueError,
        OSError,
        KeyError,
        StopIteration,
        subprocess.CalledProcessError,
        zipfile.BadZipFile,
        tarfile.TarError,
    ) as exc:
        sys.exit(f"Command failed: {exc}")
