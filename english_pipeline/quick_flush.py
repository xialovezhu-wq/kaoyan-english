from __future__ import annotations

import copy
import fcntl
import hashlib
import hmac
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping

from .errors import ValidationError
from .util import canonical_bytes, load_json, object_sha256, parse_iso_date, utc_now


QUICK_FLUSH_SCHEMA = "english_quick_flush_intent_v1"
QUICK_FLUSH_AUTHORITY_SCHEMA = "english_quick_flush_authority_v1"
QUICK_FLUSH_PURPOSE = "english-quick-flush-intent"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EVENT_ID_RE = re.compile(r"^EVT-[0-9]{8}-[A-F0-9]{16}$")


def _canonical_file_bytes(value: Mapping[str, Any]) -> bytes:
    return canonical_bytes(value) + b"\n"


def _require_owned_sealed_file(path: Path, *, error: str) -> None:
    try:
        node = path.lstat()
    except OSError as exc:
        raise ValidationError(error) from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(node.st_mode)
        or node.st_uid != os.getuid()
        or stat.S_IMODE(node.st_mode) != 0o600
    ):
        raise ValidationError(error)


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _authority_key_path(state_dir: Path) -> Path:
    return state_dir / "quick-flush" / "authority.key"


def _read_authority_key(state_dir: Path) -> bytes:
    path = _authority_key_path(state_dir)
    try:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or path.is_symlink()
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise ValidationError("quick flush authority key permissions invalid")
        value = path.read_bytes()
    except OSError as exc:
        raise ValidationError("quick flush authority key unreadable") from exc
    if len(value) != 32:
        raise ValidationError("quick flush authority key invalid")
    return value


def _authority_key(state_dir: Path) -> bytes:
    path = _authority_key_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        descriptor = -1
    if descriptor >= 0:
        try:
            key = os.urandom(32)
            os.write(descriptor, key)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    return _read_authority_key(state_dir)


def capture_receipt_identity(receipt: Mapping[str, Any]) -> dict[str, Any]:
    stages = receipt.get("stages")
    identity = {
        "schema_version": receipt.get("schema_version"),
        "receipt_id": receipt.get("receipt_id"),
        "capture_id": receipt.get("capture_id"),
        "event_path": receipt.get("event_path"),
        "event_sha256": receipt.get("event_sha256"),
        "request_sha256": receipt.get("request_sha256"),
        "formal_write_count": receipt.get("formal_write_count"),
        "formal_writeback": receipt.get("formal_writeback"),
        "supersedes_event_id": receipt.get("supersedes_event_id"),
        "stages": copy.deepcopy(stages),
    }
    if (
        identity["schema_version"] != "english_capture_receipt_v2"
        or not isinstance(identity["receipt_id"], str)
        or not EVENT_ID_RE.fullmatch(str(identity["capture_id"] or ""))
        or not isinstance(identity["event_path"], str)
        or not Path(identity["event_path"]).is_absolute()
        or not SHA256_RE.fullmatch(str(identity["event_sha256"] or ""))
        or not SHA256_RE.fullmatch(str(identity["request_sha256"] or ""))
        or identity["formal_write_count"] != 0
        or identity["formal_writeback"] != "none"
        or not isinstance(stages, Mapping)
        or stages.get("event_written") is not True
        or stages.get("schema_validated") is not True
    ):
        raise ValidationError("capture receipt cannot authorize quick flush")
    return identity


def _seal(core: Mapping[str, Any], key: bytes) -> dict[str, Any]:
    value = copy.deepcopy(dict(core))
    value.pop("authority", None)
    mac = hmac.new(
        key,
        canonical_bytes({"purpose": QUICK_FLUSH_PURPOSE, "payload": value}),
        hashlib.sha256,
    ).hexdigest()
    value["authority"] = {
        "schema_version": QUICK_FLUSH_AUTHORITY_SCHEMA,
        "algorithm": "HMAC-SHA256",
        "key_id": hashlib.sha256(key).hexdigest(),
        "purpose": QUICK_FLUSH_PURPOSE,
        "hmac_sha256": mac,
    }
    return value


def verify_quick_flush_intent(
    value: Mapping[str, Any], *, state_dir: Path, key: bytes | None = None
) -> dict[str, Any]:
    allowed = {
        "schema_version",
        "intent_id",
        "event_id",
        "event_sha256",
        "event_path",
        "capture_receipt_id",
        "capture_receipt_sha256",
        "capture_receipt_path",
        "idempotency_key",
        "request_sha256",
        "source_id",
        "study_date",
        "created_at",
        "formal_write_count",
        "formal_writeback",
        "authority",
    }
    if set(value) != allowed:
        raise ValidationError("quick flush intent fields invalid")
    authority = value.get("authority")
    core = copy.deepcopy(dict(value))
    core.pop("authority", None)
    actual_key = key if key is not None else _read_authority_key(state_dir)
    expected = hmac.new(
        actual_key,
        canonical_bytes({"purpose": QUICK_FLUSH_PURPOSE, "payload": core}),
        hashlib.sha256,
    ).hexdigest()
    if (
        value.get("schema_version") != QUICK_FLUSH_SCHEMA
        or not SHA256_RE.fullmatch(str(value.get("intent_id") or ""))
        or not EVENT_ID_RE.fullmatch(str(value.get("event_id") or ""))
        or not SHA256_RE.fullmatch(str(value.get("event_sha256") or ""))
        or not isinstance(value.get("event_path"), str)
        or not Path(str(value["event_path"])).is_absolute()
        or not isinstance(value.get("capture_receipt_id"), str)
        or not SHA256_RE.fullmatch(
            str(value.get("capture_receipt_sha256") or "")
        )
        or not isinstance(value.get("capture_receipt_path"), str)
        or not Path(str(value["capture_receipt_path"])).is_absolute()
        or not isinstance(value.get("idempotency_key"), str)
        or not str(value["idempotency_key"]).strip()
        or not SHA256_RE.fullmatch(str(value.get("request_sha256") or ""))
        or not isinstance(value.get("source_id"), str)
        or not str(value["source_id"]).strip()
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value.get("study_date") or ""))
        or not isinstance(value.get("created_at"), str)
        or value.get("formal_write_count") != 0
        or value.get("formal_writeback") != "none"
        or not isinstance(authority, Mapping)
        or set(authority)
        != {"schema_version", "algorithm", "key_id", "purpose", "hmac_sha256"}
        or authority.get("schema_version") != QUICK_FLUSH_AUTHORITY_SCHEMA
        or authority.get("algorithm") != "HMAC-SHA256"
        or authority.get("key_id") != hashlib.sha256(actual_key).hexdigest()
        or authority.get("purpose") != QUICK_FLUSH_PURPOSE
        or not hmac.compare_digest(str(authority.get("hmac_sha256") or ""), expected)
    ):
        raise ValidationError("quick flush intent invalid")
    try:
        created_at = datetime.fromisoformat(
            str(value["created_at"]).replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValidationError("quick flush intent created_at invalid") from exc
    if created_at.tzinfo is None:
        raise ValidationError("quick flush intent created_at invalid")
    identity = {
        key_name: core[key_name]
        for key_name in (
            "event_id",
            "event_sha256",
            "capture_receipt_id",
            "capture_receipt_sha256",
            "idempotency_key",
            "request_sha256",
            "source_id",
            "study_date",
        )
    }
    if value.get("intent_id") != object_sha256(identity):
        raise ValidationError("quick flush intent identity invalid")
    return copy.deepcopy(dict(value))


def _publish_content_addressed(root: Path, value: Mapping[str, Any]) -> tuple[str, Path]:
    payload = _canonical_file_bytes(value)
    digest = hashlib.sha256(payload).hexdigest()
    path = root / "sha256" / digest[:2] / f"{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _require_owned_sealed_file(
            path, error="quick flush intent content address conflict"
        )
        if path.read_bytes() != payload:
            raise ValidationError("quick flush intent content address conflict")
        return digest, path
    descriptor, temporary = tempfile.mkstemp(prefix=f".{digest}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        try:
            os.link(temporary, path)
        except FileExistsError:
            _require_owned_sealed_file(
                path, error="quick flush intent content address conflict"
            )
            if path.read_bytes() != payload:
                raise ValidationError("quick flush intent content address conflict")
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return digest, path


def publish_quick_flush_intent(
    state_dir: Path,
    *,
    event: Mapping[str, Any],
    capture_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    state_dir = state_dir.resolve()
    event_id = str(event.get("event_id") or "")
    event_path = Path(str(capture_receipt.get("event_path") or "")).resolve()
    receipt_path = Path(str(capture_receipt.get("receipt_path") or "")).resolve()
    receipt_identity = capture_receipt_identity(capture_receipt)
    event_sha256 = object_sha256(event)
    receipt_sha256 = object_sha256(receipt_identity)
    try:
        event_path.relative_to((state_dir / "events").resolve())
        receipt_path.relative_to((state_dir / "receipts" / "capture").resolve())
    except ValueError as exc:
        raise ValidationError("quick flush source path invalid") from exc
    try:
        persisted_receipt = load_json(receipt_path)
    except (OSError, ValueError) as exc:
        raise ValidationError("quick flush capture receipt unreadable") from exc
    _require_owned_sealed_file(
        event_path, error="quick flush source binding invalid"
    )
    _require_owned_sealed_file(
        receipt_path, error="quick flush source binding invalid"
    )
    if (
        not EVENT_ID_RE.fullmatch(event_id)
        or event.get("event_type")
        not in {"sentence_captured", "sentence_correction"}
        or capture_receipt.get("capture_id") != event_id
        or capture_receipt.get("event_sha256") != event_sha256
        or capture_receipt.get("request_sha256") != event.get("request_sha256")
        or load_json(event_path) != dict(event)
        or capture_receipt_identity(persisted_receipt) != receipt_identity
    ):
        raise ValidationError("quick flush source binding invalid")
    study_date = parse_iso_date(str(event.get("occurred_at") or ""))
    identity = {
        "event_id": event_id,
        "event_sha256": event_sha256,
        "capture_receipt_id": capture_receipt["receipt_id"],
        "capture_receipt_sha256": receipt_sha256,
        "idempotency_key": event["idempotency_key"],
        "request_sha256": event["request_sha256"],
        "source_id": event["article"]["source_id"],
        "study_date": study_date,
    }
    intent_id = object_sha256(identity)
    root = state_dir / "quick-flush" / "intents"
    with _lock(state_dir / "quick-flush" / "quick-flush.lock"):
        matches: list[tuple[dict[str, Any], str, Path]] = []
        if root.is_dir():
            for path in sorted(root.glob("sha256/*/*.json")):
                _require_owned_sealed_file(
                    path, error="quick flush intent hash mismatch"
                )
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                if digest != path.stem:
                    raise ValidationError("quick flush intent hash mismatch")
                loaded = json.loads(raw)
                verified = verify_quick_flush_intent(loaded, state_dir=state_dir)
                if verified["event_id"] == event_id:
                    matches.append((verified, digest, path))
        if matches:
            if len(matches) != 1 or matches[0][0]["intent_id"] != intent_id:
                raise ValidationError("quick flush intent conflict")
            intent, digest, path = matches[0]
            return {
                "schema_version": "english_quick_flush_receipt_v1",
                "status": "idempotent_noop",
                "intent_id": intent_id,
                "intent_sha256": digest,
                "intent_path": str(path),
                "event_id": event_id,
                "event_sha256": event_sha256,
                "capture_receipt_sha256": receipt_sha256,
                "formal_write_count": 0,
                "formal_writeback": "none",
            }
        key = _authority_key(state_dir)
        intent = _seal(
            {
                "schema_version": QUICK_FLUSH_SCHEMA,
                "intent_id": intent_id,
                "event_id": event_id,
                "event_sha256": event_sha256,
                "event_path": str(event_path),
                "capture_receipt_id": capture_receipt["receipt_id"],
                "capture_receipt_sha256": receipt_sha256,
                "capture_receipt_path": str(receipt_path),
                "idempotency_key": event["idempotency_key"],
                "request_sha256": event["request_sha256"],
                "source_id": event["article"]["source_id"],
                "study_date": study_date,
                "created_at": utc_now(),
                "formal_write_count": 0,
                "formal_writeback": "none",
            },
            key,
        )
        verify_quick_flush_intent(intent, state_dir=state_dir, key=key)
        digest, path = _publish_content_addressed(root, intent)
        return {
            "schema_version": "english_quick_flush_receipt_v1",
            "status": "created",
            "intent_id": intent_id,
            "intent_sha256": digest,
            "intent_path": str(path),
            "event_id": event_id,
            "event_sha256": event_sha256,
            "capture_receipt_sha256": receipt_sha256,
            "formal_write_count": 0,
            "formal_writeback": "none",
        }
