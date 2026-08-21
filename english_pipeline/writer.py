from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from .constants import MASTERED_HEADER, MASTER_HEADER, MASTER_TYPES, SP_FIELDS, WRITING_VALUES
from .errors import AuthorizationError, ValidationError
from .events import exclusive_lock
from .formal import read_csv, resolve_formal_paths, serialize_csv, validate_sentence_patterns_text
from .review_status import (
    append_review_status_record,
    load_review_status_ledger,
    serialize_review_status_ledger,
)
from .util import (
    atomic_write_bytes,
    atomic_write_json,
    bytes_sha256,
    file_sha256,
    load_json,
    normalize_item,
    object_sha256,
    utc_now,
)


SAFE_ACTIONS = {
    "master_bank_insert", "master_bank_update", "mastered_insert",
    "sentence_pattern_append", "sentence_pattern_merge",
    "review_exclusion_append", "review_reactivation_append",
}
NOOP_ACTIONS = {"skip_duplicate", "needs_user"}
UPDATE_FIELDS = {"usage", "tags", "review_note", "appear_count", "last_seen"}


class SimulatedWriterCrash(BaseException):
    """Test-only process crash that intentionally bypasses in-process rollback."""


OPEN_TRANSACTION_STATUSES = {"prepared", "committing", "committed", "committed_pending_receipt"}


def _optional_file_bytes(path: Path) -> bytes:
    return path.read_bytes() if path.exists() else b""


def _optional_file_sha256(path: Path) -> str:
    return file_sha256(path) if path.exists() else bytes_sha256(b"")


def _open_transaction_paths(state_dir: Path) -> list[Path]:
    pending: list[Path] = []
    for path in sorted((state_dir / "nightly").glob("*/*/transactions/*/transaction.json")):
        try:
            status = load_json(path).get("status")
        except Exception:
            pending.append(path)
            continue
        if status in OPEN_TRANSACTION_STATUSES:
            pending.append(path)
    return pending


def _require_fields(value: dict[str, Any], required: set[str], context: str) -> None:
    missing = sorted(required - value.keys())
    if missing:
        raise ValidationError(f"{context} missing fields: {missing}")


def validate_sol_actions(actions_doc: dict[str, Any], manifest: dict[str, Any], manifest_sha: str) -> None:
    if manifest.get("status") == "needs_preprocess":
        raise ValidationError("nightly manifest has uncovered captures and needs preprocessing")
    _require_fields(
        actions_doc,
        {"schema_version", "action_set_id", "batch_id", "batch_manifest_sha256", "created_at", "producer", "formal_write_count", "formal_writeback", "actions", "unresolved"},
        "Sol actions",
    )
    allowed_top = {"schema_version", "action_set_id", "batch_id", "batch_manifest_sha256", "created_at", "producer", "formal_write_count", "formal_writeback", "actions", "unresolved"}
    if set(actions_doc) != allowed_top:
        raise ValidationError(f"Sol actions top-level fields do not match schema: {sorted(set(actions_doc) - allowed_top)}")
    if actions_doc["schema_version"] != "english_sol_actions_v1":
        raise ValidationError("Sol actions schema_version mismatch")
    if actions_doc["batch_id"] != manifest["batch_id"]:
        raise ValidationError("Sol actions batch_id does not match manifest")
    if actions_doc["batch_manifest_sha256"] != manifest_sha:
        raise ValidationError("Sol actions manifest hash mismatch")
    if actions_doc["formal_write_count"] != 0 or actions_doc["formal_writeback"] != "none":
        raise ValidationError("Sol model proposal must declare zero formal writes")
    candidate_items: list[dict[str, Any]] = []
    for record in manifest.get("candidate_documents", []):
        path = Path(record["path"])
        if not path.is_file() or file_sha256(path) != record["sha256"]:
            raise ValidationError(f"frozen Luna candidate drift: {path}")
        candidate_items.extend(load_json(path).get("items", []))
    producer = actions_doc["producer"]
    if not isinstance(producer, dict) or producer.get("role") != "sol_nightly_reviewer":
        raise ValidationError("Sol producer role must be sol_nightly_reviewer")
    if not isinstance(actions_doc["actions"], list) or not isinstance(actions_doc["unresolved"], list):
        raise ValidationError("Sol actions and unresolved must be arrays")
    frozen_ids = set(manifest.get("capture_event_ids", []))
    action_ids: set[str] = set()
    for index, action in enumerate(actions_doc["actions"], start=1):
        context = f"action {index}"
        if not isinstance(action, dict):
            raise ValidationError(f"{context} must be an object")
        _require_fields(action, {"action_id", "action_type", "reason", "source_capture_event_ids"}, context)
        if action["action_id"] in action_ids:
            raise ValidationError(f"duplicate action_id: {action['action_id']}")
        action_ids.add(action["action_id"])
        if action["action_type"] not in SAFE_ACTIONS | {"skip_duplicate"}:
            raise ValidationError(f"unsupported action_type: {action['action_type']}")
        refs = action["source_capture_event_ids"]
        if not isinstance(refs, list) or not refs:
            raise ValidationError(f"{context} requires source_capture_event_ids")
        if not set(refs).issubset(frozen_ids):
            raise ValidationError(f"{context} references capture outside frozen manifest")
        kind = action["action_type"]
        expected_fields = {
            "master_bank_insert": {"action_id", "action_type", "reason", "source_capture_event_ids", "row"},
            "master_bank_update": {"action_id", "action_type", "reason", "source_capture_event_ids", "record_id", "updates"},
            "mastered_insert": {"action_id", "action_type", "reason", "source_capture_event_ids", "mastery_evidence_kind", "row"},
            "sentence_pattern_append": {"action_id", "action_type", "reason", "source_capture_event_ids", "fields"},
            "sentence_pattern_merge": {"action_id", "action_type", "reason", "source_capture_event_ids", "existing_sp_id", "additions"},
            "skip_duplicate": {"action_id", "action_type", "reason", "source_capture_event_ids", "target", "item"},
            "review_exclusion_append": {
                "action_id", "action_type", "reason", "source_capture_event_ids",
                "item", "bank_id", "sentence_evidence",
            },
            "review_reactivation_append": {
                "action_id", "action_type", "reason", "source_capture_event_ids",
                "item", "bank_id", "sentence_evidence",
            },
        }[kind]
        if set(action) != expected_fields:
            raise ValidationError(f"{context} fields do not match typed action schema")
        if kind == "skip_duplicate":
            if not str(action.get("item", "")).strip() or not str(action.get("target", "")).strip():
                raise ValidationError(f"{context} skip_duplicate needs target and item")
            continue
        if kind in {"review_exclusion_append", "review_reactivation_append"}:
            proposal_field = (
                "review_exclusion_proposals"
                if kind == "review_exclusion_append"
                else "reactivation_proposals"
            )
            proposals = (
                manifest.get("review_status_proposals", {}).get(proposal_field, [])
            )
            exact = [
                proposal
                for proposal in proposals
                if proposal.get("item") == action.get("item")
                and proposal.get("bank_id") == action.get("bank_id")
                and proposal.get("source_capture_event_ids") == refs
                and proposal.get("sentence_evidence") == action.get("sentence_evidence")
            ]
            if len(exact) != 1:
                raise ValidationError(
                    f"{context} does not exactly match the frozen daily proposal"
                )
            continue
        live_refs = [
            item
            for item in candidate_items
            if item.get("source_event_id") in refs and item.get("evidence_origin") == "live_user"
        ]
        if not live_refs:
            raise ValidationError(f"{context} lacks a frozen live_user candidate")
        if kind == "master_bank_insert":
            row = action.get("row")
            if not isinstance(row, dict) or set(row) != set(MASTER_HEADER):
                raise ValidationError(f"{context} master row must contain exactly 13 formal columns")
            if row["id"] not in {"", None}:
                raise ValidationError(f"{context} Sol must not allocate master_bank id")
            if row["type"] not in MASTER_TYPES or row["writing_value"] not in WRITING_VALUES:
                raise ValidationError(f"{context} master row enum is invalid")
            if not str(row["item"]).strip() or not str(row["source_sentence"]).strip():
                raise ValidationError(f"{context} master row lacks item/source_sentence")
            if not any(normalize_item(str(item.get("item", ""))) == normalize_item(row["item"]) for item in live_refs):
                raise ValidationError(f"{context} item lacks matching live_user candidate")
            if not isinstance(row["appear_count"], int) or row["appear_count"] < 1:
                raise ValidationError(f"{context} appear_count must be a positive integer")
        elif kind == "master_bank_update":
            if not str(action.get("record_id", "")).strip():
                raise ValidationError(f"{context} record_id is required")
            updates = action.get("updates")
            if not isinstance(updates, dict) or not updates or not set(updates).issubset(UPDATE_FIELDS):
                raise ValidationError(f"{context} updates contain unsupported fields")
        elif kind == "mastered_insert":
            row = action.get("row")
            if action.get("mastery_evidence_kind") != "independent_correct_use":
                raise ValidationError(f"{context} mastery gate requires independent_correct_use")
            if not isinstance(row, dict) or set(row) != set(MASTERED_HEADER):
                raise ValidationError(f"{context} mastered row must contain exactly 7 columns")
            for field in ("item", "evidence_sentence", "evidence_context", "proof_note"):
                if not str(row.get(field, "")).strip():
                    raise ValidationError(f"{context} mastered row missing {field}")
            normalized = normalize_item(row["item"])
            qualifying = [
                item
                for item in candidate_items
                if normalize_item(str(item.get("item", ""))) == normalized
                and item.get("candidate_status") == "mastery_candidate"
                and "independent_correct_use" in item.get("evidence_states", [])
                and item.get("evidence_origin") == "live_user"
                and item.get("source_event_id") in refs
            ]
            if not qualifying:
                raise ValidationError(f"{context} lacks a frozen independent mastery candidate")
        elif kind == "sentence_pattern_append":
            fields = action.get("fields")
            if not isinstance(fields, dict) or set(fields) != set(SP_FIELDS):
                raise ValidationError(f"{context} SP proposal must contain exactly 15 fields")
            if re.search(r"\bSP-\d{3}\b", str(fields["title"])):
                raise ValidationError(f"{context} Sol must not allocate SP id")
            if not str(fields["title"]).strip():
                raise ValidationError(f"{context} SP title is required")
            if not isinstance(fields["结构拆解"], list) or not isinstance(fields["来源与示例"], list):
                raise ValidationError(f"{context} SP list fields are invalid")
        elif kind == "sentence_pattern_merge":
            existing_sp_id = str(action.get("existing_sp_id", ""))
            additions = action.get("additions")
            if not re.fullmatch(r"SP-\d{3}", existing_sp_id):
                raise ValidationError(f"{context} existing_sp_id is invalid")
            if not isinstance(additions, dict) or not additions:
                raise ValidationError(f"{context} merge additions are required")
            allowed_additions = {"来源与示例", "常用变体", "相关词汇/搭配", "use_count_increment", "last_used"}
            if not set(additions).issubset(allowed_additions):
                raise ValidationError(f"{context} merge contains unsupported additions")
            for field in ("来源与示例", "常用变体", "相关词汇/搭配"):
                if field in additions and not isinstance(additions[field], list):
                    raise ValidationError(f"{context} {field} must be an array")
            if "use_count_increment" in additions and (
                not isinstance(additions["use_count_increment"], int) or additions["use_count_increment"] < 0
            ):
                raise ValidationError(f"{context} use_count_increment must be a non-negative integer")
    for index, decision in enumerate(actions_doc["unresolved"], start=1):
        context = f"unresolved {index}"
        if not isinstance(decision, dict):
            raise ValidationError(f"{context} must be an object")
        _require_fields(decision, {"action_id", "status", "reason", "source_capture_event_ids", "target", "item"}, context)
        if set(decision) != {"action_id", "status", "reason", "source_capture_event_ids", "target", "item"}:
            raise ValidationError(f"{context} fields do not match unresolved schema")
        if decision["action_id"] in action_ids:
            raise ValidationError(f"duplicate action_id: {decision['action_id']}")
        action_ids.add(decision["action_id"])
        if decision["status"] != "needs_user":
            raise ValidationError(f"unsupported unresolved status: {decision['status']}")
        refs = decision["source_capture_event_ids"]
        if not isinstance(refs, list) or not refs or not set(refs).issubset(frozen_ids):
            raise ValidationError(f"{context} references capture outside frozen manifest")
        if not str(decision["item"]).strip() or not str(decision["target"]).strip():
            raise ValidationError(f"{context} needs target and item")


def _next_master_id(rows: list[dict[str, Any]], row_date: str) -> str:
    prefix = row_date.replace("-", "")
    used = {
        int(match.group(1))
        for row in rows
        if (match := re.fullmatch(re.escape(prefix) + r"-(\d{3})", str(row.get("id", ""))))
    }
    sequence = max(used, default=0) + 1
    while sequence in used:
        sequence += 1
    return f"{prefix}-{sequence:03d}"


def _next_sp_id(text: str) -> str:
    used = [int(value) for value in re.findall(r"^## SP-(\d{3})｜", text, flags=re.MULTILINE)]
    return f"SP-{max(used, default=0) + 1:03d}"


def _render_sp_card(card_id: str, fields: dict[str, Any]) -> str:
    lines = [
        f"## {card_id}｜{fields['title']}",
        "",
        f"**骨架**：`{fields['骨架']}`",
        f"**难度等级**：{fields['难度等级']}",
        f"**基本句型**：{fields['基本句型']}",
        f"**从句类型**：{fields['从句类型']}",
        f"**场景标签**：{fields['场景标签']}",
        f"**可复用程度**：{fields['可复用程度']}",
        f"**中文解释**：{fields['中文解释']}",
        "**结构拆解**：",
        *[f"- {line}" for line in fields["结构拆解"]],
        f"**生成模板**：`{fields['生成模板']}`",
        f"**相关词汇/搭配**：{fields['相关词汇/搭配']}",
        f"**常用变体**：{fields['常用变体']}",
        "**来源与示例**：",
        *[f"{index}. {line}" for index, line in enumerate(fields["来源与示例"], start=1)],
        f"**use_count**：{fields['use_count']}",
        f"**last_used**：{fields['last_used']}",
        "",
    ]
    return "\n".join(lines)


def _merge_sp_card(text: str, existing_sp_id: str, additions: dict[str, Any]) -> tuple[str, bool]:
    headings = list(re.finditer(r"^## (SP-\d{3})｜.+$", text, flags=re.MULTILINE))
    matches = [(index, match) for index, match in enumerate(headings) if match.group(1) == existing_sp_id]
    if len(matches) != 1:
        raise ValidationError(f"sentence_pattern_merge target not unique: {existing_sp_id}")
    index, heading = matches[0]
    start = heading.start()
    end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
    block = text[start:end]
    original = block

    def append_inline(field: str, separator: str) -> None:
        nonlocal block
        additions_list = [str(value).strip() for value in additions.get(field, []) if str(value).strip()]
        if not additions_list:
            return
        pattern = re.compile(rf"^(\*\*{re.escape(field)}\*\*：)(.*)$", flags=re.MULTILINE)
        match = pattern.search(block)
        if not match:
            raise ValidationError(f"{existing_sp_id} missing merge field {field}")
        existing = [value.strip() for value in re.split(r"[、；|]", match.group(2)) if value.strip()]
        for value in additions_list:
            if value not in existing:
                existing.append(value)
        block = block[: match.start()] + match.group(1) + separator.join(existing) + block[match.end() :]

    append_inline("相关词汇/搭配", "、")
    append_inline("常用变体", "；")

    sources_to_add = [str(value).strip() for value in additions.get("来源与示例", []) if str(value).strip()]
    if sources_to_add:
        source_match = re.search(
            r"^\*\*来源与示例\*\*：\n(?P<body>.*?)(?=^\*\*use_count\*\*：)",
            block,
            flags=re.MULTILINE | re.DOTALL,
        )
        if not source_match:
            raise ValidationError(f"{existing_sp_id} missing 来源与示例 block")
        existing_sources = [match.group(1).strip() for match in re.finditer(r"^\d+\.\s*(.+)$", source_match.group("body"), re.MULTILINE)]
        for value in sources_to_add:
            if value not in existing_sources:
                existing_sources.append(value)
        rendered = "".join(f"{number}. {value}\n" for number, value in enumerate(existing_sources, start=1))
        block = block[: source_match.start("body")] + rendered + block[source_match.end("body") :]

    increment = int(additions.get("use_count_increment", 0))
    if increment:
        count_match = re.search(r"^(\*\*use_count\*\*：)(\d+)$", block, flags=re.MULTILINE)
        if not count_match:
            raise ValidationError(f"{existing_sp_id} missing use_count")
        new_count = int(count_match.group(2)) + increment
        block = block[: count_match.start()] + count_match.group(1) + str(new_count) + block[count_match.end() :]
    if additions.get("last_used"):
        last_match = re.search(r"^(\*\*last_used\*\*：)(.+)$", block, flags=re.MULTILINE)
        if not last_match:
            raise ValidationError(f"{existing_sp_id} missing last_used")
        desired = str(additions["last_used"])
        block = block[: last_match.start()] + last_match.group(1) + desired + block[last_match.end() :]
    return text[:start] + block + text[end:], block != original


def _simulate(
    actions: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
    *,
    master_rows: list[dict[str, Any]],
    mastered_rows: list[dict[str, Any]],
    sp_text: str,
    review_status_records: list[dict[str, Any]],
    study_date: str,
    dry_run: bool,
) -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], str, list[dict[str, Any]],
    list[dict[str, Any]], int, int,
]:
    master = [dict(row) for row in master_rows]
    mastered = [dict(row) for row in mastered_rows]
    patterns = sp_text
    review_records = [dict(row) for row in review_status_records]
    results: list[dict[str, Any]] = []
    safe_count = 0
    unresolved_count = 0
    for action in actions:
        kind = action["action_type"]
        result = {
            "action_id": action["action_id"],
            "action_type": kind,
            "target": action.get("target", kind),
        }
        if kind == "skip_duplicate":
            result.update(result="skipped", message=action["reason"])
            results.append(result)
            continue
        if kind == "master_bank_insert":
            row = dict(action["row"])
            normalized = normalize_item(row["item"])
            existing_rows = [existing for existing in master if normalize_item(existing["item"]) == normalized]
            if existing_rows:
                proposed = {key: str(value) for key, value in row.items() if key != "id"}
                exact = any(all(str(existing.get(key, "")) == value for key, value in proposed.items()) for existing in existing_rows)
                if exact:
                    result.update(result="skipped", message="idempotent existing master_bank row")
                    results.append(result)
                    continue
                raise ValidationError(f"master_bank_insert conflicts with existing item: {row['item']}")
            row["id"] = _next_master_id(master, row["date"])
            master.append(row)
            result["assigned_id"] = row["id"]
        elif kind == "master_bank_update":
            matches = [row for row in master if row["id"] == action["record_id"]]
            if len(matches) != 1:
                raise ValidationError(f"master_bank_update record_id not unique: {action['record_id']}")
            updates = {key: str(value) for key, value in action["updates"].items()}
            changes = {key: value for key, value in updates.items() if str(matches[0].get(key, "")) != value}
            if not changes:
                result.update(result="skipped", assigned_id=action["record_id"], message="idempotent no-change update")
                results.append(result)
                continue
            matches[0].update(changes)
            result["assigned_id"] = action["record_id"]
        elif kind == "mastered_insert":
            row = dict(action["row"])
            normalized = normalize_item(row["item"])
            existing_rows = [existing for existing in mastered if normalize_item(existing["item"]) == normalized]
            if existing_rows:
                if any(all(str(existing.get(key, "")) == str(value) for key, value in row.items()) for existing in existing_rows):
                    result.update(result="skipped", message="idempotent existing mastered row")
                    results.append(result)
                    continue
                raise ValidationError(f"mastered_insert conflicts with existing item: {row['item']}")
            mastered.append(row)
        elif kind == "sentence_pattern_append":
            title_norm = normalize_item(action["fields"]["title"])
            if any(title_norm == normalize_item(title) for title in re.findall(r"^## SP-\d{3}｜(.+)$", patterns, re.MULTILINE)):
                raise ValidationError("sentence_pattern_append duplicate title must use sentence_pattern_merge")
            card_id = _next_sp_id(patterns)
            if not patterns.endswith("\n"):
                patterns += "\n"
            patterns += "\n" + _render_sp_card(card_id, action["fields"])
            result["assigned_id"] = card_id
        elif kind == "sentence_pattern_merge":
            patterns, changed = _merge_sp_card(patterns, action["existing_sp_id"], action["additions"])
            if not changed:
                result.update(result="skipped", assigned_id=action["existing_sp_id"], message="idempotent SP merge")
                results.append(result)
                continue
            result["assigned_id"] = action["existing_sp_id"]
        elif kind in {"review_exclusion_append", "review_reactivation_append"}:
            event_type = (
                "exclude_from_review"
                if kind == "review_exclusion_append"
                else "reactivate_for_review"
            )
            if any(
                row.get("event_type") == event_type
                and normalize_item(str(row.get("item", "")))
                == normalize_item(action["item"])
                and row.get("bank_id") == action["bank_id"]
                and row.get("source_capture_event_ids")
                == action["source_capture_event_ids"]
                for row in review_records
            ):
                result.update(result="skipped", message="idempotent review status event")
                results.append(result)
                continue
            record = append_review_status_record(
                review_records,
                event_type=event_type,
                item=action["item"],
                bank_id=action["bank_id"],
                study_date=study_date,
                source_capture_event_ids=action["source_capture_event_ids"],
                sentence_evidence=action["sentence_evidence"],
                reason=action["reason"],
            )
            review_records.append(record)
            result["assigned_id"] = record["event_id"]
        safe_count += 1
        result.update(result="would_apply" if dry_run else "applied", message=action["reason"])
        results.append(result)
    for decision in unresolved:
        unresolved_count += 1
        results.append(
            {
                "action_id": decision["action_id"],
                "action_type": "needs_user",
                "target": decision["target"],
                "result": "needs_user",
                "message": decision["reason"],
            }
        )
    return (
        master, mastered, patterns, review_records, results,
        safe_count, unresolved_count,
    )


def _append_journal(path: Path, receipt_id: str, event_type: str, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_existed = path.exists()
    previous_hash = "0" * 64
    sequence = 1
    if path.exists():
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        expected_previous = "0" * 64
        for expected_sequence, line in enumerate(lines, start=1):
            record = json.loads(line)
            core = {key: value for key, value in record.items() if key != "record_sha256"}
            if record.get("sequence") != expected_sequence:
                raise ValidationError(f"journal sequence break at {path}:{expected_sequence}")
            if record.get("previous_sha256") != expected_previous:
                raise ValidationError(f"journal previous hash break at {path}:{expected_sequence}")
            if object_sha256(core) != record.get("record_sha256"):
                raise ValidationError(f"journal record hash mismatch at {path}:{expected_sequence}")
            expected_previous = record["record_sha256"]
        if lines:
            previous_hash = expected_previous
            sequence = len(lines) + 1
    core = {
        "sequence": sequence,
        "receipt_id": receipt_id,
        "event_type": event_type,
        "at": utc_now(),
        "previous_sha256": previous_hash,
        "data": data,
    }
    record = {**core, "record_sha256": object_sha256(core)}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    if not file_existed:
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def apply_nightly(
    state_dir: Path,
    repo_root: Path,
    *,
    manifest_path: Path,
    actions_path: Path,
    apply: bool = False,
    authorization: str | None = None,
    authorized_at: str | None = None,
    fault_after_replacements: int | None = None,
    fault_after_commit: bool = False,
) -> tuple[Path, dict[str, Any]]:
    manifest_path = manifest_path.resolve()
    actions_path = actions_path.resolve()
    manifest = load_json(manifest_path)
    actions_doc = load_json(actions_path)
    manifest_sha = file_sha256(manifest_path)
    actions_sha = file_sha256(actions_path)
    validate_sol_actions(actions_doc, manifest, manifest_sha)
    if apply and authorization != manifest["batch_id"]:
        raise AuthorizationError("apply requires --authorization equal to the exact frozen batch_id")
    started_at = utc_now()
    mode = "apply" if apply else "dry_run"
    receipt_id = "EN-RECEIPT-" + object_sha256(
        {"batch_id": manifest["batch_id"], "action_set_id": actions_doc["action_set_id"], "mode": mode, "time_ns": time.time_ns()}
    )[:16].upper()
    study_date = manifest["study_date"]
    journal_path = state_dir / "nightly" / study_date / f"{manifest['batch_id']}.journal.jsonl"
    receipt_path = state_dir / "receipts" / "nightly" / study_date / f"{receipt_id}.json"
    lock_path = state_dir / "locks" / "formal.lock"
    formal_paths = resolve_formal_paths(repo_root)
    formal_paths["review_exclusion_ledger"] = (
        repo_root / "bank" / "review_exclusion_ledger.jsonl"
    ).resolve()

    with exclusive_lock(lock_path):
        pending_transactions = _open_transaction_paths(state_dir)
        if pending_transactions:
            raise ValidationError(f"recovery_required: open formal transactions {pending_transactions}")
        prehashes = {
            name: _optional_file_sha256(path)
            for name, path in formal_paths.items()
        }
        expected = {name: manifest["formal_snapshot"][name]["sha256"] for name in formal_paths}
        _append_journal(journal_path, receipt_id, "started", {"mode": mode, "prehashes": prehashes})
        if prehashes != expected:
            receipt = {
                "schema_version": "english_apply_receipt_v1",
                "receipt_id": receipt_id,
                "batch_id": manifest["batch_id"],
                "action_set_id": actions_doc["action_set_id"],
                "mode": mode,
                "status": "CAS_CONFLICT",
                "started_at": started_at,
                "completed_at": utc_now(),
                "authorization": None,
                "manifest_sha256": manifest_sha,
                "actions_sha256": actions_sha,
                "lock_path": str(lock_path),
                "journal_path": str(journal_path),
                "formal_prehashes": prehashes,
                "proposed_posthashes": {},
                "formal_posthashes": prehashes,
                "formal_files_changed": False,
                "formal_write_count": 0,
                "action_results": [],
                "validation": {"status": "FAIL", "reason": "formal prehash drift", "expected": expected},
            }
            _append_journal(journal_path, receipt_id, "cas_conflict", receipt["validation"])
            atomic_write_json(receipt_path, receipt)
            return receipt_path, receipt

        master_rows = read_csv(formal_paths["master_bank"], MASTER_HEADER)
        mastered_rows = read_csv(formal_paths["mastered_items"], MASTERED_HEADER)
        sp_text = formal_paths["sentence_patterns"].read_text(encoding="utf-8")
        review_status_records = load_review_status_ledger(
            formal_paths["review_exclusion_ledger"]
        )
        (
            master, mastered, patterns, review_status_records,
            results, safe_count, unresolved_count,
        ) = _simulate(
            actions_doc["actions"],
            actions_doc["unresolved"],
            master_rows=master_rows,
            mastered_rows=mastered_rows,
            sp_text=sp_text,
            review_status_records=review_status_records,
            study_date=study_date,
            dry_run=not apply,
        )
        changed_action_types = {
            result["action_type"]
            for result in results
            if result["result"] in {"would_apply", "applied"}
        }
        proposed_bytes = {
            "master_bank": (
                serialize_csv(master, MASTER_HEADER)
                if changed_action_types & {"master_bank_insert", "master_bank_update"}
                else _optional_file_bytes(formal_paths["master_bank"])
            ),
            "mastered_items": (
                serialize_csv(mastered, MASTERED_HEADER)
                if "mastered_insert" in changed_action_types
                else _optional_file_bytes(formal_paths["mastered_items"])
            ),
            "sentence_patterns": (
                patterns.encode("utf-8")
                if changed_action_types & {"sentence_pattern_append", "sentence_pattern_merge"}
                else _optional_file_bytes(formal_paths["sentence_patterns"])
            ),
            "review_exclusion_ledger": (
                serialize_review_status_ledger(review_status_records)
                if changed_action_types
                & {"review_exclusion_append", "review_reactivation_append"}
                else _optional_file_bytes(
                    formal_paths["review_exclusion_ledger"]
                )
            ),
        }
        validate_sentence_patterns_text(patterns)
        proposed_hashes = {name: bytes_sha256(data) for name, data in proposed_bytes.items()}
        _append_journal(
            journal_path,
            receipt_id,
            "validated",
            {"safe_action_count": safe_count, "unresolved_count": unresolved_count, "proposed_hashes": proposed_hashes},
        )
        authorization_record = None
        if apply:
            authorization_record = {
                "command": "apply-nightly",
                "batch_id": manifest["batch_id"],
                "study_date": study_date,
                "authorized_at": authorized_at or utc_now(),
                "scope": manifest["authorization"]["scope"],
            }
            before_commit = {
                name: _optional_file_sha256(path)
                for name, path in formal_paths.items()
            }
            if before_commit != prehashes:
                raise ValidationError("formal files drifted after lock acquisition")
            transaction_dir = state_dir / "nightly" / study_date / manifest["batch_id"] / "transactions" / receipt_id
            backup_dir = transaction_dir / "preimages"
            staged_dir = transaction_dir / "staged"
            for name, path in formal_paths.items():
                atomic_write_bytes(
                    backup_dir / path.name, _optional_file_bytes(path)
                )
                atomic_write_bytes(staged_dir / path.name, proposed_bytes[name])
            transaction_path = transaction_dir / "transaction.json"
            transaction = {
                "schema_version": "english_formal_transaction_v1",
                "receipt_id": receipt_id,
                "batch_id": manifest["batch_id"],
                "study_date": study_date,
                "status": "prepared",
                "journal_path": str(journal_path),
                "formal_paths": {name: str(path) for name, path in formal_paths.items()},
                "preimages": {name: str(backup_dir / path.name) for name, path in formal_paths.items()},
                "staged": {name: str(staged_dir / path.name) for name, path in formal_paths.items()},
                "prehashes": prehashes,
                "proposed_hashes": proposed_hashes,
                "safe_action_count": safe_count,
                "unresolved_count": unresolved_count,
                "receipt_path": str(receipt_path),
                "replaced": [],
            }
            atomic_write_json(transaction_path, transaction)
            _append_journal(journal_path, receipt_id, "transaction_prepared", {"path": str(transaction_path)})
            replaced: list[str] = []
            try:
                for name, path in formal_paths.items():
                    if proposed_hashes[name] != prehashes[name]:
                        atomic_write_bytes(path, proposed_bytes[name])
                        replaced.append(name)
                        transaction["status"] = "committing"
                        transaction["replaced"] = list(replaced)
                        atomic_write_json(transaction_path, transaction)
                        if fault_after_replacements is not None and len(replaced) >= fault_after_replacements:
                            raise SimulatedWriterCrash(str(transaction_path))
                posthashes = {
                    name: _optional_file_sha256(path)
                    for name, path in formal_paths.items()
                }
                if posthashes != proposed_hashes:
                    raise ValidationError("post-write hashes differ from proposed hashes")
            except Exception:
                for name, path in formal_paths.items():
                    backup = backup_dir / path.name
                    if backup.exists():
                        atomic_write_bytes(path, backup.read_bytes())
                _append_journal(journal_path, receipt_id, "rolled_back", {"replaced": replaced})
                transaction["status"] = "rolled_back"
                atomic_write_json(transaction_path, transaction)
                raise
            status = "PARTIAL" if unresolved_count else ("APPLIED" if safe_count else "NO_ACTION")
            write_count = safe_count
            changed = posthashes != prehashes
            _append_journal(journal_path, receipt_id, "committed_pending_receipt", {"status": status, "posthashes": posthashes})
            transaction["status"] = "committed_pending_receipt"
            transaction["posthashes"] = posthashes
            atomic_write_json(transaction_path, transaction)
            if fault_after_commit:
                raise SimulatedWriterCrash(str(transaction_path))
        else:
            posthashes = {
                name: _optional_file_sha256(path)
                for name, path in formal_paths.items()
            }
            status = "DRY_RUN_PARTIAL" if unresolved_count else ("DRY_RUN_VALID" if safe_count else "DRY_RUN_NO_ACTION")
            write_count = 0
            changed = False
            _append_journal(journal_path, receipt_id, "dry_run_complete", {"status": status})

        receipt = {
            "schema_version": "english_apply_receipt_v1",
            "receipt_id": receipt_id,
            "batch_id": manifest["batch_id"],
            "action_set_id": actions_doc["action_set_id"],
            "mode": mode,
            "status": status,
            "started_at": started_at,
            "completed_at": utc_now(),
            "authorization": authorization_record,
            "manifest_sha256": manifest_sha,
            "actions_sha256": actions_sha,
            "lock_path": str(lock_path),
            "journal_path": str(journal_path),
            "formal_prehashes": prehashes,
            "proposed_posthashes": proposed_hashes,
            "formal_posthashes": posthashes,
            "formal_files_changed": changed,
            "formal_write_count": write_count,
            "action_results": results,
            "validation": {
                "status": "PASS" if not unresolved_count else "PARTIAL",
                "safe_action_count": safe_count,
                "unresolved_count": unresolved_count,
                "formal_schema": {"master_bank_columns": 13, "mastered_items_columns": 7, "sentence_pattern_fields": 15},
            },
        }
        atomic_write_json(receipt_path, receipt)
        if apply:
            transaction["status"] = "closed"
            transaction["receipt_sha256"] = file_sha256(receipt_path)
            atomic_write_json(transaction_path, transaction)
            _append_journal(journal_path, receipt_id, "receipt_closed", {"receipt_path": str(receipt_path), "receipt_sha256": transaction["receipt_sha256"]})
        return receipt_path, receipt


def recover_nightly(
    state_dir: Path,
    repo_root: Path,
    *,
    transaction_path: Path | None = None,
) -> dict[str, Any]:
    candidates = (
        [transaction_path.resolve()]
        if transaction_path is not None
        else sorted((state_dir / "nightly").glob("*/*/transactions/*/transaction.json"))
    )
    lock_path = state_dir / "locks" / "formal.lock"
    formal_paths = resolve_formal_paths(repo_root)
    formal_paths["review_exclusion_ledger"] = (
        repo_root / "bank" / "review_exclusion_ledger.jsonl"
    ).resolve()
    recovered: list[dict[str, Any]] = []
    with exclusive_lock(lock_path):
        for path in candidates:
            transaction = load_json(path)
            if transaction.get("status") not in OPEN_TRANSACTION_STATUSES:
                recovered.append({"transaction": str(path), "status": "skipped", "reason": transaction.get("status")})
                continue
            if transaction.get("formal_paths") != {name: str(value) for name, value in formal_paths.items()}:
                recovered.append({"transaction": str(path), "status": "failed", "reason": "formal path mismatch"})
                continue
            current = {
                name: _optional_file_sha256(value)
                for name, value in formal_paths.items()
            }
            prehashes = transaction["prehashes"]
            proposed = transaction["proposed_hashes"]
            unknown = [name for name, digest in current.items() if digest not in {prehashes[name], proposed[name]}]
            journal_path = Path(transaction["journal_path"])
            if unknown:
                recovered.append({"transaction": str(path), "status": "failed", "reason": f"unknown external drift: {unknown}"})
                _append_journal(journal_path, transaction["receipt_id"], "recovery_blocked", {"unknown": unknown})
                continue
            receipt_path = Path(transaction.get("receipt_path", ""))
            if receipt_path.is_file() and transaction.get("status") in {"committed", "committed_pending_receipt"}:
                transaction["status"] = "closed"
                transaction["receipt_sha256"] = file_sha256(receipt_path)
                atomic_write_json(path, transaction)
                _append_journal(journal_path, transaction["receipt_id"], "recovered_commit_with_receipt", {"posthashes": current})
                recovered.append({"transaction": str(path), "status": "RECOVERED_COMMIT_WITH_RECEIPT"})
                continue
            for name, formal_path in formal_paths.items():
                preimage = Path(transaction["preimages"][name])
                if not preimage.is_file() or file_sha256(preimage) != prehashes[name]:
                    raise ValidationError(f"recovery preimage missing or corrupt: {preimage}")
                atomic_write_bytes(formal_path, preimage.read_bytes())
            restored = {
                name: _optional_file_sha256(value)
                for name, value in formal_paths.items()
            }
            if restored != prehashes:
                raise ValidationError("recovery rollback hashes do not match prehashes")
            transaction["status"] = "recovered_rollback"
            transaction["posthashes"] = restored
            atomic_write_json(path, transaction)
            _append_journal(journal_path, transaction["receipt_id"], "recovered_rollback", {"posthashes": restored})
            recovered.append({"transaction": str(path), "status": "RECOVERED_ROLLBACK"})
    recovery_receipt = {
        "schema_version": "english_recovery_receipt_v1",
        "status": "PASS" if not any(row["status"] == "failed" for row in recovered) else "PARTIAL",
        "recovered": recovered,
        "formal_write_count": 0,
    }
    receipt_id = "EN-RECOVERY-" + object_sha256({"time_ns": time.time_ns(), "recovered": recovered})[:16].upper()
    receipt_day = next((load_json(path).get("study_date") for path in candidates if path.is_file()), "unknown-date")
    receipt_path = state_dir / "receipts" / "recovery" / str(receipt_day) / f"{receipt_id}.json"
    recovery_receipt["receipt_id"] = receipt_id
    recovery_receipt["receipt_path"] = str(receipt_path)
    atomic_write_json(receipt_path, recovery_receipt)
    return recovery_receipt
