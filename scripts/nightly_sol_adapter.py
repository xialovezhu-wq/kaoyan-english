#!/usr/bin/env python3
"""Thin Study Intake V2 adapter for canonical English daily curation.

The adapter validates an already frozen outer Capture set and delegates one
immutable invocation to the canonical native terminal.  It never scans for
more captures and never interprets or writes English bank or sentence-pattern
fields.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "study-intake-subject-sol-adapter-invocation-v1"
RESULT_SCHEMA = "study-intake-nightly-sol-adapter-result-v1"
BATCH_SCHEMA = "study-intake-nightly-sol-batch-v2"
AUTHORIZATION_SCHEMA = "study-intake-nightly-command-authorization-v1"
NATIVE_TERMINAL_SCHEMA = "english-daily-curation-native-terminal-v1"
RECOVERY_SCHEMA = "english_recovery_receipt_v1"
SUBJECT = "english"
ADAPTER_NAME = "EnglishNightlySolAdapter"
REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "kaoyan-english-daily-intake-curation"
SKILL_PATH = REPO_ROOT / "codex-skill-sources" / SKILL_NAME / "SKILL.md"
NATIVE_ENTRYPOINTS = (
    "scripts/english_learning_pipeline.py",
    "schema/english_pipeline/nightly-manifest-v1.schema.json",
    "schema/english_pipeline/sol-actions-v1.schema.json",
    "schema/english_pipeline/apply-receipt-v1.schema.json",
)
HARD_CONFLICT_KINDS = {
    "ambiguous_formal_target",
    "immutable_source_conflict",
    "material_formal_choice",
}
BATCH_ID = re.compile(r"^NIGHTLY-[A-F0-9]{28}$")
AUTHORIZATION_KEYS = {
    "schema_version",
    "subject",
    "capture_intake_date",
    "normalized_command",
    "command_sha256",
    "authorization_id",
}
RESOLUTION_KEYS = {
    "conflict_id",
    "batch_id",
    "subject",
    "conflicted_capture_id",
    "user_option",
    "skill_name",
    "skill_source_sha256",
}
EXECUTION_EVIDENCE_KEYS = {
    "pre_state_sha256",
    "post_state_sha256",
    "operations",
    "adapter_run_id",
    "pid",
    "transaction_id",
    "ended_at",
    "stopped_at",
    "exit_code",
}
NATIVE_TERMINAL_REQUIRED = {
    "schema_version",
    "subject",
    "batch_id",
    "status",
    "capture_results",
    "changed_files",
    "formal_write_count",
    "conflict",
    "apply_receipt",
    "apply_receipt_sha256",
    "recovery_receipt",
    "recovery_receipt_sha256",
    "execution_evidence",
}
# These are fields that may be present in a terminal envelope without being
# consumed by this adapter. They are deliberately limited to receipt
# identity/timing metadata; English content remains opaque.
NATIVE_TERMINAL_OPTIONAL = {"receipt_id", "started_at", "completed_at"}
NATIVE_TERMINAL_STATUSES = {
    "APPLIED",
    "PARTIAL",
    "NO_ACTION",
    "NEEDS_USER",
    "CAS_CONFLICT",
    "FAILED",
    # Lower-case aliases are accepted at this outer terminal boundary; the
    # embedded writer receipt remains bound to its canonical upper-case enum.
    "applied",
    "partial",
    "no_action",
    "needs_user",
    "cas_conflict",
    "failed",
}
LEGACY_NATIVE_STATUSES = {
    "committed",
    "noop",
    "partial",
    "awaiting_user",
    "failed",
}
APPLY_RECEIPT_KEYS = {
    "schema_version",
    "receipt_id",
    "batch_id",
    "action_set_id",
    "mode",
    "status",
    "started_at",
    "completed_at",
    "authorization",
    "manifest_sha256",
    "actions_sha256",
    "lock_path",
    "journal_path",
    "formal_prehashes",
    "proposed_posthashes",
    "formal_posthashes",
    "formal_files_changed",
    "formal_write_count",
    "action_results",
    "validation",
    "error",
}
APPLY_RECEIPT_REQUIRED = {
    *APPLY_RECEIPT_KEYS,
}
APPLY_RECEIPT_REQUIRED.remove("error")
APPLY_STATUSES = {
    "DRY_RUN_VALID",
    "DRY_RUN_PARTIAL",
    "DRY_RUN_NO_ACTION",
    "APPLIED",
    "PARTIAL",
    "NO_ACTION",
    "FAILED",
    "CAS_CONFLICT",
    "RECOVERED_ROLLBACK",
    "RECOVERED_COMMIT",
}
ACTION_TYPES = {
    "master_bank_insert",
    "master_bank_update",
    "mastered_insert",
    "sentence_pattern_append",
    "sentence_pattern_merge",
    "skip_duplicate",
    "needs_user",
}
ACTION_RESULTS = {"would_apply", "applied", "skipped", "needs_user", "failed"}
RECOVERY_KEYS = {
    "schema_version",
    "receipt_id",
    "receipt_path",
    "status",
    "recovered",
    "formal_write_count",
}


class AdapterError(ValueError):
    pass


class _FrozenDict(dict):
    """A JSON-compatible recursively immutable mapping for native callers."""

    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("immutable native invocation")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


class _FrozenList(list):
    """A JSON-compatible recursively immutable sequence for native callers."""

    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("immutable native invocation")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable
    append = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenDict({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return _FrozenList(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def aggregate_state_sha256(value: Mapping[str, Any]) -> str:
    """Aggregate a formal hash map without interpreting any English fields."""

    if not isinstance(value, Mapping):
        raise AdapterError("execution_state_hashes_invalid")
    return sha256_value(dict(sorted(value.items())))


def _date(value: Any) -> str:
    if not isinstance(value, str):
        raise AdapterError("capture_intake_date_invalid")
    try:
        if dt.date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError as exc:
        raise AdapterError("capture_intake_date_invalid") from exc
    return value


def _sha(value: Any, code: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise AdapterError(code)
    return value


def _nonempty_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdapterError(code)
    return value


def _timestamp(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise AdapterError(code)
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise AdapterError(code) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AdapterError(code)
    return value


def _validate_authorization(value: Any, *, capture_intake_date: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != AUTHORIZATION_KEYS:
        raise AdapterError("nightly_authorization_shape_invalid")
    if value.get("schema_version") != AUTHORIZATION_SCHEMA:
        raise AdapterError("nightly_authorization_schema_invalid")
    if value.get("subject") != SUBJECT:
        raise AdapterError("nightly_authorization_subject_invalid")
    if value.get("capture_intake_date") != capture_intake_date:
        raise AdapterError("nightly_authorization_date_invalid")
    normalized = value.get("normalized_command")
    if not isinstance(normalized, str):
        raise AdapterError("nightly_command_not_exact")
    match = re.fullmatch(r"开始 (\d{4}-\d{2}-\d{2}) 英语正式入库", normalized)
    if match is None or match.group(1) != capture_intake_date:
        raise AdapterError("nightly_command_not_exact")
    _date(match.group(1))
    command_sha = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    if value.get("command_sha256") != command_sha:
        raise AdapterError("nightly_authorization_hash_invalid")
    core = {
        "schema_version": AUTHORIZATION_SCHEMA,
        "subject": SUBJECT,
        "capture_intake_date": capture_intake_date,
        "normalized_command": normalized,
        "command_sha256": command_sha,
    }
    expected_id = "NAUTH-" + sha256_value(core)[:24].upper()
    if value.get("authorization_id") != expected_id:
        raise AdapterError("nightly_authorization_id_invalid")
    return {**core, "authorization_id": expected_id}


def _validate_resolution(value: Any, checked: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != RESOLUTION_KEYS:
        raise AdapterError("nightly_resolution_shape_invalid")
    if value.get("batch_id") != checked["batch_id"]:
        raise AdapterError("nightly_resolution_batch_binding_invalid")
    if value.get("subject") != SUBJECT:
        raise AdapterError("nightly_resolution_subject_binding_invalid")
    if value.get("skill_name") != checked["skill"]["name"]:
        raise AdapterError("nightly_resolution_skill_binding_invalid")
    if value.get("skill_source_sha256") != checked["skill"]["source_sha256"]:
        raise AdapterError("nightly_resolution_skill_binding_invalid")
    conflict_id = _nonempty_text(
        value.get("conflict_id"), "nightly_resolution_conflict_invalid"
    )
    if not conflict_id.startswith("CONFLICT-"):
        raise AdapterError("nightly_resolution_conflict_invalid")
    capture_id = value.get("conflicted_capture_id")
    if capture_id not in checked["capture_ids"]:
        raise AdapterError("nightly_resolution_capture_invalid")
    option = value.get("user_option")
    if not isinstance(option, str) or not option.strip():
        raise AdapterError("nightly_resolution_option_invalid")
    return dict(value)


def validate_batch(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "batch_id",
        "subject",
        "capture_intake_date",
        "capture_ids",
        "capture_set_sha256",
        "analysis_packages",
        "skill",
        "authorization",
        "status",
        "formal_write_count",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise AdapterError("nightly_batch_shape_invalid")
    if value.get("schema_version") != BATCH_SCHEMA or value.get("subject") != SUBJECT:
        raise AdapterError("nightly_batch_subject_invalid")
    batch_id = _nonempty_text(value.get("batch_id"), "nightly_batch_id_invalid")
    if BATCH_ID.fullmatch(batch_id) is None:
        raise AdapterError("nightly_batch_id_invalid")
    capture_date = _date(value.get("capture_intake_date"))
    if value.get("status") != "frozen" or value.get("formal_write_count") != 0:
        raise AdapterError("nightly_batch_state_invalid")
    capture_ids = value.get("capture_ids")
    if (
        not isinstance(capture_ids, list)
        or not capture_ids
        or capture_ids != sorted(set(capture_ids))
        or any(not isinstance(item, str) or not item for item in capture_ids)
    ):
        raise AdapterError("nightly_batch_capture_ids_invalid")
    expected_set_sha = sha256_value(capture_ids)
    if _sha(value.get("capture_set_sha256"), "capture_set_sha256_invalid") != expected_set_sha:
        raise AdapterError("capture_set_sha256_invalid")
    packages = value.get("analysis_packages")
    if not isinstance(packages, list) or len(packages) != len(capture_ids):
        raise AdapterError("analysis_package_set_invalid")
    package_ids: list[str] = []
    for row in packages:
        if not isinstance(row, Mapping) or set(row) != {
            "capture_id",
            "package_ref",
            "package_sha256",
        }:
            raise AdapterError("analysis_package_set_invalid")
        package_id = row.get("capture_id")
        package_ids.append(str(package_id or ""))
        package_sha = _sha(
            row.get("package_sha256"), "analysis_package_sha256_invalid"
        )
        package_ref = row.get("package_ref")
        if package_ref != "study-intake-analysis-package://sha256/" + package_sha:
            raise AdapterError("analysis_package_ref_invalid")
    if package_ids != capture_ids:
        raise AdapterError("analysis_package_set_invalid")
    skill = value.get("skill")
    if not isinstance(skill, Mapping) or set(skill) != {
        "name",
        "source_sha256",
        "declared_version",
    }:
        raise AdapterError("skill_binding_invalid")
    expected_skill_sha = sha256_file(SKILL_PATH)
    if (
        skill.get("name") != SKILL_NAME
        or skill.get("source_sha256") != expected_skill_sha
        or (
            skill.get("declared_version") is not None
            and not isinstance(skill.get("declared_version"), str)
        )
    ):
        raise AdapterError("skill_binding_invalid")
    authorization = _validate_authorization(
        value.get("authorization"), capture_intake_date=capture_date
    )
    result = dict(value)
    result["batch_id"] = batch_id
    result["capture_intake_date"] = capture_date
    result["capture_ids"] = list(capture_ids)
    result["analysis_packages"] = [dict(row) for row in packages]
    result["skill"] = dict(skill)
    result["authorization"] = authorization
    return result


def _selected_capture_ids(
    checked: Mapping[str, Any],
    capture_ids: list[str] | None,
    resolution: Mapping[str, Any] | None,
) -> list[str]:
    all_ids = list(checked["capture_ids"])
    if resolution is not None:
        checked_resolution = _validate_resolution(resolution, checked)
        conflicted = checked_resolution["conflicted_capture_id"]
        if capture_ids is not None and capture_ids != [conflicted]:
            raise AdapterError("nightly_resolution_scope_invalid")
        return [conflicted]
    if capture_ids is None:
        return all_ids
    if (
        not isinstance(capture_ids, list)
        or not capture_ids
        or len(capture_ids) != len(set(capture_ids))
        or any(item not in all_ids for item in capture_ids)
    ):
        raise AdapterError("nightly_capture_selection_invalid")
    return list(capture_ids)


def validate_resolution(value: Mapping[str, Any], batch: Mapping[str, Any]) -> dict[str, Any]:
    """Public strict resolution validator used by the Python bridge."""

    checked = validate_batch(batch)
    return _validate_resolution(value, checked)


def prepare_invocation(
    batch: Mapping[str, Any],
    *,
    capture_ids: list[str] | None = None,
    resolution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    checked = validate_batch(batch)
    selected = _selected_capture_ids(checked, capture_ids, resolution)
    for relative in NATIVE_ENTRYPOINTS:
        if not (REPO_ROOT / relative).is_file():
            raise AdapterError("native_entrypoint_missing")
    core: dict[str, Any] = {
        "schema_version": SCHEMA,
        "adapter_name": ADAPTER_NAME,
        "subject": SUBJECT,
        "batch_id": checked["batch_id"],
        "capture_intake_date": checked["capture_intake_date"],
        "capture_ids": selected,
        "capture_set_sha256": sha256_value(selected),
        "outer_capture_set_sha256": checked["capture_set_sha256"],
        "analysis_packages": [
            package
            for package in checked["analysis_packages"]
            if package["capture_id"] in selected
        ],
        "skill": checked["skill"],
        "authorization": checked["authorization"],
        "native_entrypoints": list(NATIVE_ENTRYPOINTS),
        "selection_policy": (
            "conflicted_capture_only"
            if resolution is not None
            else "outer_frozen_set_only"
        ),
        "formal_write_count": 0,
    }
    if resolution is not None:
        core["resolution"] = dict(_validate_resolution(resolution, checked))
    return {**core, "invocation_sha256": sha256_value(core)}


def _hash_map(value: Any, code: str, *, allow_empty: bool) -> dict[str, str]:
    if not isinstance(value, Mapping) or (not allow_empty and not value):
        raise AdapterError(code)
    result: dict[str, str] = {}
    for key, digest in value.items():
        if not isinstance(key, str) or not key:
            raise AdapterError(code)
        result[key] = _sha(digest, code)
    return result


def _validate_action_results(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise AdapterError("apply_receipt_action_results_invalid")
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise AdapterError("apply_receipt_action_result_invalid")
        allowed = {
            "action_id",
            "action_type",
            "target",
            "result",
            "message",
            "assigned_id",
        }
        required = {"action_id", "action_type", "target", "result", "message"}
        if not set(row) <= allowed or not required <= set(row):
            raise AdapterError("apply_receipt_action_result_invalid")
        action_id = _nonempty_text(
            row.get("action_id"), "apply_receipt_action_result_invalid"
        )
        if action_id in seen:
            raise AdapterError("apply_receipt_action_result_duplicate")
        seen.add(action_id)
        if row.get("action_type") not in ACTION_TYPES:
            raise AdapterError("apply_receipt_action_result_invalid")
        if not isinstance(row.get("target"), str) or not row.get("target"):
            raise AdapterError("apply_receipt_action_result_invalid")
        if row.get("result") not in ACTION_RESULTS:
            raise AdapterError("apply_receipt_action_result_invalid")
        if not isinstance(row.get("message"), str):
            raise AdapterError("apply_receipt_action_result_invalid")
        result.append(dict(row))
    return result


def _validate_apply_receipt(
    value: Any,
    *,
    batch: Mapping[str, Any],
    terminal_status: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AdapterError("apply_receipt_missing")
    if set(value) != APPLY_RECEIPT_REQUIRED and set(value) != APPLY_RECEIPT_KEYS:
        raise AdapterError("apply_receipt_shape_invalid")
    receipt = dict(value)
    if receipt.get("schema_version") != "english_apply_receipt_v1":
        raise AdapterError("apply_receipt_schema_invalid")
    if receipt.get("batch_id") != batch["batch_id"]:
        raise AdapterError("apply_receipt_batch_binding_invalid")
    _nonempty_text(receipt.get("receipt_id"), "apply_receipt_id_invalid")
    _nonempty_text(receipt.get("action_set_id"), "apply_receipt_action_set_id_invalid")
    started_at = _timestamp(receipt.get("started_at"), "apply_receipt_started_at_invalid")
    completed_at = _timestamp(
        receipt.get("completed_at"), "apply_receipt_completed_at_invalid"
    )
    started = dt.datetime.fromisoformat(
        started_at[:-1] + "+00:00" if started_at.endswith("Z") else started_at
    )
    completed = dt.datetime.fromisoformat(
        completed_at[:-1] + "+00:00"
        if completed_at.endswith("Z")
        else completed_at
    )
    if started > completed:
        raise AdapterError("apply_receipt_timeline_invalid")
    _nonempty_text(receipt.get("lock_path"), "apply_receipt_lock_path_invalid")
    _nonempty_text(receipt.get("journal_path"), "apply_receipt_journal_path_invalid")
    status = receipt.get("status")
    if status not in APPLY_STATUSES:
        raise AdapterError("apply_receipt_status_invalid")
    mode = receipt.get("mode")
    if mode not in {"dry_run", "apply"}:
        raise AdapterError("apply_receipt_mode_invalid")
    if mode == "dry_run" and not status.startswith("DRY_RUN_"):
        raise AdapterError("apply_receipt_mode_invalid")
    if status.startswith("DRY_RUN_") and receipt.get("authorization") is not None:
        raise AdapterError("apply_receipt_authorization_invalid")
    authorization = receipt.get("authorization")
    if authorization is not None:
        if (
            not isinstance(authorization, Mapping)
            or set(authorization)
            != {"command", "batch_id", "study_date", "authorized_at", "scope"}
            or authorization.get("command") != "apply-nightly"
            or authorization.get("batch_id") != batch["batch_id"]
            or authorization.get("study_date") != batch["capture_intake_date"]
            or not isinstance(authorization.get("scope"), list)
            or not authorization["scope"]
        ):
            raise AdapterError("apply_receipt_authorization_invalid")
        _timestamp(
            authorization.get("authorized_at"),
            "apply_receipt_authorization_invalid",
        )
    if status in {
        "APPLIED",
        "PARTIAL",
        "NO_ACTION",
        "RECOVERED_COMMIT",
        "RECOVERED_ROLLBACK",
    } and not isinstance(authorization, Mapping):
        raise AdapterError("apply_receipt_authorization_invalid")
    _sha(receipt.get("manifest_sha256"), "apply_receipt_manifest_hash_invalid")
    _sha(receipt.get("actions_sha256"), "apply_receipt_actions_hash_invalid")
    pre = _hash_map(
        receipt.get("formal_prehashes"),
        "apply_receipt_prehashes_invalid",
        allow_empty=False,
    )
    proposed = _hash_map(
        receipt.get("proposed_posthashes"),
        "apply_receipt_proposed_hashes_invalid",
        allow_empty=True,
    )
    post = _hash_map(
        receipt.get("formal_posthashes"),
        "apply_receipt_posthashes_invalid",
        allow_empty=False,
    )
    changed = receipt.get("formal_files_changed")
    if not isinstance(changed, bool) or changed != (pre != post):
        raise AdapterError("apply_receipt_formal_change_invalid")
    write_count = receipt.get("formal_write_count")
    if (
        isinstance(write_count, bool)
        or not isinstance(write_count, int)
        or write_count < 0
    ):
        raise AdapterError("apply_receipt_formal_write_count_invalid")
    if status.startswith("DRY_RUN_") or status == "CAS_CONFLICT":
        if write_count != 0 or changed or post != pre:
            raise AdapterError("apply_receipt_status_semantics_invalid")
    if status == "CAS_CONFLICT" and proposed:
        raise AdapterError("apply_receipt_status_semantics_invalid")
    if (
        status in {"APPLIED", "PARTIAL", "NO_ACTION", "RECOVERED_COMMIT", "RECOVERED_ROLLBACK"}
        and proposed != post
    ):
        raise AdapterError("apply_receipt_posthash_binding_invalid")
    validation = receipt.get("validation")
    if (
        not isinstance(validation, Mapping)
        or validation.get("status") not in {"PASS", "PARTIAL", "FAIL"}
    ):
        raise AdapterError("apply_receipt_validation_invalid")
    if status in {"APPLIED", "NO_ACTION", "RECOVERED_COMMIT"} and validation.get("status") != "PASS":
        raise AdapterError("apply_receipt_validation_invalid")
    if status in {"PARTIAL", "DRY_RUN_PARTIAL"} and validation.get("status") not in {"PASS", "PARTIAL"}:
        raise AdapterError("apply_receipt_validation_invalid")
    if status in {"CAS_CONFLICT", "FAILED"} and validation.get("status") != "FAIL":
        raise AdapterError("apply_receipt_validation_invalid")
    receipt["formal_prehashes"] = pre
    receipt["proposed_posthashes"] = proposed
    receipt["formal_posthashes"] = post
    receipt["action_results"] = _validate_action_results(receipt.get("action_results"))
    safe_results = sum(
        row["result"] in {"would_apply", "applied"}
        for row in receipt["action_results"]
    )
    unresolved_results = sum(
        row["result"] == "needs_user" for row in receipt["action_results"]
    )
    safe_count = validation.get("safe_action_count")
    unresolved_count = validation.get("unresolved_count")
    if (
        isinstance(safe_count, bool)
        or not isinstance(safe_count, int)
        or isinstance(unresolved_count, bool)
        or not isinstance(unresolved_count, int)
        or safe_count != safe_results
        or unresolved_count != unresolved_results
        or (
            mode == "apply"
            and status in {"APPLIED", "PARTIAL", "NO_ACTION"}
            and write_count != safe_count
        )
    ):
        raise AdapterError("apply_receipt_action_count_mismatch")
    return receipt


def _validate_recovery_receipt(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != RECOVERY_KEYS:
        raise AdapterError("recovery_receipt_shape_invalid")
    receipt = dict(value)
    if receipt.get("schema_version") != RECOVERY_SCHEMA:
        raise AdapterError("recovery_receipt_schema_invalid")
    _nonempty_text(receipt.get("receipt_id"), "recovery_receipt_id_invalid")
    _nonempty_text(receipt.get("receipt_path"), "recovery_receipt_path_invalid")
    if receipt.get("status") not in {"PASS", "PARTIAL"}:
        raise AdapterError("recovery_receipt_status_invalid")
    if not isinstance(receipt.get("recovered"), list):
        raise AdapterError("recovery_receipt_recovered_invalid")
    if receipt.get("formal_write_count") != 0:
        raise AdapterError("recovery_receipt_formal_write_count_invalid")
    for row in receipt["recovered"]:
        if (
            not isinstance(row, Mapping)
            or not set(row) <= {"transaction", "status", "reason"}
            or not {"transaction", "status"} <= set(row)
        ):
            raise AdapterError("recovery_receipt_recovered_invalid")
        if not isinstance(row.get("transaction"), str) or not row.get("transaction"):
            raise AdapterError("recovery_receipt_recovered_invalid")
        if row.get("status") not in {
            "skipped",
            "failed",
            "RECOVERED_COMMIT_WITH_RECEIPT",
            "RECOVERED_ROLLBACK",
        }:
            raise AdapterError("recovery_receipt_recovered_invalid")
        if "reason" in row and row["reason"] is not None and not isinstance(row["reason"], str):
            raise AdapterError("recovery_receipt_recovered_invalid")
    return receipt


def _validate_execution_evidence(
    value: Any,
    *,
    apply_receipt: Mapping[str, Any],
    terminal_status: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != EXECUTION_EVIDENCE_KEYS:
        raise AdapterError("execution_evidence_shape_invalid")
    evidence = dict(value)
    _sha(evidence.get("pre_state_sha256"), "execution_pre_state_hash_invalid")
    _sha(evidence.get("post_state_sha256"), "execution_post_state_hash_invalid")
    if not isinstance(evidence.get("operations"), list):
        raise AdapterError("execution_operations_invalid")
    _nonempty_text(evidence.get("adapter_run_id"), "execution_adapter_run_id_invalid")
    pid = evidence.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
        raise AdapterError("execution_pid_invalid")
    _nonempty_text(evidence.get("transaction_id"), "execution_transaction_id_invalid")
    ended_at = _timestamp(evidence.get("ended_at"), "execution_ended_at_invalid")
    stopped_at = _timestamp(evidence.get("stopped_at"), "execution_stopped_at_invalid")
    ended_text = ended_at[:-1] + "+00:00" if ended_at.endswith("Z") else ended_at
    stopped_text = stopped_at[:-1] + "+00:00" if stopped_at.endswith("Z") else stopped_at
    if dt.datetime.fromisoformat(ended_text) > dt.datetime.fromisoformat(stopped_text):
        raise AdapterError("execution_timeline_invalid")
    exit_code = evidence.get("exit_code")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        raise AdapterError("execution_exit_code_invalid")
    if terminal_status in {
        "APPLIED",
        "PARTIAL",
        "NO_ACTION",
        "NEEDS_USER",
        "DRY_RUN_VALID",
        "DRY_RUN_PARTIAL",
        "DRY_RUN_NO_ACTION",
    } and exit_code != 0:
        raise AdapterError("execution_exit_code_invalid")
    if terminal_status in {"CAS_CONFLICT", "FAILED"} and exit_code == 0:
        raise AdapterError("execution_failure_exit_code_invalid")
    expected_pre = aggregate_state_sha256(apply_receipt["formal_prehashes"])
    expected_post = aggregate_state_sha256(apply_receipt["formal_posthashes"])
    if (
        evidence["pre_state_sha256"] != expected_pre
        or evidence["post_state_sha256"] != expected_post
        or evidence["operations"] != apply_receipt["action_results"]
    ):
        raise AdapterError("execution_state_hash_binding_invalid")
    return evidence


def _conflict_capture(conflict: Mapping[str, Any]) -> str | None:
    value = conflict.get("capture_id")
    if value is None:
        value = conflict.get("conflicted_capture_id")
    return value if isinstance(value, str) else None


def _conflict_id(checked: Mapping[str, Any], conflict: Mapping[str, Any]) -> str:
    capture_id = _conflict_capture(conflict)
    kind = conflict.get("kind")
    if kind not in HARD_CONFLICT_KINDS or capture_id not in checked["capture_ids"]:
        raise AdapterError("hard_conflict_invalid")
    stable = {
        "schema_version": NATIVE_TERMINAL_SCHEMA,
        "subject": SUBJECT,
        "batch_id": checked["batch_id"],
        "capture_id": capture_id,
        "kind": kind,
        "skill_name": checked["skill"]["name"],
        "skill_source_sha256": checked["skill"]["source_sha256"],
    }
    result = "CONFLICT-" + sha256_value(stable)[:24].upper()
    supplied = conflict.get("conflict_id")
    if supplied is not None and supplied != result:
        raise AdapterError("hard_conflict_binding_invalid")
    return result


def validate_native_terminal(
    batch: Mapping[str, Any],
    native_receipt: Mapping[str, Any],
    *,
    capture_ids: list[str] | None = None,
    resolution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Strictly validate the native English terminal envelope."""

    checked = validate_batch(batch)
    selected = _selected_capture_ids(checked, capture_ids, resolution)
    if not isinstance(native_receipt, Mapping):
        raise AdapterError("native_terminal_shape_invalid")
    if set(native_receipt) - NATIVE_TERMINAL_REQUIRED - NATIVE_TERMINAL_OPTIONAL:
        raise AdapterError("native_terminal_shape_invalid")
    if not NATIVE_TERMINAL_REQUIRED <= set(native_receipt):
        raise AdapterError("native_terminal_shape_invalid")
    terminal = dict(native_receipt)
    if terminal.get("schema_version") != NATIVE_TERMINAL_SCHEMA:
        raise AdapterError("native_terminal_schema_invalid")
    if (
        terminal.get("subject") != SUBJECT
        or terminal.get("batch_id") != checked["batch_id"]
    ):
        raise AdapterError("native_terminal_batch_binding_invalid")
    status = terminal.get("status")
    if status not in NATIVE_TERMINAL_STATUSES:
        raise AdapterError("native_terminal_status_invalid")
    status = {
        "applied": "APPLIED",
        "partial": "PARTIAL",
        "no_action": "NO_ACTION",
        "needs_user": "NEEDS_USER",
        "cas_conflict": "CAS_CONFLICT",
        "failed": "FAILED",
    }.get(status, status)
    terminal["status"] = status
    if not isinstance(terminal.get("capture_results"), list):
        raise AdapterError("native_terminal_capture_results_invalid")
    result_ids: list[str] = []
    for row in terminal["capture_results"]:
        if not isinstance(row, Mapping) or not isinstance(row.get("capture_id"), str):
            raise AdapterError("native_terminal_capture_result_invalid")
        result_ids.append(row["capture_id"])
    if len(result_ids) != len(set(result_ids)) or set(result_ids) != set(selected):
        raise AdapterError("native_terminal_capture_results_incomplete")
    changed_files = terminal.get("changed_files")
    if not isinstance(changed_files, list) or any(
        not isinstance(path, str) or not path for path in changed_files
    ):
        raise AdapterError("native_terminal_changed_files_invalid")
    count = terminal.get("formal_write_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise AdapterError("native_terminal_formal_write_count_invalid")
    conflict = terminal.get("conflict")
    conflict_id = None
    if conflict is not None:
        if not isinstance(conflict, Mapping):
            raise AdapterError("hard_conflict_invalid")
        conflict_id = _conflict_id(checked, conflict)
        conflict_capture = _conflict_capture(conflict)
        if conflict_capture not in selected:
            raise AdapterError("hard_conflict_scope_invalid")
    if status == "NEEDS_USER" and conflict is None:
        raise AdapterError("hard_conflict_missing")
    if status in {"PARTIAL", "NEEDS_USER"} and conflict is None:
        raise AdapterError("hard_conflict_missing")
    if status not in {"PARTIAL", "NEEDS_USER"} and conflict is not None:
        raise AdapterError("hard_conflict_status_invalid")
    apply_receipt = _validate_apply_receipt(
        terminal.get("apply_receipt"), batch=checked, terminal_status=status
    )
    if terminal.get("apply_receipt_sha256") != sha256_value(apply_receipt):
        raise AdapterError("apply_receipt_hash_invalid")
    recovery = terminal.get("recovery_receipt")
    recovery_hash = terminal.get("recovery_receipt_sha256")
    if recovery is None:
        if recovery_hash is not None:
            raise AdapterError("recovery_receipt_hash_invalid")
    else:
        checked_recovery = _validate_recovery_receipt(recovery)
        if recovery_hash != sha256_value(checked_recovery):
            raise AdapterError("recovery_receipt_hash_invalid")
        if status not in {"CAS_CONFLICT", "FAILED"}:
            raise AdapterError("recovery_receipt_status_invalid")
        terminal["recovery_receipt"] = checked_recovery
    if count != apply_receipt["formal_write_count"]:
        raise AdapterError("native_terminal_formal_write_count_binding_invalid")
    if status in {"CAS_CONFLICT", "FAILED"} and count != 0:
        raise AdapterError("native_terminal_failed_write_count_nonzero")
    if bool(changed_files) != bool(apply_receipt["formal_files_changed"]):
        raise AdapterError("native_terminal_changed_files_binding_invalid")
    _validate_execution_evidence(
        terminal.get("execution_evidence"),
        apply_receipt=apply_receipt,
        terminal_status=status,
    )
    if status == "APPLIED" and apply_receipt["status"] != "APPLIED":
        raise AdapterError("native_terminal_apply_status_invalid")
    if status == "PARTIAL" and apply_receipt["status"] not in {"PARTIAL", "DRY_RUN_PARTIAL"}:
        raise AdapterError("native_terminal_apply_status_invalid")
    if status == "NEEDS_USER" and apply_receipt["status"] not in {"PARTIAL", "DRY_RUN_PARTIAL"}:
        raise AdapterError("native_terminal_apply_status_invalid")
    if status == "NO_ACTION" and apply_receipt["status"] not in {"NO_ACTION", "DRY_RUN_NO_ACTION"}:
        raise AdapterError("native_terminal_apply_status_invalid")
    if status == "CAS_CONFLICT" and apply_receipt["status"] != "CAS_CONFLICT":
        raise AdapterError("native_terminal_apply_status_invalid")
    if status == "FAILED" and apply_receipt["status"] not in {"FAILED", "CAS_CONFLICT"}:
        raise AdapterError("native_terminal_apply_status_invalid")
    terminal["capture_results"] = [dict(row) for row in terminal["capture_results"]]
    terminal["changed_files"] = list(changed_files)
    terminal["formal_write_count"] = count
    terminal["apply_receipt"] = apply_receipt
    terminal["execution_evidence"] = dict(terminal["execution_evidence"])
    return terminal


def _wrap_legacy_native_receipt(
    checked: Mapping[str, Any], native_receipt: Mapping[str, Any]
) -> dict[str, Any]:
    """Keep the original wrap CLI usable for pre-terminal receipt fixtures."""

    required = {
        "schema_version",
        "subject",
        "batch_id",
        "status",
        "capture_results",
        "changed_files",
        "formal_write_count",
        "conflict",
    }
    if set(native_receipt) != required:
        raise AdapterError("native_receipt_shape_invalid")
    status = str(native_receipt.get("status") or "")
    if (
        native_receipt.get("subject") != SUBJECT
        or native_receipt.get("batch_id") != checked["batch_id"]
        or status not in LEGACY_NATIVE_STATUSES
        or isinstance(native_receipt.get("formal_write_count"), bool)
        or not isinstance(native_receipt.get("formal_write_count"), int)
        or int(native_receipt["formal_write_count"]) < 0
        or not isinstance(native_receipt.get("changed_files"), list)
        or not isinstance(native_receipt.get("capture_results"), list)
    ):
        raise AdapterError("native_receipt_invalid")
    conflict = native_receipt.get("conflict")
    conflict_id = None
    if status == "awaiting_user":
        if not isinstance(conflict, Mapping):
            raise AdapterError("hard_conflict_invalid")
        conflict_id = _conflict_id(checked, conflict)
    elif conflict is not None:
        raise AdapterError("hard_conflict_invalid")
    status_map = {
        "committed": "complete",
        "noop": "noop",
        "partial": "partial",
        "awaiting_user": "awaiting_user",
        "failed": "failed",
    }
    receipt = dict(native_receipt)
    return {
        "schema_version": RESULT_SCHEMA,
        "adapter_name": ADAPTER_NAME,
        "subject": SUBJECT,
        "batch_id": checked["batch_id"],
        "status": status_map[status],
        "native_receipt": receipt,
        "native_receipt_sha256": sha256_value(receipt),
        "conflict_id": conflict_id,
        "formal_write_count": int(receipt["formal_write_count"]),
    }


def wrap_native_receipt(
    batch: Mapping[str, Any],
    native_receipt: Mapping[str, Any],
    *,
    capture_ids: list[str] | None = None,
    resolution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    checked = validate_batch(batch)
    if (
        isinstance(native_receipt, Mapping)
        and native_receipt.get("schema_version") == NATIVE_TERMINAL_SCHEMA
    ):
        terminal = validate_native_terminal(
            checked,
            native_receipt,
            capture_ids=capture_ids,
            resolution=resolution,
        )
        status_map = {
            "APPLIED": "complete",
            "PARTIAL": "partial",
            "NO_ACTION": "noop",
            "NEEDS_USER": "awaiting_user",
            "CAS_CONFLICT": "failed",
            "FAILED": "failed",
        }
        outer_status = (
            "awaiting_user"
            if terminal.get("conflict") is not None
            else status_map[terminal["status"]]
        )
        return {
            "schema_version": RESULT_SCHEMA,
            "adapter_name": ADAPTER_NAME,
            "subject": SUBJECT,
            "batch_id": checked["batch_id"],
            "status": outer_status,
            "native_receipt": terminal,
            "native_receipt_sha256": sha256_value(terminal),
            "conflict_id": (
                _conflict_id(checked, terminal["conflict"])
                if terminal.get("conflict") is not None
                else None
            ),
            "formal_write_count": int(terminal["formal_write_count"]),
        }
    raise AdapterError("native_terminal_schema_required")


class EnglishNightlySolAdapter:
    """Callable Python bridge for one exact English nightly terminal run."""

    def execute(
        self,
        batch: Mapping[str, Any],
        *,
        native_executor: Any,
        capture_ids: list[str] | None = None,
        resolution: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        checked = validate_batch(batch)
        selected = _selected_capture_ids(checked, capture_ids, resolution)
        invocation = prepare_invocation(
            checked, capture_ids=selected, resolution=resolution
        )
        executor = native_executor
        if not callable(executor):
            executor = getattr(native_executor, "execute", None)
        if not callable(executor):
            raise AdapterError("native_executor_not_callable")
        immutable_invocation = _freeze(invocation)
        native_receipt = executor(immutable_invocation)
        if not isinstance(native_receipt, Mapping):
            raise AdapterError("native_executor_result_invalid")
        return wrap_native_receipt(
            checked,
            native_receipt,
            capture_ids=selected,
            resolution=resolution,
        )


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AdapterError("json_object_required")
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(canonical_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        try:
            Path(name).unlink()
        except FileNotFoundError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "wrap"):
        command = sub.add_parser(name)
        command.add_argument("--batch", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        if name == "wrap":
            command.add_argument("--native-receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    batch = _load(args.batch)
    result = (
        prepare_invocation(batch)
        if args.command == "prepare"
        else wrap_native_receipt(batch, _load(args.native_receipt))
    )
    _write(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
