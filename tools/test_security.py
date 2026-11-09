import hashlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import call, patch
from urllib.error import HTTPError
import os

spec = importlib.util.spec_from_file_location("security", Path(__file__).with_name("security.py"))
security = importlib.util.module_from_spec(spec)
spec.loader.exec_module(security)


class BinaryDownloadTest(unittest.TestCase):
    def test_retries_gateway_error_with_the_same_pinned_checksum(self):
        payload = b"test binary"
        archive_bytes = io.BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode="w:gz") as archive:
            member = tarfile.TarInfo("tool")
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
        data = archive_bytes.getvalue()
        checksum = hashlib.sha256(data).hexdigest()
        binaries = {"tool": ("example/tool", "1.0", {"Linux-x86_64": ("linux", checksum)})}
        url = "https://github.com/example/tool/releases/download/v1.0/tool_1.0_linux.tar.gz"
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(security, "CACHE", Path(directory)), \
                patch.object(security, "BINARIES", binaries), \
                patch.object(security.platform, "system", return_value="Linux"), \
                patch.object(security.platform, "machine", return_value="x86_64"), \
                patch.object(security.urllib.request, "urlopen") as download:
            gateway_error = HTTPError(url, 504, "Gateway Timeout", None, None)
            release = b'{"assets":[{"name":"other.tar.gz","id":2},{"name":"tool_1.0_linux.tar.gz","id":3}]}'
            download.side_effect = [gateway_error, io.BytesIO(release), io.BytesIO(data)]
            self.assertEqual(security.binary("tool").read_bytes(), payload)
            self.assertEqual(download.call_args_list[:2], [
                call(url, timeout=60),
                call("https://api.github.com/repos/example/tool/releases/tags/v1.0", timeout=60),
            ])
            self.assertEqual(download.call_count, 3)
            request = download.call_args.args[0]
            self.assertEqual(request.full_url, "https://api.github.com/repos/example/tool/releases/assets/3")
            self.assertEqual(request.get_header("Accept"), "application/octet-stream")


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
