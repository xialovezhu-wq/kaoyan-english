"""Targeted tests for the standalone historical English source verifier."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts" / "verify_historical_source_closure_english.py"
MANIFEST_PATH = ROOT / "schema" / "study-intake-historical-source-closure-v1.json"
HISTORICAL_ROOT = ROOT.parents[3] / "kaoyan-english"

_SPEC = importlib.util.spec_from_file_location(
    "verify_historical_source_closure_english", VERIFIER_PATH
)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"cannot load verifier from {VERIFIER_PATH}")
_VERIFIER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_VERIFIER)


class HistoricalSourceClosureEnglishTests(unittest.TestCase):
    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, str(VERIFIER_PATH), *arguments],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_manifest_is_frozen_compact_and_has_no_machine_paths(self) -> None:
        raw = MANIFEST_PATH.read_text(encoding="utf-8")
        manifest = json.loads(raw)
        self.assertEqual(manifest["schema_version"], "study-intake-historical-source-closure-v1")
        self.assertEqual(manifest["subject"], "english")
        self.assertEqual(manifest["file_count"], 20)
        self.assertEqual(manifest["total_bytes"], 251077)
        self.assertEqual(len(manifest["ordered_paths"]), 20)
        self.assertEqual(len(manifest["files"]), 20)
        self.assertEqual(
            {
                entry["classification"]
                for entry in manifest["files"]
            },
            {"replaced_by_current", "evidence_only", "restore_required"},
        )
        self.assertEqual(
            sum(entry["classification"] == "replaced_by_current" for entry in manifest["files"]),
            14,
        )
        self.assertEqual(
            sum(entry["classification"] == "evidence_only" for entry in manifest["files"]),
            2,
        )
        self.assertEqual(
            sum(entry["classification"] == "restore_required" for entry in manifest["files"]),
            4,
        )
        self.assertEqual(
            raw,
            json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + "\n",
        )
        self.assertNotIn("/Users/", raw)
        self.assertNotIn("/home/", raw)

    def test_ordered_raw_bytes_algorithm_reproduces_frozen_bundle(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        rows = [(entry["file_sha256"], entry["path"]) for entry in manifest["files"]]
        self.assertEqual(_VERIFIER.ordered_bytes_digest(rows), manifest["bundle_sha256"])
        self.assertEqual(
            manifest["ordered_raw_bytes_algorithm"]["record"],
            "<file_sha256><two spaces><repo-relative-path><LF>",
        )

    def test_canonical_default_and_explicit_root_pass(self) -> None:
        for arguments in (
            ("canonical",),
            ("canonical", "--repo-root", str(ROOT)),
        ):
            with self.subTest(arguments=arguments):
                result = self._run(*arguments)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["status"], "PASS")
                self.assertEqual(payload["mode"], "canonical")
                self.assertEqual(
                    payload["restore_required"],
                    [
                        "prompts/codex_prompt.md",
                        "schema/schema.md",
                        "schema/protected_exam_analysis.md",
                        "schema/reference_grounded_examples.md",
                    ],
                )
                self.assertEqual(payload["classification_counts"]["replaced_by_current"], 14)
                self.assertEqual(payload["classification_counts"]["evidence_only"], 2)
                self.assertEqual(payload["classification_counts"]["restore_required"], 4)
                self.assertEqual(payload["replacement_references_checked"], 14)

    def test_external_requires_explicit_source_root(self) -> None:
        result = self._run("external")
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAIL")
        self.assertIn("--source-root", payload["errors"][0])

    def test_external_recomputes_all_twenty_fixed_files(self) -> None:
        self.assertTrue(HISTORICAL_ROOT.is_dir())
        result = self._run("external", "--source-root", str(HISTORICAL_ROOT))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["mode"], "external")
        self.assertEqual(payload["file_count"], 20)
        self.assertEqual(payload["total_bytes"], 251077)
        self.assertEqual(payload["restore_required"], [])

if __name__ == "__main__":  # pragma: no cover
    unittest.main()
