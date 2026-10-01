"""Offline integration checks for the public POSIX download entry point.

Run directly with: python -m unittest discover -s tests -p test_download_installer.py
"""

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "packaging" / "download.sh"
VERSION = json.loads((PROJECT / "package.json").read_text())["version"]
BASE_URL = f"https://github.com/zhengye123188/research-cli/releases/download/v{VERSION}"


class DownloadInstallerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="research download 研究 ")
        self.root = Path(self.directory.name)
        self.bin = self.root / "bin"
        self.fixtures = self.root / "fixtures"
        self.downloads = self.root / "temporary files"
        for directory in (self.bin, self.fixtures, self.downloads):
            directory.mkdir()
        self.marker = self.root / "executed.json"
        self.log = self.root / "curl.jsonl"
        self.env = {
            **os.environ,
            "PATH": str(self.bin),
            "TMPDIR": str(self.downloads),
            "TEST_FIXTURES": str(self.fixtures),
            "TEST_EXEC_MARKER": str(self.marker),
            "TEST_CURL_LOG": str(self.log),
            "TEST_SYSTEM": "Darwin",
            "TEST_ARCHITECTURE": "arm64",
        }
        for name in ("sh", "mktemp", "rm", "cat"):
            target = shutil.which(name)
            self.assertIsNotNone(target)
            (self.bin / name).symlink_to(target)
        self.write_executable(
            "uname",
            "import os, sys\n"
            "print(os.environ['TEST_SYSTEM' if sys.argv[1] == '-s' "
            "else 'TEST_ARCHITECTURE'])\n",
        )
        self.write_executable(
            "curl",
            "import json, os, pathlib, shutil, sys\n"
            "args = sys.argv[1:]\n"
            "with open(os.environ['TEST_CURL_LOG'], 'a') as log:\n"
            "    log.write(json.dumps(args) + '\\n')\n"
            "url = args[-1]\n"
            "if os.environ.get('TEST_CURL_FAIL_MATCH', '\\0') in url:\n"
            "    sys.exit(22)\n"
            "target = args[args.index('--output') + 1]\n"
            "fixture = pathlib.Path(os.environ['TEST_FIXTURES']) / url.rsplit('/', 1)[1]\n"
            "shutil.copyfile(fixture, target)\n",
        )
        self.hash_program = (
            "import hashlib, sys\n"
            "assert sys.argv[1:] in ([], ['-a', '256'])\n"
            "print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest() + '  -')\n"
        )
        self.write_executable("shasum", self.hash_program)
        payload = self.root / "payload.py"
        payload.write_text(
            "import json, os, pathlib, sys\n"
            "pathlib.Path(os.environ['TEST_EXEC_MARKER']).write_text(\n"
            "    json.dumps({'args': sys.argv[1:], 'stdin': sys.stdin.read()}))\n"
            "sys.exit(int(os.environ.get('TEST_INSTALL_EXIT', '0')))\n"
        )
        self.installer = (
            f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(payload))} "$@"\n'
        ).encode()
        digest = hashlib.sha256(self.installer).hexdigest()
        for platform in ("darwin-arm64", "darwin-x64", "linux-arm64", "linux-x64"):
            name = self.asset(platform)
            (self.fixtures / name).write_bytes(self.installer)
            (self.fixtures / f"{name}.sha256").write_text(f"{digest}  {name}\n")

    def tearDown(self):
        self.directory.cleanup()

    def write_executable(self, name, source):
        path = self.bin / name
        code = self.bin / f"{name}.py"
        code.write_text(source)
        path.write_text(
            f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(code))} "$@"\n'
        )
        path.chmod(0o755)

    @staticmethod
    def asset(platform):
        return f"research-cli-{VERSION}-{platform}.run"

    def run_download(self, *args, piped=False):
        command = ["/bin/sh", "-s", "--", *args] if piped else ["/bin/sh", str(SCRIPT), *args]
        result = subprocess.run(
            command,
            input=SCRIPT.read_text() if piped else "",
            text=True,
            capture_output=True,
            env=self.env,
            timeout=15,
        )
        self.assertEqual(list(self.downloads.iterdir()), [], "Temporary files were not removed")
        return result

    def curl_calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_all_platforms_select_matching_release_assets_over_https(self):
        for system, architecture, platform in (
            ("Darwin", "arm64", "darwin-arm64"),
            ("Darwin", "x86_64", "darwin-x64"),
            ("Linux", "aarch64", "linux-arm64"),
            ("Linux", "amd64", "linux-x64"),
        ):
            with self.subTest(platform=platform):
                self.env.update(TEST_SYSTEM=system, TEST_ARCHITECTURE=architecture)
                self.log.unlink(missing_ok=True)
                result = self.run_download()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(self.marker.exists())
                name = self.asset(platform)
                calls = self.curl_calls()
                self.assertEqual(
                    [call[-1] for call in calls],
                    [
                        f"{BASE_URL}/{name}",
                        f"{BASE_URL}/{name}.sha256",
                    ],
                )
                for call in calls:
                    self.assertEqual(call[call.index("--proto") + 1], "=https")
                    self.assertEqual(call[call.index("--proto-redir") + 1], "=https")
                    self.assertEqual(call[call.index("--retry") + 1], "3")

    def test_piped_script_forwards_arguments_with_spaces_and_empty_stdin(self):
        args = ["--prefix", str(self.root / "研究 CLI"), "--bin-dir", str(self.root / "my bin")]
        result = self.run_download(*args, piped=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.marker.read_text()), {"args": args, "stdin": ""})

    def test_checksum_mismatch_never_executes_installer(self):
        path = self.fixtures / self.asset("darwin-arm64")
        path.write_bytes(self.installer + b"# changed\n")
        result = self.run_download()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum failed", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_malformed_checksum_and_unexpected_filenames_never_execute(self):
        name = self.asset("darwin-arm64")
        digest = hashlib.sha256(self.installer).hexdigest()
        records = [
            f"{digest}  ../{name}\n",
            f"{digest}  unexpected.run\n",
            f"{digest}  {name}\n{digest}  unexpected.run\n",
            f"{digest}  {name}; touch injected\n",
            f"{'0' * 63}  {name}\n",
            f"{'g' * 64}  {name}\n",
            f"{digest}  *{name}\n",
        ]
        for record in records:
            with self.subTest(record=record):
                (self.fixtures / f"{name}.sha256").write_text(record)
                result = self.run_download()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid installer checksum file", result.stderr)
                self.assertFalse(self.marker.exists())

    def test_sha256sum_fallback(self):
        (self.bin / "shasum").unlink()
        self.write_executable("sha256sum", self.hash_program)
        result = self.run_download()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.marker.exists())

    def test_missing_checksum_utility_does_not_download(self):
        (self.bin / "shasum").unlink()
        result = self.run_download()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing SHA-256 utility", result.stderr)
        self.assertEqual(self.curl_calls(), [])
        self.assertFalse(self.marker.exists())

    def test_download_failure_never_executes_and_cleans_temporary_files(self):
        self.env["TEST_CURL_FAIL_MATCH"] = ".sha256"
        result = self.run_download()
        self.assertEqual(result.returncode, 22)
        self.assertFalse(self.marker.exists())

    def test_installer_failure_preserves_exit_status_and_cleans_temporary_files(self):
        self.env["TEST_INSTALL_EXIT"] = "7"
        result = self.run_download()
        self.assertEqual(result.returncode, 7)
        self.assertTrue(self.marker.exists())

    def test_unsupported_platforms_do_not_download(self):
        for system, architecture in (("Windows_NT", "x86_64"), ("Linux", "riscv64")):
            with self.subTest(system=system, architecture=architecture):
                self.env.update(TEST_SYSTEM=system, TEST_ARCHITECTURE=architecture)
                result = self.run_download()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Unsupported", result.stderr)
                self.assertEqual(self.curl_calls(), [])
                self.assertFalse(self.marker.exists())

    def test_help_does_not_download(self):
        result = self.run_download("--help", piped=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--prefix", result.stdout)
        self.assertEqual(self.curl_calls(), [])


if __name__ == "__main__":
    unittest.main()
