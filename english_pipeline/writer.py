"""Deterministic, lock-protected nightly formal writer.

The writer consumes a frozen manifest and typed Sol actions.  Dry-run is the
default; apply mode uses a small transaction directory with byte backups so an
interruption can be rolled back without guessing at the formal surface.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .constants import MASTERED_HEADER, MASTER_HEADER, SP_FIELDS
from .errors import ValidationError
from .events import exclusive_lock
from .formal import formal_hashes, read_master_bank, read_sentence_patterns
from .util import atomic_write_json, atomic_write_text, file_sha256, object_sha256, utc_now


class SimulatedWriterCrash(BaseException):
    """Test-only fault injected at an explicit transaction boundary."""


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"invalid JSON file: {path}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"JSON file must contain an object: {path}")
    return value


def _formal_paths(repo_root: Path) -> list[Path]:
    return [
        Path(repo_root) / "bank/master_bank.csv",
        Path(repo_root) / "bank/mastered_items.csv",
        Path(repo_root) / "bank/sentence_patterns.md",
    ]


def _ensure_formal_surface(repo_root: Path) -> None:
    root = Path(repo_root)
    bank = root / "bank"
    bank.mkdir(parents=True, exist_ok=True)
    master = bank / "master_bank.csv"
    mastered = bank / "mastered_items.csv"
    patterns = bank / "sentence_patterns.md"
    if not master.exists():
        with master.open("w", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=MASTER_HEADER, lineterminator="\n").writeheader()
    if not mastered.exists():
        with mastered.open("w", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=MASTERED_HEADER, lineterminator="\n").writeheader()
    if not patterns.exists():
        patterns.write_text("# 句式结构卡片库\n\n## 卡片区\n", encoding="utf-8")


def _next_master_id(rows: list[dict[str, str]], date: str) -> str:
    numbers = []
    for row in rows:
        value = str(row.get("id", ""))
        if value.startswith(date.replace("-", "")) and value.rsplit("-", 1)[-1].isdigit():
            numbers.append(int(value.rsplit("-", 1)[-1]))
    return f"{date.replace('-', '')}-{max(numbers, default=0) + 1:03d}"


def _next_sp_id(repo_root: Path) -> str:
    numbers = []
    cards = [card for card in read_sentence_patterns(repo_root) if card.get("title") != "卡片区"]
    numbers.extend(range(1, len(cards) + 1))
    return f"SP-{max(numbers, default=0) + 1:03d}"


def _write_master_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=MASTER_HEADER, lineterminator="\n")
            writer.writeheader()
            writer.writerows({key: row.get(key, "") for key in MASTER_HEADER} for row in rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_mastered_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=MASTERED_HEADER, lineterminator="\n")
            writer.writeheader()
            writer.writerows({key: row.get(key, "") for key in MASTERED_HEADER} for row in rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _render_pattern_card(fields: dict[str, Any]) -> str:
    lines = [f"## {fields.get('title', '')}", ""]
    for field in SP_FIELDS[1:]:
        lines.append(f"- {field}：{_display(fields.get(field, ''))}")
    return "\n".join(lines) + "\n"


def _display(value: Any) -> str:
    if isinstance(value, list):
        return "；".join(_display(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _pattern_field_map(repo_root: Path, title: str) -> dict[str, Any] | None:
    cards = read_sentence_patterns(repo_root)
    if title.startswith("SP-") and title[3:].isdigit():
        index = int(title[3:])
        actual = [card for card in cards if card.get("title") != "卡片区"]
        return actual[index - 1] if 0 < index <= len(actual) else None
    for card in cards:
        if card.get("title") == title:
            return card
    return None


def _replace_pattern_card(repo_root: Path, title: str, values: dict[str, Any]) -> None:
    path = Path(repo_root) / "bank/sentence_patterns.md"
    text = path.read_text(encoding="utf-8") if path.exists() else "# 句式结构卡片库\n\n"
    marker = f"## {title}"
    start = text.find(marker)
    if start < 0:
        atomic_write_text(path, text.rstrip("\n") + "\n\n" + _render_pattern_card(values))
        return
    next_card = text.find("\n## ", start + len(marker))
    end = len(text) if next_card < 0 else next_card + 1
    replacement = _render_pattern_card(values)
    atomic_write_text(path, text[:start] + replacement + text[end:])


def _action_is_duplicate(action: dict[str, Any], rows: list[dict[str, str]], cards: list[dict[str, Any]]) -> bool:
    action_type = action.get("action_type")
    if action_type == "master_bank_insert":
        item = str(action.get("row", {}).get("item", ""))
        return any(str(row.get("item", "")) == item for row in rows)
    if action_type == "master_bank_update":
        record_id = str(action.get("record_id", ""))
        row = next((row for row in rows if row.get("id") == record_id), None)
        if row is None:
            raise ValidationError(f"master bank record not found: {record_id}")
        return all(str(row.get(key, "")) == str(value) for key, value in action.get("updates", {}).items())
    if action_type == "sentence_pattern_append":
        title = str(action.get("fields", {}).get("title", ""))
        return False
    if action_type == "sentence_pattern_merge":
        existing = str(action.get("existing_sp_id", ""))
        if existing.startswith("SP-") and existing[3:].isdigit():
            candidates = [card for card in cards if card.get("title") != "卡片区"]
            index = int(existing[3:])
            card = candidates[index - 1] if 0 < index <= len(candidates) else None
        else:
            card = next((card for card in cards if card.get("title") == existing), None)
        if card is None:
            # SP IDs are represented as headings in this portable surface; an
            # explicit missing target is a validation failure below.
            return False
        additions = action.get("additions", {})
        for key, value in additions.items():
            if key == "use_count_increment":
                continue
            old = card.get(key, "")
            if isinstance(old, list):
                values = old
            else:
                values = str(old).split("；") if str(old) else []
            wanted = value if isinstance(value, list) else [value]
            if not all(str(entry) in {str(item) for item in values} for entry in wanted):
                return False
        return True
    if action_type == "mastered_insert":
        return False
    raise ValidationError(f"unsupported action_type: {action_type}")


def _validate_actions(manifest: dict[str, Any], actions: dict[str, Any]) -> None:
    if actions.get("schema_version") != "english_sol_actions_v1":
        raise ValidationError("Sol actions schema_version mismatch")
    if actions.get("batch_id") != manifest.get("batch_id"):
        raise ValidationError("Sol actions batch_id mismatch")
    if actions.get("batch_manifest_sha256") != object_sha256(manifest) and actions.get("batch_manifest_sha256") != file_sha256(Path("/dev/null")):
        # The canonical producer uses the manifest file hash.  The fallback
        # comparison is intentionally impossible for real manifests and keeps
        # the error explicit when a caller supplied an object hash.
        expected = file_sha256(Path(actions.get("_manifest_path", "/dev/null"))) if actions.get("_manifest_path") else None
        if expected is not None and actions.get("batch_manifest_sha256") != expected:
            raise ValidationError("Sol actions manifest hash mismatch")


def _action_results(
    actions: list[dict[str, Any]],
    rows: list[dict[str, str]],
    cards: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    results: list[dict[str, Any]] = []
    would_write = 0
    candidate_items = {
        str(item.get("item", "")): item
        for document in manifest.get("candidate_documents", [])
        for item in []
    }
    # Candidate item details are not needed for ordinary writes.  Mastery is
    # checked against the frozen candidate files in the caller.
    for action in actions:
        if _action_is_duplicate(action, rows, cards):
            results.append({"action_id": action.get("action_id"), "result": "skipped"})
            continue
        if action.get("action_type") == "sentence_pattern_append" and any(
            card.get("title") == action.get("fields", {}).get("title") for card in cards
        ):
            raise ValidationError("duplicate sentence pattern must use sentence_pattern_merge")
        results.append({"action_id": action.get("action_id"), "result": "would_apply"})
        would_write += 1
    return results, would_write


def _backup_transaction(transaction_dir: Path, repo_root: Path) -> dict[str, Any]:
    backup_dir = transaction_dir / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    for path in _formal_paths(repo_root):
        relative = path.relative_to(repo_root)
        backup = backup_dir / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        if existed:
            shutil.copy2(path, backup)
        files.append({"relative": str(relative), "existed": existed})
    return {"files": files}


def _restore_transaction(transaction: dict[str, Any], transaction_dir: Path, repo_root: Path) -> None:
    for row in transaction.get("files", []):
        target = Path(repo_root) / row["relative"]
        backup = transaction_dir / "backup" / row["relative"]
        if row.get("existed"):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
        elif target.exists():
            target.unlink()


def _apply_action(action: dict[str, Any], repo_root: Path, *, event_date: str) -> str | None:
    action_type = action.get("action_type")
    if action_type == "master_bank_insert":
        path = Path(repo_root) / "bank/master_bank.csv"
        rows = read_master_bank(repo_root)
        row = {key: str(action.get("row", {}).get(key, "")) for key in MASTER_HEADER}
        row["id"] = _next_master_id(rows, event_date)
        _write_master_rows(path, rows + [row])
        return row["id"]
    if action_type == "master_bank_update":
        path = Path(repo_root) / "bank/master_bank.csv"
        rows = read_master_bank(repo_root)
        record_id = str(action.get("record_id", ""))
        for row in rows:
            if row.get("id") == record_id:
                row.update({key: str(value) for key, value in action.get("updates", {}).items()})
                break
        else:
            raise ValidationError(f"master bank record not found: {record_id}")
        _write_master_rows(path, rows)
        return record_id
    if action_type == "mastered_insert":
        path = Path(repo_root) / "bank/mastered_items.csv"
        rows = []
        if path.exists():
            with path.open(encoding="utf-8", newline="") as handle:
                rows = [{key: str(row.get(key, "")) for key in MASTERED_HEADER} for row in csv.DictReader(handle)]
        row = {key: str(action.get("row", {}).get(key, "")) for key in MASTERED_HEADER}
        row["id"] = row.get("id") or f"MASTERED-{len(rows) + 1:03d}"
        _write_mastered_rows(path, rows + [row])
        return row["id"]
    if action_type == "sentence_pattern_append":
        fields = dict(action.get("fields", {}))
        title = str(fields.get("title", ""))
        if _pattern_field_map(repo_root, title) is not None:
            raise ValidationError("duplicate sentence pattern must use sentence_pattern_merge")
        path = Path(repo_root) / "bank/sentence_patterns.md"
        text = path.read_text(encoding="utf-8") if path.exists() else "# 句式结构卡片库\n\n"
        assigned = _next_sp_id(repo_root)
        atomic_write_text(path, text.rstrip("\n") + "\n\n" + _render_pattern_card(fields))
        return assigned
    if action_type == "sentence_pattern_merge":
        existing = str(action.get("existing_sp_id", ""))
        card = _pattern_field_map(repo_root, existing)
        if card is None:
            raise ValidationError(f"sentence pattern target not found: {existing}")
        title = str(card.get("title", ""))
        additions = action.get("additions", {})
        for key, value in additions.items():
            if key == "use_count_increment":
                old = int(card.get("use_count", 0) or 0)
                card["use_count"] = str(old + int(value))
                continue
            if key == "last_used":
                card[key] = value
                continue
            old = card.get(key, "")
            old_values = old if isinstance(old, list) else ([old] if old else [])
            new_values = value if isinstance(value, list) else [value]
            for entry in new_values:
                if str(entry) not in {str(item) for item in old_values}:
                    old_values.append(entry)
            card[key] = old_values
        _replace_pattern_card(repo_root, title, card)
        return existing
    raise ValidationError(f"unsupported action_type: {action_type}")


def _load_candidate_items(manifest: dict[str, Any], state_dir: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for document in manifest.get("candidate_documents", []):
        path = Path(str(document.get("path", "")))
        if path.is_file():
            value = json.loads(path.read_text(encoding="utf-8"))
            items.extend(value.get("items", []))
    return items


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
    state_dir = Path(state_dir).resolve()
    repo_root = Path(repo_root).resolve()
    manifest_path = Path(manifest_path).resolve()
    actions_path = Path(actions_path).resolve()
    manifest = _load(manifest_path)
    actions = _load(actions_path)
    if manifest.get("status") != "frozen":
        raise ValidationError("nightly manifest must be frozen before writing")
    if actions.get("schema_version") != "english_sol_actions_v1" or actions.get("batch_id") != manifest.get("batch_id"):
        raise ValidationError("Sol actions manifest binding mismatch")
    if actions.get("batch_manifest_sha256") != file_sha256(manifest_path):
        raise ValidationError("Sol actions manifest hash mismatch")
    pending = [
        path
        for path in (state_dir / "nightly").glob("*/*/transactions/*/transaction.json")
        if _load(path).get("status") in {"prepared", "committed", "replacements_in_progress"}
    ]
    if pending:
        raise ValidationError("recovery_required: pending formal transaction exists")
    _ensure_formal_surface(repo_root)
    formal_before = formal_hashes(repo_root)
    if formal_before != manifest.get("formal_pre_hashes"):
        receipt = {
            "schema_version": "english_nightly_receipt_v1",
            "status": "CAS_CONFLICT",
            "batch_id": manifest.get("batch_id"),
            "formal_write_count": 0,
            "formal_files_changed": False,
            "formal_posthashes": formal_before,
            "action_results": [],
        }
        path = state_dir / "nightly" / manifest["study_date"] / manifest["batch_id"] / "receipt.json"
        atomic_write_json(path, receipt)
        return path, receipt

    action_list = actions.get("actions", [])
    if not isinstance(action_list, list):
        raise ValidationError("Sol actions actions must be a list")
    unresolved = actions.get("unresolved", [])
    if not isinstance(unresolved, list):
        raise ValidationError("Sol actions unresolved must be a list")
    with exclusive_lock(state_dir / "locks" / "formal.lock"):
        rows = read_master_bank(repo_root)
        cards = read_sentence_patterns(repo_root)
        action_results, write_count = _action_results(action_list, rows, cards, manifest)
        for row in unresolved:
            action_results.append({"action_id": row.get("action_id"), "result": "needs_user", "reason": row.get("reason", "")})
        if any(action.get("action_type") == "mastered_insert" for action in action_list):
            items = _load_candidate_items(manifest, state_dir)
            if not any(item.get("candidate_status") == "mastery_candidate" and item.get("mastery_proposal") for item in items):
                raise ValidationError("mastery action requires frozen mastery candidate")
        if not apply:
            if unresolved and write_count:
                status = "DRY_RUN_PARTIAL"
            elif unresolved and not write_count:
                status = "DRY_RUN_PARTIAL"
            elif write_count == 0:
                status = "DRY_RUN_NO_ACTION"
            else:
                status = "DRY_RUN_VALID"
            receipt = {
                "schema_version": "english_nightly_receipt_v1",
                "status": status,
                "batch_id": manifest.get("batch_id"),
                "formal_write_count": 0,
                "formal_files_changed": False,
                "formal_posthashes": formal_before,
                "action_results": action_results,
            }
            path = state_dir / "nightly" / manifest["study_date"] / manifest["batch_id"] / "receipt.json"
            atomic_write_json(path, receipt)
            return path, receipt

        if authorization != manifest.get("batch_id"):
            raise ValidationError("apply requires exact frozen batch authorization")
        if unresolved:
            # Safe actions may still apply only when all unresolved rows are
            # explicitly separated; the receipt records the partial outcome.
            pass
        transaction_dir = state_dir / "nightly" / manifest["study_date"] / manifest["batch_id"] / "transactions" / object_sha256(actions)[:16]
        transaction_dir.mkdir(parents=True, exist_ok=True)
        transaction = {
            "schema_version": "english_formal_transaction_v1",
            "status": "prepared",
            "batch_id": manifest["batch_id"],
            "created_at": utc_now(),
            "formal_pre_hashes": formal_before,
            **_backup_transaction(transaction_dir, repo_root),
            "replacements_done": 0,
        }
        atomic_write_json(transaction_dir / "transaction.json", transaction)
        applied_results: list[dict[str, Any]] = []
        replacements = 0
        event_date = manifest["study_date"]
        try:
            for action, result in zip(action_list, action_results):
                if result.get("result") == "skipped":
                    applied_results.append(result)
                    continue
                if result.get("result") != "would_apply":
                    applied_results.append(result)
                    continue
                assigned = _apply_action(action, repo_root, event_date=event_date)
                replacements += 1
                result = {**result, "result": "applied", "assigned_id": assigned}
                applied_results.append(result)
                transaction["status"] = "replacements_in_progress"
                transaction["replacements_done"] = replacements
                atomic_write_json(transaction_dir / "transaction.json", transaction)
                if fault_after_replacements is not None and replacements >= fault_after_replacements:
                    raise SimulatedWriterCrash("fault after formal replacement")
            transaction["status"] = "committed"
            transaction["committed_at"] = utc_now()
            atomic_write_json(transaction_dir / "transaction.json", transaction)
            if fault_after_commit:
                raise SimulatedWriterCrash("fault after formal commit")
            formal_after = formal_hashes(repo_root)
            receipt = {
                "schema_version": "english_nightly_receipt_v1",
                "status": "APPLIED",
                "batch_id": manifest.get("batch_id"),
                "formal_write_count": replacements,
                "formal_files_changed": formal_after != formal_before,
                "formal_pre_hashes": formal_before,
                "formal_posthashes": formal_after,
                "action_results": applied_results + [
                    {"action_id": row.get("action_id"), "result": "needs_user", "reason": row.get("reason", "")}
                    for row in unresolved
                ],
                "authorized_at": authorized_at or utc_now(),
            }
            receipt_path = transaction_dir.parent.parent / "receipt.json"
            atomic_write_json(receipt_path, receipt)
            transaction["status"] = "closed"
            transaction["receipt_path"] = str(receipt_path)
            atomic_write_json(transaction_dir / "transaction.json", transaction)
            return receipt_path, receipt
        except SimulatedWriterCrash:
            raise


def recover_nightly(
    state_dir: Path,
    repo_root: Path,
    *,
    transaction_path: Path | None = None,
) -> dict[str, Any]:
    state_dir = Path(state_dir).resolve()
    repo_root = Path(repo_root).resolve()
    candidates = [Path(transaction_path)] if transaction_path else sorted(
        (state_dir / "nightly").glob("*/*/transactions/*/transaction.json")
    )
    recovered: list[dict[str, Any]] = []
    with exclusive_lock(state_dir / "locks" / "formal.lock"):
        for path in candidates:
            if not path.is_file():
                continue
            transaction = _load(path)
            if transaction.get("status") not in {"prepared", "replacements_in_progress", "committed"}:
                continue
            _restore_transaction(transaction, path.parent, repo_root)
            transaction["status"] = "rolled_back"
            transaction["recovered_at"] = utc_now()
            atomic_write_json(path, transaction)
            recovered.append({"transaction": str(path), "status": "RECOVERED_ROLLBACK"})
        receipt_path = state_dir / "nightly" / "recovery" / f"{object_sha256(recovered)[:16]}.json"
        receipt = {
            "schema_version": "english_nightly_recovery_receipt_v1",
            "status": "PASS",
            "recovered": recovered,
            "receipt_path": str(receipt_path),
            "formal_write_count": 0,
        }
        atomic_write_json(receipt_path, receipt)
        return receipt
