"""Validate that a release tag checks out the matching version on main's history."""

import argparse
import ast
import re
import subprocess
import tomllib
from pathlib import Path


def git(*args):
    return subprocess.check_output(["git", *args], stderr=subprocess.PIPE, text=True).strip()


def validate(tag, main_ref="refs/remotes/origin/main"):
    if not re.fullmatch(
        r"v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:b(?:0|[1-9]\d*))?", tag
    ):
        raise ValueError("Use vMAJOR.MINOR.PATCH or a beta tag such as v0.1.0b0")
    version = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
    module = ast.parse(Path("src/mousepilot/protocol.py").read_text())
    protocol_version = next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in node.targets)
    )
    if tag != "v" + version or version != protocol_version:
        raise ValueError("Tag, project version, and backend version must match")
    commit = git("rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
    if commit != git("rev-parse", "HEAD"):
        raise ValueError("Checkout must be the exact tagged commit")
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, main_ref], capture_output=True
    )
    if result.returncode:
        raise ValueError(
            "The tagged commit must belong to main; checkout full history including origin/main"
        )
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--main-ref", default="refs/remotes/origin/main")
    args = parser.parse_args()
    try:
        print(f"Release eligible: {validate(args.tag, args.main_ref)}")
    except (ValueError, StopIteration, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Release rejected: {exc}\n")
