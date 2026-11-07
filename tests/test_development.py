import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


DEV = module("mousepilot_dev", "scripts/dev.py")
HOOKS = module("mousepilot_hooks", "scripts/install-hooks.py")


class DevelopmentTests(unittest.TestCase):
    def test_help_and_unsupported_commands_do_not_run_tools(self):
        with patch.object(DEV, "run") as run:
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(DEV.main(["help"]), 0)
                for command in ("install", "reinstall", "uninstall", "publish"):
                    self.assertEqual(DEV.main([command]), 2)
            run.assert_not_called()

    def artifact(self, root, version="0.1.0b0", native=False):
        path = root / ("mousepilot-windows-x64.zip" if native else "mousepilot.whl")
        with zipfile.ZipFile(path, "w") as archive:
            if native:
                archive.writestr("mousepilot-server.exe", b"test application")
                archive.writestr(
                    "package-info.json", json.dumps({"project": "mousepilot", "version": version})
                )
            else:
                archive.writestr(
                    "mousepilot.dist-info/METADATA", f"Name: mousepilot\nVersion: {version}\n"
                )
        manifest = root / "release-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "project": "mousepilot",
                    "version": "0.1.0b0",
                    "artifacts": [{"file": path.name, "sha256": DEV.digest(path)}],
                }
            )
        )
        return path

    def test_verified_artifact_rejects_changed_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.artifact(Path(temporary))
            DEV.verify_artifact(path, "0.1.0b0")
            with path.open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(ValueError, "hash"):
                DEV.verify_artifact(path, "0.1.0b0")

    def test_wheel_and_native_metadata_must_match_manifest(self):
        for native in (False, True):
            with self.subTest(native=native), tempfile.TemporaryDirectory() as temporary:
                path = self.artifact(Path(temporary), version="0.0.1", native=native)
                with self.assertRaisesRegex(ValueError, "metadata"):
                    DEV.verify_artifact(path, "0.1.0b0")


@unittest.skipUnless(shutil.which("git"), "Git is required")
class HookTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mousepilot hooks ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        (self.root / "scripts").mkdir()
        (self.root / "scripts/check-public-files.py").write_text('print("checked")\n')

    def test_installs_owned_hook_with_space_in_path(self):
        hook = HOOKS.install(self.root)
        self.assertIn(HOOKS.MARKER, hook.read_text())
        self.assertEqual(HOOKS.install(self.root), hook)

    def test_preserves_existing_hook(self):
        hook = self.root / ".git/hooks/pre-commit"
        hook.write_text("existing hook\n")
        with self.assertRaises(ValueError):
            HOOKS.install(self.root)
        self.assertEqual(hook.read_text(), "existing hook\n")

    def test_preserves_hook_manager(self):
        subprocess.run(
            ["git", "config", "core.hooksPath", "custom-hooks"], cwd=self.root, check=True
        )
        with self.assertRaisesRegex(ValueError, "manager"):
            HOOKS.install(self.root)
        self.assertFalse((self.root / "custom-hooks").exists())
