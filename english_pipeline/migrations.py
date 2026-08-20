"""Read-only validation for explicitly recorded event-v2 migrations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import ValidationError
from .util import file_sha256, object_sha256


def validate_migration_receipt(
    receipt: dict[str, Any], *, source_event: dict[str, Any], source_path: Path
) -> dict[str, Any]:
    """Validate a migration receipt before exposing its derived event.

    Migration receipts are never inferred.  They must bind the immutable source
    bytes and identify the source event explicitly; the returned object is a
    shallow v2 view used only for read compatibility.
    """

    required = {
        "migration_id",
        "source_event_id",
        "source_event_sha256",
        "target_schema_version",
    }
    if not isinstance(receipt, dict) or not required.issubset(receipt):
        raise ValidationError("migration receipt is incomplete")
    if receipt.get("source_event_id") != source_event.get("event_id"):
        raise ValidationError("migration source event mismatch")
    if receipt.get("source_event_sha256") != file_sha256(Path(source_path)):
        raise ValidationError("migration source hash mismatch")
    if receipt.get("target_schema_version") != "english_capture_event_v2":
        raise ValidationError("migration target schema mismatch")
    derived = dict(source_event)
    derived["schema_version"] = "english_capture_event_v2"
    if "observed_signals" not in derived:
        derived["observed_signals"] = []
        derived["source_signal_ids"] = []
        derived["capture_coverage"] = {
            "schema_version": "english_capture_coverage_v2",
            "declared_signal_count": 0,
            "covered_signal_count": 0,
            "signals": [],
        }
    return derived
