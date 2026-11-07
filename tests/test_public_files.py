"""Regression checks for the staged-file publication guard, without real credentials."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("git"), "Git is required for publication checks")
class PublicFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.script = Path(__file__).resolve().parents[1] / "scripts" / "check-public-files.py"
        self.git("init", "-q")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def stage(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        self.git("add", "--force", "--", name)
        return path

    def check(self):
        return subprocess.run(
            [sys.executable, str(self.script)], cwd=self.root, capture_output=True, text=True
        )

    def test_public_examples_are_allowed(self):
        self.stage("examples/devices.toml", 'expected_device_id = "REPLACE_ME"\n')
        self.stage("examples/mcp-config.json", "{}\n")
        self.assertEqual(self.check().returncode, 0)

    def test_local_assistant_files_are_not_public(self):
        for name in (
            "nested/AgEnTs.Md",
            ".claude/settings.json",
            ".codex/config.toml",
            ".mcp.json",
        ):
            with self.subTest(name=name):
                self.stage(name, "local settings\n")
                self.assertNotEqual(self.check().returncode, 0)

    def test_capture_cannot_be_published_even_if_force_added(self):
        self.stage("captures/private.png", "synthetic capture data")
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("captures/private.png", result.stderr)

    def test_scans_index_even_after_working_copy_is_cleaned(self):
        secret_marker = "-----BEGIN " + "PRIVATE KEY-----"
        path = self.stage("accidental.txt", secret_marker + "\nsynthetic test data\n")
        path.write_text("sanitized working copy\n")
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("accidental.txt", result.stderr)
        self.assertNotIn(secret_marker, result.stderr)
