from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .candidates import validate_luna_candidate
from .errors import IdempotencyConflict, ValidationError
from .events import effective_sentence_events, event_by_id, load_events
from .constants import MASTERED_HEADER, MASTER_HEADER
from .formal import formal_snapshot, read_csv
from .review_status import (
    build_review_status_proposals,
    effective_review_status,
    load_review_status_ledger,
)
from .util import atomic_write_json, bytes_sha256, file_sha256, load_json, object_sha256, utc_now


def discover_candidate_paths(state_dir: Path, study_date: str) -> list[Path]:
    root = state_dir / "candidates" / study_date
    if not root.is_dir():
        return []
    return sorted(path for path in root.rglob("*.json") if path.is_file())


def freeze_nightly(
    state_dir: Path,
    repo_root: Path,
    *,
    study_date: str,
    candidate_paths: Iterable[Path] | None = None,
    output: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    paths = [path.resolve() for path in (candidate_paths or discover_candidate_paths(state_dir, study_date))]
    documents: list[dict[str, Any]] = []
    capture_ids: set[str] = set()
    for path in paths:
        if not path.is_file():
            raise ValidationError(f"candidate document missing: {path}")
        candidate = load_json(path)
        validate_luna_candidate(candidate, state_dir=state_dir)
        if candidate["study_date"] != study_date:
            raise ValidationError(
                f"candidate study_date mismatch for {path}: {candidate['study_date']} != {study_date}"
            )
        if candidate["validation"]["status"] != "PASS":
            raise ValidationError(f"blocked Luna candidate cannot be frozen: {path}")
        documents.append(
            {
                "path": str(path),
                "sha256": file_sha256(path),
                "candidate_id": candidate["candidate_id"],
                "runtime_identity_status": candidate["runtime_identity"]["status"],
            }
        )
        capture_ids.update(candidate["capture_event_ids"])
    all_events = load_events(state_dir)
    by_id = event_by_id(all_events)
    article_source_hashes: dict[str, str] = {}
    sentence_hashes: dict[str, str] = {}
    for capture_id in sorted(capture_ids):
        event = by_id.get(capture_id)
        if event is None:
            raise ValidationError(f"frozen capture event missing: {capture_id}")
        if event.get("learning", {}).get("evidence_origin") == "synthetic_fixture":
            raise ValidationError(f"synthetic_fixture capture cannot enter production freeze: {capture_id}")
        article_id = event["article"]["article_id"]
        article_hash = event["article"]["source_hash"]
        previous_article_hash = article_source_hashes.get(article_id)
        if previous_article_hash and previous_article_hash != article_hash:
            raise ValidationError(f"conflicting article source hashes for {article_id}")
        article_source_hashes[article_id] = article_hash
        sentence_hashes[capture_id] = event["source"]["sentence_hash"]
    day_capture_ids = {
        event["event_id"]
        for event in effective_sentence_events(all_events, study_date=study_date)
        if event.get("source", {}).get("source_kind") != "explanation"
        and event.get("learning", {}).get("evidence_origin") != "synthetic_fixture"
    }
    uncovered_capture_ids = sorted(day_capture_ids - capture_ids)
    documents.sort(key=lambda row: (row["candidate_id"], row["path"]))
    runtime_identity_summary = {
        status: sorted(
            row["candidate_id"]
            for row in documents
            if row["runtime_identity_status"] == status
        )
        for status in ("confirmed", "requested_unverified", "mismatch", "unavailable")
    }
    snapshot = formal_snapshot(repo_root)
    ledger_path = repo_root / "bank" / "review_exclusion_ledger.jsonl"
    ledger_records = load_review_status_ledger(ledger_path)
    review_status_proposals = build_review_status_proposals(
        effective_sentence_events(all_events, study_date=study_date),
        read_csv(repo_root / "bank" / "master_bank.csv", MASTER_HEADER),
        study_date=study_date,
        current_status=effective_review_status(ledger_records),
        mastered_items=read_csv(
            repo_root / "bank" / "mastered_items.csv", MASTERED_HEADER
        ),
    )
    snapshot["review_exclusion_ledger"] = {
        "path": str(ledger_path.resolve()),
        "exists": ledger_path.exists(),
        "sha256": (
            file_sha256(ledger_path)
            if ledger_path.exists()
            else bytes_sha256(b"")
        ),
        "event_count": len(ledger_records),
    }
    review_status_source_hashes = {
        "master_bank": snapshot["master_bank"]["sha256"],
        "mastered_items": snapshot["mastered_items"]["sha256"],
        "review_exclusion_ledger": snapshot["review_exclusion_ledger"]["sha256"],
    }
    batch_identity = object_sha256(
        {
            "study_date": study_date,
            "candidate_documents": documents,
            "runtime_identity_summary": runtime_identity_summary,
            "capture_event_ids": sorted(capture_ids),
            "source_snapshot": {
                "article_source_hashes": dict(sorted(article_source_hashes.items())),
                "sentence_hashes": dict(sorted(sentence_hashes.items())),
            },
            "uncovered_capture_event_ids": uncovered_capture_ids,
            "review_status_proposals": review_status_proposals,
            "review_status_source_hashes": review_status_source_hashes,
            "formal_hashes": {name: row["sha256"] for name, row in snapshot.items()},
        }
    )[:12].upper()
    batch_id = f"EN-BATCH-{study_date.replace('-', '')}-{batch_identity}"
    manifest = {
        "schema_version": "english_nightly_manifest_v2",
        "batch_id": batch_id,
        "study_date": study_date,
        "frozen_at": utc_now(),
        "candidate_documents": documents,
        "runtime_identity_summary": runtime_identity_summary,
        "capture_event_ids": sorted(capture_ids),
        "source_snapshot": {
            "article_source_hashes": dict(sorted(article_source_hashes.items())),
            "sentence_hashes": dict(sorted(sentence_hashes.items())),
        },
        "uncovered_capture_event_ids": uncovered_capture_ids,
        "review_status_proposals": review_status_proposals,
        "review_status_proposals_sha256": object_sha256(
            review_status_proposals
        ),
        "review_status_source_hashes": review_status_source_hashes,
        "formal_snapshot": snapshot,
        "authorization": {
            "command": "apply-nightly",
            "batch_id": batch_id,
            "study_date": study_date,
            "authorized": False,
            "authorized_at": None,
            "scope": [
                "master_bank", "mastered_items", "sentence_patterns",
                "review_exclusion_ledger",
            ],
        },
        "status": (
            "needs_preprocess"
            if uncovered_capture_ids
            else ("frozen" if documents else "NOOP")
        ),
    }
    target = output or state_dir / "nightly" / study_date / f"{batch_id}.manifest.json"
    if target.exists():
        existing = load_json(target)
        comparable_existing = {key: value for key, value in existing.items() if key != "frozen_at"}
        comparable_new = {key: value for key, value in manifest.items() if key != "frozen_at"}
        if comparable_existing != comparable_new:
            raise IdempotencyConflict(f"immutable nightly manifest already exists with different content: {target}")
        return target, existing
    atomic_write_json(target, manifest)
    return target, manifest


def pipeline_status(state_dir: Path) -> dict[str, Any]:
    from .events import load_events, validate_event

    events = load_events(state_dir)
    event_counts: dict[str, int] = {}
    for event in events:
        validate_event(event)
        kind = str(event.get("event_type", "unknown"))
        event_counts[kind] = event_counts.get(kind, 0) + 1
    candidate_files = sorted((state_dir / "candidates").glob("**/*.json"))
    manifest_files = sorted((state_dir / "nightly").glob("**/*.manifest.json"))
    receipt_files = sorted((state_dir / "receipts").glob("**/*.json"))
    latest_receipts: list[dict[str, Any]] = []
    for path in receipt_files[-10:]:
        try:
            receipt = load_json(path)
        except Exception:
            continue
        latest_receipts.append(
            {
                "path": str(path),
                "receipt_id": receipt.get("receipt_id"),
                "status": receipt.get("status"),
            }
        )
    return {
        "schema_version": "english_pipeline_status_v1",
        "state_dir": str(state_dir.resolve()),
        "event_counts": event_counts,
        "event_total": len(events),
        "candidate_document_count": len(candidate_files),
        "nightly_manifest_count": len(manifest_files),
        "receipt_count": len(receipt_files),
        "latest_receipts": latest_receipts,
        "event_validation": "PASS",
    }


def validate_events_report(state_dir: Path, *, study_date: str | None = None) -> dict[str, Any]:
    from .events import load_events, validate_event
    from .util import object_sha256, parse_iso_date

    records: list[dict[str, Any]] = []
    for event in load_events(state_dir):
        event_date = parse_iso_date(str(event["occurred_at"]))
        if study_date is not None and event_date != study_date:
            continue
        validate_event(event)
        records.append(
            {
                "event_id": event["event_id"],
                "event_type": event["event_type"],
                "study_date": event_date,
                "event_sha256": object_sha256(event),
                "source_id": event["article"]["source_id"],
                "article_source_hash": event["article"]["source_hash"],
                "sentence_hash": event.get("source", {}).get("sentence_hash"),
                "evidence_origin": event.get("learning", {}).get("evidence_origin"),
            }
        )
    return {
        "schema_version": "english_event_validation_report_v1",
        "status": "PASS",
        "study_date": study_date,
        "validated_event_count": len(records),
        "events": records,
        "formal_write_count": 0,
    }
