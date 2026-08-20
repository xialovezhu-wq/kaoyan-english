"""Proposal-only review status helpers.

The foreground capture remains immutable.  These functions only derive
selector proposals or append a separate status record; they never mutate the
formal vocabulary bank.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from .util import object_sha256, parse_iso_date


def canonical_machine_decision(value: str) -> str:
    aliases = {
        "long_term": "long_term_candidate",
        "long-term": "long_term_candidate",
        "bbdc": "bbdc_candidate",
        "article": "article_only",
        "not-recommended": "not_recommended",
    }
    normalized = str(value or "").strip().casefold()
    return aliases.get(normalized, normalized)


def exact_item_occurrences(text: str, item: str) -> list[dict[str, Any]]:
    """Find exact token/phrase occurrences without substring false positives."""

    source = str(text)
    needle = str(item).strip()
    if not needle:
        return []
    escaped = re.escape(needle)
    ascii_word = bool(re.fullmatch(r"[A-Za-z0-9_]+(?:[ '\u2019-][A-Za-z0-9_]+)*", needle))
    if ascii_word:
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])", re.IGNORECASE)
    else:
        pattern = re.compile(escaped, re.IGNORECASE)
    return [
        {"start": match.start(), "end": match.end(), "surface_form": match.group(0)}
        for match in pattern.finditer(source)
    ]


def append_review_status_record(
    records: list[dict[str, Any]],
    *,
    event_type: str,
    item: str,
    bank_id: str,
    study_date: str,
    source_capture_event_ids: list[str],
    sentence_evidence: list[dict[str, Any]],
    reason: str,
) -> dict[str, Any]:
    if event_type not in {"exclude_from_review", "reactivate_for_review"}:
        raise ValueError(f"unsupported review status event type: {event_type}")
    record = {
        "schema_version": "english_review_status_v1",
        "status_event_id": "RS-" + object_sha256(
            {
                "event_type": event_type,
                "item": item,
                "bank_id": bank_id,
                "study_date": study_date,
                "source_capture_event_ids": source_capture_event_ids,
                "sentence_evidence": sentence_evidence,
                "reason": reason,
            }
        )[:16].upper(),
        "event_type": event_type,
        "item": item,
        "bank_id": bank_id,
        "study_date": study_date,
        "source_capture_event_ids": list(source_capture_event_ids),
        "sentence_evidence": sentence_evidence,
        "reason": reason,
    }
    records.append(record)
    return record


def effective_review_status(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    effective: dict[str, dict[str, Any]] = {}
    for record in records:
        item = str(record.get("item", "")).strip()
        if not item:
            continue
        event_type = record.get("event_type")
        if event_type == "exclude_from_review":
            status = "excluded_from_review"
        elif event_type == "reactivate_for_review":
            status = "unmastered_reactivated"
        else:
            continue
        effective[item] = {**record, "status": status}
    return effective


def eligible_review_bank_rows(
    bank_rows: list[dict[str, Any]], records: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    statuses = effective_review_status(records)
    return [
        row
        for row in bank_rows
        if str(row.get("item", "")).strip() not in statuses
        or statuses[str(row.get("item", "")).strip()].get("status") != "excluded_from_review"
    ]


def _event_terms(event: dict[str, Any]) -> set[str]:
    terms: set[str] = set()
    for candidate in event.get("candidates", []):
        if isinstance(candidate, dict) and str(candidate.get("item", "")).strip():
            terms.add(str(candidate["item"]).strip())
    learning = event.get("learning", {})
    if isinstance(learning, dict):
        breakpoint = str(learning.get("first_breakpoint", "")).strip()
        if breakpoint:
            terms.add(breakpoint)
    return terms


def _explicit_unknown(event: dict[str, Any]) -> bool:
    learning = event.get("learning", {})
    if not isinstance(learning, dict):
        return False
    states = set(learning.get("evidence_states", []))
    evidence = set(learning.get("user_evidence", []))
    return bool(
        states & {"unknown_observed", "mistranslated_observed"}
        or evidence & {"unknown", "mistranslated"}
    )


def build_review_status_proposals(
    events: list[dict[str, Any]],
    bank_rows: list[dict[str, Any]],
    *,
    study_date: str,
    current_status: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    bank_by_item = {str(row.get("item", "")).strip(): row for row in bank_rows}
    same_day = [
        event
        for event in events
        if event.get("event_type") in {"sentence_captured", "sentence_correction"}
        and parse_iso_date(str(event.get("occurred_at"))) == study_date
    ]
    unknown_terms: list[str] = []
    explicit_events: dict[str, list[dict[str, Any]]] = {}
    for event in same_day:
        if not _explicit_unknown(event):
            continue
        for item in _event_terms(event):
            if item in bank_by_item and item not in unknown_terms:
                unknown_terms.append(item)
            explicit_events.setdefault(item, []).append(event)

    exclusion_proposals: list[dict[str, Any]] = []
    # A non-report by itself is intentionally not enough to produce an
    # exclusion when the same day contains an explicit unknown signal.
    for event in same_day:
        learning = event.get("learning", {})
        if not isinstance(learning, dict) or _explicit_unknown(event):
            continue
        if "nonreport" not in set(learning.get("evidence_states", [])) and "nonreport" not in set(learning.get("user_evidence", [])):
            continue
        sentence = str(event.get("source", {}).get("source_sentence", ""))
        for item, row in bank_by_item.items():
            if item in unknown_terms or not exact_item_occurrences(sentence, item):
                continue
            exclusion_proposals.append(
                {
                    "item": item,
                    "bank_id": row.get("id", ""),
                    "reason": "appeared_in_sentence_but_not_reported_unknown",
                    "source_capture_event_ids": [event.get("event_id")],
                }
            )

    reactivation: list[dict[str, Any]] = []
    for item, status in (current_status or {}).items():
        if item in explicit_events:
            reactivation.append(
                {
                    "item": item,
                    "reason": "explicit_unknown_or_mistranslated_after_mastery",
                    "source_capture_event_ids": [
                        event.get("event_id") for event in explicit_events[item]
                    ],
                }
            )

    return {
        "study_date": study_date,
        "daily_explicit_unknown_terms": unknown_terms,
        "review_exclusion_proposals": exclusion_proposals,
        "reactivation_proposals": reactivation,
    }
