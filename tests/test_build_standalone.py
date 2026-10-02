"""Offline checks for OCR assets and their selection in a standalone installation."""

from __future__ import annotations

import hashlib
import importlib.util
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
SPEC = importlib.util.spec_from_file_location(
    "research_standalone_build", PROJECT / "scripts/build_standalone.py"
)
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


@unittest.skipUnless(shutil.which("node"), "Bundling OCR requires the selected Node runtime")
class StandaloneOcrTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="research OCR 研究 ")
        self.bundle = Path(self.temporary.name).resolve() / "bundle with spaces"
        (self.bundle / "app/bin").mkdir(parents=True)
        self.module = self.bundle / "app/bin/ocr.mjs"
        self.module.write_text("""
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
export const OCR_LICENSE = { url: 'https://raw.githubusercontent.com/example/pin/LICENSE', size: 7, sha256: createHash('sha256').update('license').digest('hex') };
export async function installOcrModels(languages, { env }) {
  if (JSON.stringify(languages) !== JSON.stringify(['eng', 'chi_sim', 'chi_tra'])) throw new Error('Missing a bundled language');
  const directory = env.RESEARCH_OCR_TESSDATA;
  mkdirSync(directory, { recursive: true });
  const models = languages.map(language => {
    const data = Buffer.from(`fixture ${language}`), path = join(directory, `${language}.traineddata`);
    writeFileSync(path, data);
    return { language, path, size: data.length, sha256: createHash('sha256').update(data).digest('hex') };
  });
  return { source: 'fixture official pinned OCR source', models };
}
export async function downloadOcrLicense() { return Buffer.from('license'); }
""")

    def tearDown(self):
        self.temporary.cleanup()

    def test_models_license_and_manifest_are_relocatable_and_covered_by_bundle_hashes(self):
        metadata = BUILD.bundle_ocr_assets(
            self.bundle,
            shutil.which("node"),
            {
                **os.environ,
                "RESEARCH_OCR_TESSDATA": str(self.bundle / "never-selected"),
            },
        )
        self.assertEqual(
            [model["language"] for model in metadata["models"]], ["eng", "chi_sim", "chi_tra"]
        )
        self.assertEqual(metadata["license"]["path"], "licenses/tessdata-fast.txt")
        self.assertEqual((self.bundle / "licenses/tessdata-fast.txt").read_bytes(), b"license")
        self.assertFalse((self.bundle / "never-selected").exists())
        self.assertEqual(json.loads((self.bundle / "app/ocr/manifest.json").read_text()), metadata)
        for model in metadata["models"]:
            path = self.bundle / model["path"]
            self.assertTrue(model["path"].startswith("app/ocr/tessdata/"))
            self.assertFalse(Path(model["path"]).is_absolute())
            self.assertEqual(path.stat().st_size, model["size"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), model["sha256"])
        BUILD.write_manifest(
            self.bundle,
            "test",
            "darwin-arm64",
            {"node_version": "22", "python_version": "3.12"},
            {"ocr": metadata},
        )
        manifest = json.loads((self.bundle / "bundle.json").read_text())
        self.assertEqual(manifest["runtimes"]["ocr"], metadata)
        for model in [*metadata["models"], metadata["license"]]:
            self.assertEqual(manifest["files"][model["path"]]["sha256"], model["sha256"])

    def test_license_verification_failure_stops_build_before_manifest_is_written(self):
        self.module.write_text(
            self.module.read_text().replace(
                "return Buffer.from('license');",
                "throw new Error('Pinned license verification failed');",
            )
        )
        with self.assertRaises(subprocess.CalledProcessError):
            BUILD.bundle_ocr_assets(self.bundle, shutil.which("node"), os.environ.copy())
        self.assertFalse((self.bundle / "app/ocr/manifest.json").exists())
        self.assertFalse((self.bundle / "licenses/tessdata-fast.txt").exists())

    def test_standalone_launcher_selects_embedded_models_and_preserves_explicit_selection(self):
        (self.bundle / "bin").mkdir()
        launcher = self.bundle / "bin/research"
        shutil.copy2(PROJECT / "packaging/research", launcher)
        runtime_node = self.bundle / "runtime/node/bin/node"
        runtime_node.parent.mkdir(parents=True)
        capture = self.bundle / "capture.py"
        capture.write_text(
            "import json, os, sys\nprint(json.dumps({'args': sys.argv[1:], 'ocr': os.environ['RESEARCH_OCR_TESSDATA'], 'python': os.environ['RESEARCH_PYTHON']}))\n"
        )
        runtime_node.write_text(
            f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(capture))} "$@"\n'
        )
        runtime_node.chmod(0o755)
        for selected in (None, str(self.bundle / "explicit models")):
            with self.subTest(selected=selected):
                env = os.environ.copy()
                env.pop("RESEARCH_OCR_TESSDATA", None)
                if selected is not None:
                    env["RESEARCH_OCR_TESSDATA"] = selected
                result = subprocess.run(
                    ["/bin/sh", str(launcher), "ocr", "list"],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=5,
                )
                actual = json.loads(result.stdout)
                self.assertEqual(actual["ocr"], selected or str(self.bundle / "app/ocr/tessdata"))
                self.assertEqual(actual["python"], str(self.bundle / "runtime/python/bin/python3"))
                self.assertEqual(
                    actual["args"], [str(self.bundle / "app/bin/research.mjs"), "ocr", "list"]
                )


if __name__ == "__main__":
    unittest.main()
