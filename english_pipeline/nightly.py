"""Date-bounded candidate freeze and read-only pipeline reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .candidates import validate_luna_candidate
from .errors import ValidationError
from .events import effective_sentence_events, load_events
from .formal import formal_hashes
from .util import atomic_write_json, file_sha256, object_sha256, parse_iso_date


def _candidate_path(state_dir: Path, study_date: str, candidate_id: str) -> Path:
    return state_dir / "candidates" / study_date / f"{candidate_id}.json"


def _load_candidate(path: Path, state_dir: Path) -> dict[str, Any]:
    candidate = json.loads(path.read_text(encoding="utf-8"))
    return validate_luna_candidate(candidate, state_dir=state_dir)


def _manifest_identity(
    study_date: str,
    event_ids: list[str],
    candidate_hashes: list[str],
    formal_pre_hashes: dict[str, str | None],
) -> str:
    return "NIGHTLY-" + object_sha256(
        {
            "study_date": study_date,
            "event_ids": event_ids,
            "candidate_hashes": candidate_hashes,
            "formal_pre_hashes": formal_pre_hashes,
        }
    )[:24].upper()


def freeze_nightly(
    state_dir: Path,
    repo_root: Path,
    *,
    study_date: str,
    candidate_paths: list[Path] | None = None,
    output: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    state_dir = Path(state_dir).resolve()
    repo_root = Path(repo_root).resolve()
    events = load_events(state_dir)
    day_events = [
        event
        for event in effective_sentence_events(events, study_date=study_date)
        if event.get("event_type") in {"sentence_captured", "sentence_correction"}
    ]
    event_ids = sorted(str(event["event_id"]) for event in day_events)
    if candidate_paths is None:
        candidate_paths = sorted((state_dir / "candidates" / study_date).glob("*.json"))
    candidates: list[dict[str, Any]] = []
    candidate_documents: list[dict[str, Any]] = []
    for path in candidate_paths:
        candidate = _load_candidate(Path(path), state_dir)
        candidates.append(candidate)
        candidate_documents.append(
            {
                "candidate_id": candidate["candidate_id"],
                "path": str(Path(path)),
                "sha256": file_sha256(Path(path)),
                "capture_event_ids": list(candidate.get("capture_event_ids", [])),
                "item_count": len(candidate.get("items", [])),
                "runtime_identity_status": candidate.get("runtime_identity_status", candidate["runtime_identity"]["status"]),
                "validation_status": candidate.get("validation", {}).get("status"),
            }
        )
    covered = {
        event_id
        for candidate in candidates
        for event_id in candidate.get("capture_event_ids", [])
    }
    uncovered = [event_id for event_id in event_ids if event_id not in covered]
    formal_pre_hashes = formal_hashes(repo_root)
    candidate_hashes = [row["sha256"] for row in candidate_documents]
    batch_id = _manifest_identity(study_date, event_ids, candidate_hashes, formal_pre_hashes)
    status = "NOOP" if not day_events else ("needs_preprocess" if uncovered else "frozen")
    runtime_summary = {
        "confirmed": sorted(
            row["candidate_id"] for row in candidate_documents if row["runtime_identity_status"] == "confirmed"
        ),
        "requested_unverified": sorted(
            row["candidate_id"] for row in candidate_documents if row["runtime_identity_status"] == "requested_unverified"
        ),
        "mismatch": sorted(
            row["candidate_id"] for row in candidate_documents if row["runtime_identity_status"] == "mismatch"
        ),
        "unavailable": sorted(
            row["candidate_id"] for row in candidate_documents if row["runtime_identity_status"] == "unavailable"
        ),
    }
    manifest = {
        "schema_version": "english_nightly_manifest_v1",
        "batch_id": batch_id,
        "status": status,
        "study_date": study_date,
        "capture_event_ids": event_ids,
        "uncovered_capture_event_ids": uncovered,
        "candidate_documents": candidate_documents,
        "runtime_identity_summary": runtime_summary,
        "source_snapshot": {
            "event_sha256": {event["event_id"]: object_sha256(event) for event in day_events},
            "sentence_hashes": {event["event_id"]: event.get("source", {}).get("sentence_hash") for event in day_events},
        },
        "formal_pre_hashes": formal_pre_hashes,
        "formal_write_count": 0,
        "formal_writeback": "none",
    }
    path = Path(output) if output is not None else state_dir / "nightly" / study_date / batch_id / "manifest.json"
    atomic_write_json(path, manifest)
    return path, manifest


def pipeline_status(state_dir: Path) -> dict[str, Any]:
    state_dir = Path(state_dir)
    events = load_events(state_dir)
    candidates = list((state_dir / "candidates").glob("*/*.json"))
    manifests = list((state_dir / "nightly").glob("*/*/manifest.json"))
    receipts = list((state_dir / "receipts").glob("**/*.json"))
    return {
        "schema_version": "english_pipeline_status_v1",
        "event_count": len(events),
        "candidate_count": len(candidates),
        "manifest_count": len(manifests),
        "receipt_count": len(receipts),
        "formal_write_count": 0,
    }


def validate_events_report(state_dir: Path, *, study_date: str | None = None) -> dict[str, Any]:
    events = load_events(Path(state_dir))
    if study_date is not None:
        events = [event for event in events if parse_iso_date(str(event["occurred_at"])) == study_date]
    return {
        "schema_version": "english_validate_events_report_v1",
        "status": "PASS",
        "study_date": study_date,
        "event_count": len(events),
        "event_ids": [event["event_id"] for event in events],
        "formal_write_count": 0,
    }
