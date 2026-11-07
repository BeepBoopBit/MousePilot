import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("git"), "Git required for release validation")
class ReleaseTagTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.script = Path(__file__).resolve().parents[1] / "scripts/check-release-tag.py"
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Release test")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "tag.gpgsign", "false")
        self.git("config", "core.hooksPath", str(self.root / "no-hooks"))
        self.root.joinpath("src/mousepilot").mkdir(parents=True)
        self.root.joinpath("pyproject.toml").write_text('[project]\nversion="0.4.1"\n')
        self.root.joinpath("src/mousepilot/protocol.py").write_text('VERSION="0.4.1"\n')
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True, text=True, timeout=10
        )

    def check(self, tag):
        return subprocess.run(
            [sys.executable, str(self.script), "--tag", tag],
            cwd=self.root,
            capture_output=True,
            text=True,
        )

    def test_main_tag_is_accepted(self):
        self.git("tag", "v0.4.1")
        self.assertEqual(self.check("v0.4.1").returncode, 0)

    def test_beta_tag_on_main_is_accepted(self):
        self.root.joinpath("pyproject.toml").write_text('[project]\nversion="0.1.0b0"\n')
        self.root.joinpath("src/mousepilot/protocol.py").write_text('VERSION="0.1.0b0"\n')
        self.git("add", ".")
        self.git("commit", "-qm", "initial beta")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("tag", "v0.1.0b0")
        self.assertEqual(self.check("v0.1.0b0").returncode, 0)

    def test_noncanonical_beta_tags_are_rejected(self):
        for tag in ("v0.1.0-beta", "v0.1.0b", "v0.1.0b00"):
            with self.subTest(tag=tag):
                self.assertIn("Use vMAJOR", self.check(tag).stderr)

    def test_feature_branch_tag_is_rejected(self):
        self.git("checkout", "-qb", "feature")
        self.root.joinpath("feature.txt").write_text("unmerged")
        self.git("add", ".")
        self.git("commit", "-qm", "unmerged feature")
        self.git("tag", "v0.4.1")
        self.assertIn("must belong to main", self.check("v0.4.1").stderr)

    def test_version_mismatch_is_rejected(self):
        self.git("tag", "v0.5.0")
        self.assertIn("must match", self.check("v0.5.0").stderr)

    def test_malformed_tag_is_rejected(self):
        self.assertNotEqual(self.check("v0.4.1-rc1").returncode, 0)

    def test_checkout_after_tag_is_rejected(self):
        self.git("tag", "v0.4.1")
        self.root.joinpath("later.txt").write_text("later")
        self.git("add", ".")
        self.git("commit", "-qm", "later")
        self.assertIn("exact tagged commit", self.check("v0.4.1").stderr)
