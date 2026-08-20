"""Validation and rendering for proposal-only Luna English candidates."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .events import load_events
from .util import atomic_write_text, file_sha256, object_sha256, parse_iso_date


_CANDIDATE_ID = re.compile(r"^LUNA-[0-9]{8}-[A-Za-z0-9-]+$")


def _runtime_identity_status(candidate: dict[str, Any]) -> str:
    identity = candidate.get("runtime_identity")
    if not isinstance(identity, dict):
        raise ValidationError("candidate runtime_identity is required")
    status = str(identity.get("status", ""))
    if status not in {"confirmed", "requested_unverified", "mismatch", "unavailable"}:
        raise ValidationError("candidate runtime identity status is invalid")
    requested = identity.get("requested", {})
    observed = identity.get("observed", {})
    if status == "confirmed":
        if requested != observed:
            raise ValidationError("runtime identity mismatch")
    if status == "mismatch" and candidate.get("validation", {}).get("status") != "BLOCKED":
        raise ValidationError("runtime identity mismatch")
    if status == "unavailable" and candidate.get("validation", {}).get("status") != "BLOCKED":
        raise ValidationError("runtime identity unavailable")
    return status


def _validate_item(item: dict[str, Any], events_by_id: dict[str, dict[str, Any]]) -> None:
    required = {
        "item_id",
        "sequence",
        "item",
        "candidate_status",
        "source_event_id",
        "source_article",
        "source_kind",
        "source_sentence",
        "article_source_hash",
        "sentence_hash",
        "evidence_states",
        "evidence_origin",
    }
    missing = sorted(required - set(item))
    if missing:
        raise ValidationError(f"candidate item missing fields: {missing}")
    event_id = str(item["source_event_id"])
    event = events_by_id.get(event_id)
    if event is None:
        raise ValidationError(f"candidate source event not found: {event_id}")
    if item["article_source_hash"] != event.get("article", {}).get("source_hash"):
        raise ValidationError("candidate article source hash mismatch")
    if item["sentence_hash"] != event.get("source", {}).get("sentence_hash"):
        raise ValidationError("candidate sentence hash mismatch")
    if item["source_sentence"] != event.get("source", {}).get("source_sentence"):
        raise ValidationError("candidate source sentence mismatch")
    if item.get("candidate_status") == "mastery_candidate":
        proposal = item.get("mastery_proposal")
        states = set(item.get("evidence_states", []))
        if not isinstance(proposal, dict) or "independent_correct_use" not in states:
            raise ValidationError("mastery candidate lacks independent evidence")
        if item.get("evidence_origin") != "live_user":
            raise ValidationError("mastery evidence must be live user evidence")


def validate_luna_candidate(
    candidate: dict[str, Any], *, state_dir: Path | None = None
) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise ValidationError("candidate must be an object")
    if candidate.get("schema_version") != "english_luna_candidate_v1":
        raise ValidationError("candidate schema_version mismatch")
    candidate_id = str(candidate.get("candidate_id", ""))
    if not _CANDIDATE_ID.fullmatch(candidate_id):
        raise ValidationError("candidate_id is invalid")
    study_date = str(candidate.get("study_date", ""))
    try:
        if parse_iso_date(study_date) != study_date:
            raise ValidationError("candidate study_date must be an ISO date")
    except ValueError as exc:
        raise ValidationError("candidate study_date is invalid") from exc
    source_id = str(candidate.get("source_id", ""))
    if not source_id or candidate.get("article_id") != source_id:
        raise ValidationError("candidate source identity is invalid")
    if not isinstance(candidate.get("items"), list):
        raise ValidationError("candidate items must be a list")
    validation = candidate.get("validation")
    if not isinstance(validation, dict) or validation.get("status") not in {"PASS", "BLOCKED"}:
        raise ValidationError("candidate validation status is invalid")
    runtime_status = _runtime_identity_status(candidate)

    events_by_id: dict[str, dict[str, Any]] = {}
    if state_dir is not None:
        events_by_id = {str(event["event_id"]): event for event in load_events(state_dir)}
        event_ids = [str(value) for value in candidate.get("capture_event_ids", [])]
        if not event_ids:
            raise ValidationError("candidate must bind at least one capture event")
        for event_id in event_ids:
            event = events_by_id.get(event_id)
            if event is None:
                raise ValidationError(f"candidate capture event not found: {event_id}")
            if parse_iso_date(str(event["occurred_at"])) != study_date:
                raise ValidationError("candidate crosses the Asia/Shanghai study date")
            expected = candidate.get("capture_event_sha256", {}).get(event_id)
            if expected != object_sha256(event):
                raise ValidationError("candidate capture event hash mismatch")
        if candidate.get("article_source_hash"):
            for event_id in event_ids:
                if candidate["article_source_hash"] != events_by_id[event_id]["article"]["source_hash"]:
                    raise ValidationError("candidate article source hash mismatch")

    for item in candidate["items"]:
        if not isinstance(item, dict):
            raise ValidationError("candidate item must be an object")
        if state_dir is not None:
            _validate_item(item, events_by_id)

    result = dict(candidate)
    result["item_count"] = len(candidate["items"])
    result["runtime_identity_status"] = runtime_status
    return result


def _format_value(value: Any) -> str:
    if isinstance(value, list):
        return "；".join(_format_value(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def render_luna_candidate(candidate: dict[str, Any]) -> str:
    """Render a stable, answer-safe lasting-style review document."""

    lines = [
        f"# {candidate.get('source_id', '')} Luna 候选",
        "",
        f"study_date: {candidate.get('study_date', '')}",
        f"candidate_id: {candidate.get('candidate_id', '')}",
        "",
    ]
    for item in candidate.get("items", []):
        lines.extend(
            [
                f"## {item.get('item', '')}",
                "",
                f"- 类型：{item.get('candidate_type', '')}",
                f"- 状态：{item.get('candidate_status', '')}",
                f"- 层级：{item.get('tier', item.get('tier_hint', ''))}",
                f"- 来源句：{item.get('source_sentence', '')}",
                f"- 证据状态：{_format_value(item.get('evidence_states', []))}",
                f"- 释义：{item.get('card', {}).get('meaning', item.get('meaning', ''))}",
                f"- 用法：{item.get('card', {}).get('usage', item.get('usage', ''))}",
                f"- 复习提示：{item.get('card', {}).get('review_note', item.get('review_note', ''))}",
                "",
            ]
        )
    return "\n".join(lines)


def validate_luna_candidate_file(
    path: Path, *, state_dir: Path | None = None
) -> dict[str, Any]:
    candidate = json.loads(Path(path).read_text(encoding="utf-8"))
    result = validate_luna_candidate(candidate, state_dir=state_dir)
    return {
        "schema_version": "english_candidate_validation_receipt_v1",
        "status": "PASS" if result.get("validation", {}).get("status") == "PASS" else "BLOCKED",
        "candidate_id": result["candidate_id"],
        "item_count": result["item_count"],
        "runtime_identity_status": result["runtime_identity_status"],
        "formal_write_count": 0,
    }


def render_luna_candidate_file(path: Path, output: Path | None = None) -> tuple[Path | None, str]:
    candidate = json.loads(Path(path).read_text(encoding="utf-8"))
    text = render_luna_candidate(candidate)
    if output is None:
        return None, text
    atomic_write_text(Path(output), text)
    return Path(output), text
