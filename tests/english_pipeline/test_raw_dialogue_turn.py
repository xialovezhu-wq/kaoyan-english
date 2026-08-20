from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from english_pipeline.cli import main as cli_main
from english_pipeline.constants import RAW_DIALOGUE_EVENT_TYPE
from english_pipeline.errors import IdempotencyConflict, ValidationError
from english_pipeline.events import (
    SimulatedCaptureCrash,
    append_derived_sentence_event,
    append_raw_dialogue_turn,
    load_events,
)


def raw_request(*, key: str = "synthetic-raw-1", status: str = "resolved") -> dict:
    digest = hashlib.sha256(b"synthetic attachment bytes").hexdigest()
    return {
        "event_type": RAW_DIALOGUE_EVENT_TYPE,
        "idempotency_key": key,
        "occurred_at": "2026-08-20T10:02:00Z",
        "messages": [
            {
                "role": "user",
                "message_id": "synthetic-user-1",
                "timestamp": "2026-08-20T10:00:00Z",
                "content": "Synthetic first user message.",
            },
            {
                "role": "user",
                "message_id": "synthetic-user-2",
                "timestamp": "2026-08-20T10:01:00Z",
                "content": "Synthetic second user message.",
            },
            {
                "role": "assistant",
                "message_id": "synthetic-assistant-1",
                "timestamp": "2026-08-20T10:02:00Z",
                "content": "Synthetic complete assistant reply.",
                "complete": True,
            },
        ],
        "attachments": [
            {
                "attachment_id": "synthetic-attachment-1",
                "message_id": "synthetic-user-2",
                "metadata": {"mime_type": "image/png", "byte_length": 26},
                "sha256": digest,
                "durable_ref": "synthetic://attachments/sha256/" + digest,
            }
        ],
        "context_identity": {
            "conversation_id": "synthetic-conversation",
            "thread_id": "synthetic-thread",
            "workspace_id": "synthetic-workspace",
            "assistant_context_id": "synthetic-assistant-context",
        },
        "resolution_status": status,
    }


def sentence_request(*, key: str = "synthetic-sentence-1") -> dict:
    return {
        "event_type": "sentence_captured",
        "idempotency_key": key,
        "occurred_at": "2026-08-20T10:03:00Z",
        "article": {
            "article_id": "SYNTHETIC-ARTICLE",
            "source_id": "SYNTHETIC-ARTICLE",
            "source_article": "fixtures/synthetic.md",
            "source_hash": "a" * 64,
        },
        "source": {
            "sentence_id": "S01",
            "source_sentence": "Synthetic sentence.",
            "source_kind": "article",
        },
        "learning": {
            "first_translation": None,
            "user_evidence_verbatim": None,
            "evidence_states": [],
            "evidence_origin": "synthetic_fixture",
            "user_evidence": [],
            "answer_protection": "practice_safe",
            "hint_level": 0,
            "translation": "",
            "explanation": "",
            "first_breakpoint": "",
            "restatement": "",
        },
        "candidates": [],
    }


class RawDialogueTurnTests(unittest.TestCase):
    def test_active_schema_declares_raw_turn_and_sentence_parent_boundary(self) -> None:
        schema = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "schema/english_pipeline/capture-event-v2.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIn(
            RAW_DIALOGUE_EVENT_TYPE,
            schema["properties"]["event_type"]["enum"],
        )
        sentence_rule = schema["allOf"][0]["then"]["required"]
        self.assertIn("parent_raw_capture_id", sentence_rule)
        self.assertFalse(schema["additionalProperties"])

    def test_resolved_and_unresolved_turns_preserve_order_content_and_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state = Path(raw) / "intake"
            append_raw_dialogue_turn(state, raw_request())
            append_raw_dialogue_turn(
                state, raw_request(key="synthetic-raw-2", status="unresolved")
            )
            events = load_events(state)
            self.assertEqual(len(events), 2)
            self.assertEqual(
                [message["role"] for message in events[0]["messages"]],
                ["user", "user", "assistant"],
            )
            self.assertEqual(
                events[0]["messages"][1]["content"],
                "Synthetic second user message.",
            )
            self.assertEqual(events[0]["attachments"][0]["message_id"], "synthetic-user-2")
            self.assertEqual(events[1]["resolution_status"], "unresolved")
            self.assertEqual(events[0]["formal_write_count"], 0)

    def test_crash_retry_is_idempotent_and_conflicting_content_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state = Path(raw) / "intake"
            request = raw_request()
            with self.assertRaises(SimulatedCaptureCrash):
                append_raw_dialogue_turn(state, request, fault_after_event=True)
            replay = append_raw_dialogue_turn(state, request)
            self.assertEqual(replay["status"], "idempotent_noop")
            self.assertEqual(len(load_events(state)), 1)
            changed = deepcopy(request)
            changed["messages"][0]["content"] = "Synthetic changed content."
            with self.assertRaises(IdempotencyConflict):
                append_raw_dialogue_turn(state, changed)

    def test_sentence_derivation_requires_parent_and_parse_failure_keeps_raw(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state = Path(raw) / "intake"
            receipt = append_raw_dialogue_turn(
                state,
                raw_request(),
                sentence_parser=lambda _event: (_ for _ in ()).throw(
                    ValueError("synthetic parse failure")
                ),
            )
            self.assertEqual(receipt["sentence_derivation_status"], "failed")
            self.assertEqual(len(load_events(state)), 1)
            derived = append_derived_sentence_event(
                state,
                sentence_request(),
                parent_raw_capture_id=receipt["capture_id"],
            )
            self.assertEqual(derived["status"], "created")
            with self.assertRaisesRegex(ValidationError, "durable raw dialogue"):
                append_derived_sentence_event(
                    state,
                    sentence_request(key="missing-parent"),
                    parent_raw_capture_id="EVT-20260820-0000000000000000",
                )

    def test_cli_uses_same_event_store_without_queue_or_model_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            request_path = root / "raw-turn.json"
            request_path.write_text(
                json.dumps(raw_request(), ensure_ascii=False), encoding="utf-8"
            )
            state = root / "intake"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = cli_main(
                    [
                        "capture-raw-turn",
                        "--repo-root",
                        str(root),
                        "--state-dir",
                        str(state),
                        "--input-json",
                        str(request_path),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["formal_write_count"], 0)
            self.assertEqual(len(load_events(state)), 1)
            self.assertFalse((state / "quick-flush").exists())


if __name__ == "__main__":
    unittest.main()
