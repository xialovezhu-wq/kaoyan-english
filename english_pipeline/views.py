"""Read-only projections derived from immutable English capture events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .events import append_event, effective_sentence_events, load_events
from .formal import formal_hashes
from .util import atomic_write_json, atomic_write_text, file_sha256, object_sha256, parse_iso_date


def quick_capture_projection_binding(
    events: list[dict[str, Any]], *, article_id: str | None = None, study_date: str | None = None
) -> dict[str, Any]:
    effective = effective_sentence_events(
        events,
        article_id=article_id,
        study_date=study_date,
    )
    effective = sorted(effective, key=lambda event: str(event.get("event_id", "")))
    event_ids = [str(event["event_id"]) for event in effective]
    high_water = object_sha256(
        [
            {
                "event_id": event["event_id"],
                "event_sha256": object_sha256(event),
            }
            for event in effective
        ]
    )
    return {
        "schema_version": "study-intake-projection-binding-v1",
        "data_role": "projection",
        "article_id": article_id,
        "study_date": study_date,
        "effective_event_ids": event_ids,
        "effective_event_count": len(event_ids),
        "effective_event_high_water_sha256": high_water,
        "formal_write_count": 0,
    }


def _safe_learning(event: dict[str, Any]) -> list[str]:
    learning = event.get("learning", {})
    if not isinstance(learning, dict):
        return []
    source_kind = str(event.get("source", {}).get("source_kind", ""))
    answer_protection = str(learning.get("answer_protection", ""))
    if source_kind == "explanation":
        return ["受保护解析正文不在可重建视图回显"]
    result = []
    for label, key in (
        ("首译", "first_translation"),
        ("用户证据", "user_evidence_verbatim"),
        ("翻译", "translation"),
        ("首个断点", "first_breakpoint"),
        ("复述", "restatement"),
    ):
        value = learning.get(key)
        if value is not None and value != "":
            result.append(f"- {label}：{value}")
    return result


def render_quick_capture(
    events: list[dict[str, Any]], *, article_id: str | None = None, study_date: str | None = None
) -> str:
    effective = effective_sentence_events(events, article_id=article_id, study_date=study_date)
    effective = sorted(effective, key=lambda event: str(event.get("event_id", "")))
    binding = quick_capture_projection_binding(
        events,
        article_id=article_id,
        study_date=study_date,
    )
    binding_text = json.dumps(binding, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    lines = [f"<!-- study-intake-projection-binding-v1 {binding_text} -->", ""]
    if not effective:
        lines.append("暂无当前筛选范围内的句子捕获。")
        return "\n".join(lines) + "\n"
    for event in effective:
        source = event.get("source", {})
        lines.extend(
            [
                f"## {source.get('sentence_id', event.get('event_id', ''))}",
                "",
                f"事件：{event.get('event_id', '')}",
                f"来源类型：{source.get('source_kind', '')}",
            ]
        )
        if source.get("source_kind") != "explanation":
            lines.extend([f"原句：{source.get('source_sentence', '')}"])
        lines.extend(_safe_learning(event))
        candidates = event.get("candidates", [])
        if candidates:
            lines.append("候选：" + "、".join(str(row.get("item", "")) for row in candidates))
        lines.append("")
    return "\n".join(lines)


def write_quick_capture_view(
    state_dir: Path,
    *,
    article_id: str | None = None,
    study_date: str | None = None,
    output: Path | None = None,
) -> tuple[Path, str]:
    state_dir = Path(state_dir)
    events = load_events(state_dir)
    if study_date is None:
        matching = [event for event in events if event.get("event_type") in {"sentence_captured", "sentence_correction"}]
        study_date = parse_iso_date(str(matching[-1]["occurred_at"])) if matching else "unknown"
    text = render_quick_capture(events, article_id=article_id, study_date=study_date)
    path = Path(output) if output is not None else state_dir / "views" / study_date / f"{article_id or 'all'}-quick-capture.md"
    atomic_write_text(path, text)
    return path, text


def _export_candidates(events: list[dict[str, Any]], article_id: str, study_date: str) -> dict[str, Any]:
    tier_counts = {"A": 0, "B": 0, "C": 0}
    items: list[dict[str, Any]] = []
    for event in effective_sentence_events(events, article_id=article_id, study_date=study_date):
        for candidate in event.get("candidates", []):
            decision = str(candidate.get("decision", ""))
            tier = str(candidate.get("tier_hint", "C")).upper()
            if decision == "not_recommended":
                tier = "C"
            if tier not in tier_counts:
                tier = "C"
            tier_counts[tier] += 1
            items.append({**candidate, "tier": tier, "source_event_id": event["event_id"]})
    return {
        "schema_version": "english_article_export_v1",
        "source_id": article_id,
        "study_date": study_date,
        "tier_counts": tier_counts,
        "items": items,
        "formal_write_count": 0,
    }


def complete_article(
    state_dir: Path,
    repo_root: Path,
    *,
    article_id: str,
    idempotency_key: str,
    study_date: str | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    state_dir = Path(state_dir)
    repo_root = Path(repo_root)
    events = load_events(state_dir)
    effective = effective_sentence_events(events, article_id=article_id, study_date=study_date)
    if not effective:
        raise ValueError("no effective sentence captures for article")
    if study_date is None:
        study_date = parse_iso_date(str(effective[0]["occurred_at"]))
    article = dict(effective[0]["article"])
    completion = {
        "study_date": study_date,
        "effective_capture_event_ids": [event["event_id"] for event in effective],
        "capture_event_sha256": {event["event_id"]: object_sha256(event) for event in effective},
    }
    request = {
        "event_type": "article_completed",
        "idempotency_key": idempotency_key,
        "occurred_at": f"{study_date}T15:00:00Z",
        "article": article,
        "completion": completion,
    }
    receipt = append_event(state_dir, request)
    export = _export_candidates(events, article_id, study_date)
    destination = Path(output_dir) if output_dir is not None else state_dir / "exports" / study_date
    export_path = destination / f"{article_id}-abc.json"
    atomic_write_json(export_path, export)
    return {
        "schema_version": "english_article_completion_receipt_v1",
        "status": receipt.get("status", "created"),
        "completion_event_id": receipt["capture_id"],
        "source_id": article_id,
        "study_date": study_date,
        "effective_capture_event_ids": completion["effective_capture_event_ids"],
        "tier_counts": export["tier_counts"],
        "export_json": str(export_path),
        "formal_sources_unchanged": True,
        "formal_write_count": 0,
        "formal_writeback": "none",
    }
