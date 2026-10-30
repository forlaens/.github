import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
import os

spec = importlib.util.spec_from_file_location("security", Path(__file__).with_name("security.py"))
security = importlib.util.module_from_spec(spec)
spec.loader.exec_module(security)


class SecretsTest(unittest.TestCase):
    def test_secret_in_intermediate_commit_is_blocked_and_redacted(self):
        executable = security.binary("gitleaks")
        with tempfile.TemporaryDirectory() as directory:
            def git(*args):
                return subprocess.run(["git", *args], cwd=directory, check=True, capture_output=True, text=True).stdout.strip()
            git("init")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.invalid")
            path = Path(directory) / "example.txt"
            path.write_text("safe\n")
            git("add", ".")
            git("commit", "-m", "Safe baseline")
            base = git("rev-parse", "HEAD")
            fixture = "ghp_" + "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8"
            path.write_text("token=" + fixture)
            git("commit", "-am", "Synthetic secret fixture")
            path.write_text("safe again\n")
            git("commit", "-am", "Remove fixture")
            result = subprocess.run([str(executable), "git", "--redact=100", "--log-opts", base + "..HEAD"], cwd=directory, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn(fixture, result.stdout + result.stderr)
            clean = subprocess.run([str(executable), "dir", "--redact=100", directory], capture_output=True, text=True)
            self.assertEqual(clean.returncode, 0)

    def test_dom_xss_fixture_fails_static_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "unsafe.js"
            fixture.write_text("document.body.innerHTML = location.hash;\n")
            env = {k: v for k, v in os.environ.items() if not k.startswith("SEMGREP_")}
            result = subprocess.run([str(security.python_tools() / "semgrep"), "scan", "--metrics=off", "--disable-version-check", "--config", str(Path(__file__).with_name("security-rules.yml")), "--severity", "ERROR", "--error", str(fixture)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
