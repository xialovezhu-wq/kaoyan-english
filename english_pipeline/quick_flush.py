"""Signed, event-bound immediate microbatch intents.

Quick flush is an intent handoff only.  It never performs a formal write and
does not change the ordinary background batching policy.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .util import atomic_write_json, canonical_bytes, file_sha256, object_sha256, utc_now


def _authority_key(state_dir: Path) -> Path:
    path = Path(state_dir) / "quick-flush" / "authority.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or not path.is_file() or len(path.read_bytes()) != 32:
            raise ValidationError("quick flush authority key is invalid")
        os.chmod(path, 0o600)
        return path
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, secrets.token_bytes(32))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path


def _hmac_payload(intent: dict[str, Any]) -> bytes:
    unsigned = json.loads(json.dumps(intent, ensure_ascii=False))
    authority = unsigned.get("authority")
    if isinstance(authority, dict):
        authority["hmac_sha256"] = ""
    return canonical_bytes(unsigned)


def _intent_digest(intent: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(intent)).hexdigest()


def verify_quick_flush_intent(intent: dict[str, Any], *, state_dir: Path) -> dict[str, Any]:
    if not isinstance(intent, dict):
        raise ValidationError("quick flush intent must be an object")
    required = {
        "schema_version",
        "intent_id",
        "event_id",
        "event_sha256",
        "capture_receipt_id",
        "source_id",
        "created_at",
        "formal_write_count",
        "formal_writeback",
        "authority",
    }
    if set(intent) != required:
        raise ValidationError("quick flush intent fields do not match schema")
    if intent.get("schema_version") != "english_quick_flush_intent_v1":
        raise ValidationError("quick flush intent schema_version mismatch")
    if intent.get("formal_write_count") != 0 or intent.get("formal_writeback") != "none":
        raise ValidationError("quick flush intent must have zero formal writes")
    if not isinstance(intent.get("authority"), dict):
        raise ValidationError("quick flush authority is missing")
    authority = intent["authority"]
    if authority.get("algorithm") != "HMAC-SHA256" or not isinstance(authority.get("hmac_sha256"), str):
        raise ValidationError("quick flush authority metadata is invalid")
    key = _authority_key(Path(state_dir)).read_bytes()
    expected = hmac.new(key, _hmac_payload(intent), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, authority["hmac_sha256"]):
        raise ValidationError("quick flush intent HMAC mismatch")
    if not isinstance(intent.get("event_sha256"), str) or len(intent["event_sha256"]) != 64:
        raise ValidationError("quick flush event hash is invalid")
    return intent


def publish_quick_flush_intent(
    state_dir: Path, *, event: dict[str, Any], capture_receipt: dict[str, Any]
) -> dict[str, Any]:
    state_dir = Path(state_dir).resolve()
    event_hash = object_sha256(event)
    if capture_receipt.get("capture_id") != event.get("event_id"):
        raise ValidationError("quick flush receipt does not bind event")
    if capture_receipt.get("event_sha256") != event_hash:
        raise ValidationError("quick flush receipt event hash mismatch")
    if capture_receipt.get("formal_write_count") != 0:
        raise ValidationError("quick flush requires zero formal writes")

    root = state_dir / "quick-flush" / "intents"
    root.mkdir(parents=True, exist_ok=True)
    existing: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(root.glob("*/*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("event_id") == event.get("event_id"):
            existing.append((path, value))
    if existing:
        if any(value.get("event_sha256") != event_hash for _, value in existing):
            raise ValidationError("quick flush event is bound to conflicting intent")
        for _, value in existing:
            verify_quick_flush_intent(value, state_dir=state_dir)
        if len(existing) > 1:
            raise ValidationError("quick flush event has duplicate intents")
        return {
            "schema_version": "english_quick_flush_receipt_v1",
            "status": "idempotent_noop",
            "event_id": event["event_id"],
            "intent_id": existing[0][1]["intent_id"],
            "intent_path": str(existing[0][0]),
            "intent_sha256": file_sha256(existing[0][0]),
            "formal_write_count": 0,
            "formal_writeback": "none",
        }

    authority_key_path = _authority_key(state_dir)
    created_at = utc_now()
    intent_id = "QF-" + event["event_id"][4:]
    intent: dict[str, Any] = {
        "schema_version": "english_quick_flush_intent_v1",
        "intent_id": intent_id,
        "event_id": event["event_id"],
        "event_sha256": event_hash,
        "capture_receipt_id": capture_receipt.get("receipt_id"),
        "source_id": event.get("article", {}).get("source_id"),
        "created_at": created_at,
        "formal_write_count": 0,
        "formal_writeback": "none",
        "authority": {
            "algorithm": "HMAC-SHA256",
            "key_id": "local-quick-flush-v1",
            "hmac_sha256": "",
        },
    }
    intent["authority"]["hmac_sha256"] = hmac.new(
        authority_key_path.read_bytes(), _hmac_payload(intent), hashlib.sha256
    ).hexdigest()
    digest = _intent_digest(intent)
    path = root / digest[:2] / f"{digest}.json"
    atomic_write_json(path, intent)
    os.chmod(path, 0o600)
    return {
        "schema_version": "english_quick_flush_receipt_v1",
        "status": "created",
        "event_id": event["event_id"],
        "intent_id": intent_id,
        "intent_path": str(path),
        "intent_sha256": file_sha256(path),
        "formal_write_count": 0,
        "formal_writeback": "none",
    }
