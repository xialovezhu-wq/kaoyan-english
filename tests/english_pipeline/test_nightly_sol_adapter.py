from __future__ import annotations

import hashlib
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/nightly_sol_adapter.py"
SPEC = importlib.util.spec_from_file_location("english_nightly_sol_adapter", MODULE_PATH)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


DATE = "2026-08-21"


def batch() -> dict:
    captures = ["CAP-EN-001", "CAP-EN-002"]
    skill_sha = adapter.sha256_file(adapter.SKILL_PATH)
    command = f"开始 {DATE} 英语正式入库"
    return {
        "schema_version": adapter.BATCH_SCHEMA,
        "batch_id": "NIGHTLY-" + "C" * 28,
        "subject": "english",
        "capture_intake_date": DATE,
        "capture_ids": captures,
        "capture_set_sha256": adapter.sha256_value(captures),
        "analysis_packages": [
            {
                "capture_id": item,
                "package_ref": "study-intake-analysis-package://sha256/" + str(index) * 64,
                "package_sha256": str(index) * 64,
            }
            for index, item in enumerate(captures, start=1)
        ],
        "skill": {
            "name": adapter.SKILL_NAME,
            "source_sha256": skill_sha,
            "declared_version": None,
        },
        "authorization": {
            "schema_version": adapter.AUTHORIZATION_SCHEMA,
            "subject": "english",
            "capture_intake_date": DATE,
            "normalized_command": command,
            "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
            "authorization_id": "NAUTH-" + adapter.sha256_value({
                "schema_version": adapter.AUTHORIZATION_SCHEMA,
                "subject": "english",
                "capture_intake_date": DATE,
                "normalized_command": command,
                "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
            })[:24].upper(),
        },
        "status": "frozen",
        "formal_write_count": 0,
    }


def apply_receipt(
    batch_value: dict,
    *,
    status: str = "APPLIED",
    formal_write_count: int = 1,
    partial: bool = False,
) -> dict:
    pre = {"master_bank": "a" * 64, "mastered_items": "b" * 64}
    post = dict(pre)
    if formal_write_count:
        post["master_bank"] = "c" * 64
    changed = pre != post
    if status.startswith("DRY_RUN_") or status == "CAS_CONFLICT":
        post = dict(pre)
        changed = False
        formal_write_count = 0
    proposed = {} if status == "CAS_CONFLICT" else dict(post)
    validation_status = "PARTIAL" if partial or status == "PARTIAL" else "PASS"
    if status in {"CAS_CONFLICT", "FAILED"}:
        validation_status = "FAIL"
    authorization = None
    if not status.startswith("DRY_RUN_") and status != "CAS_CONFLICT":
        authorization = {
            "command": "apply-nightly",
            "batch_id": batch_value["batch_id"],
            "study_date": DATE,
            "authorized_at": f"{DATE}T01:00:00+08:00",
            "scope": ["master_bank", "mastered_items", "sentence_patterns"],
        }
    result = {
        "schema_version": "english_apply_receipt_v1",
        "receipt_id": "EN-APPLY-SYNTHETIC-001",
        "batch_id": batch_value["batch_id"],
        "action_set_id": "EN-ACTIONS-SYNTHETIC-001",
        "mode": "dry_run" if status.startswith("DRY_RUN_") else "apply",
        "status": status,
        "started_at": f"{DATE}T00:59:59+08:00",
        "completed_at": f"{DATE}T01:00:00+08:00",
        "authorization": authorization,
        "manifest_sha256": "d" * 64,
        "actions_sha256": "e" * 64,
        "lock_path": "/synthetic/english.lock",
        "journal_path": "/synthetic/english.jsonl",
        "formal_prehashes": pre,
        "proposed_posthashes": proposed,
        "formal_posthashes": post,
        "formal_files_changed": changed,
        "formal_write_count": formal_write_count,
        "action_results": (
            ([{
                "action_id": "ACT-1",
                "action_type": "master_bank_insert",
                "target": "master_bank",
                "result": "applied",
                "message": "synthetic safe action",
            }] if formal_write_count else [])
            + ([{
                "action_id": "ACT-NEEDS-USER",
                "action_type": "needs_user",
                "target": "unresolved",
                "result": "needs_user",
                "message": "synthetic hard conflict",
            }] if partial else [])
        ),
        "validation": {
            "status": validation_status,
            "safe_action_count": formal_write_count,
            "unresolved_count": 1 if partial else 0,
            "formal_schema": {
                "master_bank_columns": 13,
                "mastered_items_columns": 7,
                "sentence_pattern_fields": 15,
            },
        },
    }
    return result


def execution_evidence(receipt: dict, *, exit_code: int = 0) -> dict:
    return {
        "pre_state_sha256": adapter.aggregate_state_sha256(receipt["formal_prehashes"]),
        "post_state_sha256": adapter.aggregate_state_sha256(receipt["formal_posthashes"]),
        "operations": receipt["action_results"],
        "adapter_run_id": "RUN-EN-001",
        "pid": 1001,
        "transaction_id": "TX-EN-001",
        "ended_at": f"{DATE}T01:00:00+08:00",
        "stopped_at": f"{DATE}T01:00:01+08:00",
        "exit_code": exit_code,
    }


def terminal(batch_value: dict, *, status: str = "APPLIED", selected: list[str] | None = None, conflict: dict | None = None) -> dict:
    selected = selected or batch_value["capture_ids"]
    partial = status == "PARTIAL"
    receipt = apply_receipt(batch_value, status=status, partial=partial)
    return {
        "schema_version": adapter.NATIVE_TERMINAL_SCHEMA,
        "subject": "english",
        "batch_id": batch_value["batch_id"],
        "status": status,
        "capture_results": [
            {"capture_id": capture_id, "opaque": {"English": "untouched"}}
            for capture_id in selected
        ],
        "changed_files": ["bank/master_bank.csv"] if receipt["formal_files_changed"] else [],
        "formal_write_count": receipt["formal_write_count"],
        "conflict": conflict,
        "apply_receipt": receipt,
        "apply_receipt_sha256": adapter.sha256_value(receipt),
        "recovery_receipt": None,
        "recovery_receipt_sha256": None,
        "execution_evidence": execution_evidence(receipt),
    }


class EnglishNightlySolAdapterTests(unittest.TestCase):
    def test_prepare_binds_outer_set_real_skill_and_exact_authorization(self) -> None:
        invocation = adapter.prepare_invocation(batch())
        self.assertEqual(invocation["selection_policy"], "outer_frozen_set_only")
        self.assertEqual(invocation["capture_ids"], ["CAP-EN-001", "CAP-EN-002"])
        self.assertEqual(invocation["authorization"]["schema_version"], adapter.AUTHORIZATION_SCHEMA)
        self.assertEqual(invocation["formal_write_count"], 0)

    def test_exact_authorization_and_hash_drift_fail_closed(self) -> None:
        drifted = batch()
        drifted["authorization"]["normalized_command"] = "开始今天的英语正式入库"
        with self.assertRaisesRegex(adapter.AdapterError, "nightly_command_not_exact"):
            adapter.prepare_invocation(drifted)
        drifted = batch()
        drifted["authorization"]["command_sha256"] = "f" * 64
        with self.assertRaisesRegex(adapter.AdapterError, "nightly_authorization_hash_invalid"):
            adapter.prepare_invocation(drifted)

    def test_executor_called_once_with_recursively_immutable_invocation(self) -> None:
        calls: list[dict] = []

        def executor(invocation: dict) -> dict:
            calls.append(invocation)
            with self.assertRaises(TypeError):
                invocation["capture_ids"].append("CAP-EN-003")
            return terminal(batch())

        result = adapter.EnglishNightlySolAdapter().execute(
            batch(), native_executor=executor
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["native_receipt"]["status"], "APPLIED")

    def test_actual_apply_receipt_shape_and_execution_evidence_are_bound(self) -> None:
        value = terminal(batch())
        checked = adapter.validate_native_terminal(batch(), value)
        self.assertEqual(checked["apply_receipt"]["schema_version"], "english_apply_receipt_v1")
        self.assertEqual(
            checked["execution_evidence"]["pre_state_sha256"],
            adapter.aggregate_state_sha256(checked["apply_receipt"]["formal_prehashes"]),
        )
        self.assertEqual(checked["formal_write_count"], 1)

    def test_resolution_binds_skill_and_runs_only_conflicted_capture(self) -> None:
        value = batch()
        resolution = {
            "conflict_id": "CONFLICT-USER-001",
            "batch_id": value["batch_id"],
            "subject": "english",
            "conflicted_capture_id": "CAP-EN-002",
            "user_option": "select-existing-target",
            "skill_name": value["skill"]["name"],
            "skill_source_sha256": value["skill"]["source_sha256"],
        }
        calls: list[dict] = []

        def executor(invocation: dict) -> dict:
            calls.append(invocation)
            self.assertEqual(invocation["capture_ids"], ["CAP-EN-002"])
            self.assertEqual(invocation["selection_policy"], "conflicted_capture_only")
            self.assertEqual(invocation["resolution"]["conflicted_capture_id"], "CAP-EN-002")
            return terminal(value, selected=["CAP-EN-002"])

        result = adapter.EnglishNightlySolAdapter().execute(
            value,
            native_executor=executor,
            resolution=resolution,
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["status"], "complete")

    def test_capture_result_scope_and_apply_hash_drift_fail_closed(self) -> None:
        value = batch()
        malformed = terminal(value)
        malformed["capture_results"] = malformed["capture_results"][:1]
        with self.assertRaisesRegex(adapter.AdapterError, "native_terminal_capture_results_incomplete"):
            adapter.validate_native_terminal(value, malformed)
        drifted = terminal(value)
        drifted["apply_receipt"]["formal_write_count"] = 99
        with self.assertRaisesRegex(
            adapter.AdapterError,
            "apply_receipt_(action_count_mismatch|hash_invalid)",
        ):
            adapter.EnglishNightlySolAdapter().execute(
                value, native_executor=lambda _invocation: drifted
            )

    def test_partial_safe_items_are_isolated_from_hard_conflict(self) -> None:
        value = batch()
        conflict = {
            "kind": "ambiguous_formal_target",
            "capture_id": "CAP-EN-002",
        }
        native = terminal(value, status="PARTIAL", conflict=conflict)
        native["capture_results"][1]["status"] = "needs_user"
        result = adapter.EnglishNightlySolAdapter().execute(
            value, native_executor=lambda _invocation: native
        )
        self.assertEqual(result["status"], "awaiting_user")
        self.assertTrue(result["conflict_id"].startswith("CONFLICT-"))

    def test_legacy_wrap_cannot_bypass_strict_terminal_contract(self) -> None:
        value = batch()
        native = {
            "schema_version": "english_apply_receipt_v1",
            "subject": "english",
            "batch_id": value["batch_id"],
            "status": "committed",
            "capture_results": [{"capture_id": "CAP-EN-001", "opaque": {"x": 1}}],
            "changed_files": ["bank/master_bank.csv"],
            "formal_write_count": 1,
            "conflict": None,
        }
        with self.assertRaisesRegex(
            adapter.AdapterError, "native_terminal_schema_required"
        ):
            adapter.wrap_native_receipt(value, native)


if __name__ == "__main__":
    unittest.main()
