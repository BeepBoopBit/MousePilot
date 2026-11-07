"""Collect installed dependency notices and the pinned pystray source (when installed) for a desktop bundle.

This is an inventory of the build environment, not a claim about exact reachability
inside the executable. Nothing from local device profiles or captures is copied.
"""

import argparse
import hashlib
import json
import re
import shutil
import sys
import tomllib
from importlib.metadata import distributions
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen


def collect(output, lock_path):
    output.mkdir(parents=True, exist_ok=True)
    inventory = []
    for distribution in sorted(distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = distribution.metadata["Name"]
        directory = output / re.sub(r"[^A-Za-z0-9_.-]", "-", name)
        notices = []
        for entry in distribution.files or ():
            if not entry.name.lower().startswith(("license", "copying", "notice")):
                continue
            path = Path(distribution.locate_file(entry))
            if not path.is_file():
                continue
            directory.mkdir(exist_ok=True)
            target = directory / f"{len(notices) + 1}-{path.name}"
            shutil.copyfile(path, target)
            notices.append(str(target.relative_to(output)))
        license_id = distribution.metadata.get("License-Expression") or distribution.metadata.get(
            "License", ""
        )
        inventory.append(
            {
                "name": name,
                "version": distribution.version,
                "license_metadata": license_id,
                "notice_files": notices,
            }
        )
    runtime_candidates = [
        Path(sys.base_prefix) / "LICENSE.txt",
        Path(sys.base_prefix) / "LICENSE",
        Path(sys.base_prefix) / "Lib" / "LICENSE.txt",
        Path(sys.base_prefix)
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "LICENSE.txt",
    ]
    runtime_license = next((p for p in runtime_candidates if p.is_file()), None)
    if runtime_license is None:
        raise RuntimeError(
            "Python runtime license not found; add it before distributing the executable"
        )
    shutil.copyfile(runtime_license, output / "PYTHON-LICENSE.txt")
    pinned = {}
    if any(p["name"].lower() == "pystray" for p in inventory):
        # LGPL pystray remains separately licensed. Include its exact locked, unmodified source.
        lock = tomllib.loads(lock_path.read_text())
        pystray = next(p for p in lock["package"] if p["name"] == "pystray")
        pinned = json.loads(
            (lock_path.parent / "scripts" / "third-party-sources.json").read_text()
        )["pystray"]
        if pystray["version"] != pinned["version"]:
            raise RuntimeError(
                "Update and review the pinned pystray source when changing its version"
            )
        parsed = urlparse(pinned["url"])
        if parsed.scheme != "https" or parsed.hostname != "codeload.github.com":
            raise RuntimeError(
                "Expected an upstream pystray source archive from codeload.github.com"
            )
        with urlopen(pinned["url"], timeout=30) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != pinned["sha256"]:
            raise RuntimeError(
                "pystray upstream source hash does not match the reviewed source pin"
            )
        source_dir = output / "sources"
        source_dir.mkdir(exist_ok=True)
        (source_dir / pinned["filename"]).write_bytes(data)
    (output / "inventory.json").write_text(
        json.dumps(
            {
                "scope": "Installed build environment; may include tools not bundled in the executable",
                "python_version": sys.version.split()[0],
                "packages": inventory,
                "pystray_source_sha256": pinned.get("sha256"),
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Collected notices for {len(inventory)} distributions (including source when required)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist/third-party"))
    parser.add_argument("--lock", type=Path, default=Path("uv.lock"))
    args = parser.parse_args()
    collect(args.output, args.lock)
