"""Portable constants for the English pipeline.

The module deliberately derives repository paths from its own location.  No
machine-specific workspace path is part of the source closure; deployments can
override the state root through ``ENGLISH_PIPELINE_STATE_DIR`` or the CLI flag.
"""

from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_DIR = Path(
    os.environ.get("ENGLISH_PIPELINE_STATE_DIR", str(REPO_ROOT / "intake"))
).expanduser()

# User-facing evidence vocabulary.  The capture layer preserves these values;
# later review code decides how they affect selection.
EVIDENCE_STATES = frozenset(
    {
        "unknown_observed",
        "mistranslated_observed",
        "structure_trap",
        "guided_understood",
        "independent_correct_use",
        "nonreport",
    }
)
USER_EVIDENCE = frozenset(
    {
        "unknown",
        "mistranslated",
        "structure_trap",
        "guided_understood",
        "independent_correct_use",
        "nonreport",
    }
)

MASTER_HEADER = [
    "id",
    "date",
    "type",
    "item",
    "source_article",
    "source_sentence",
    "meaning",
    "usage",
    "writing_value",
    "tags",
    "review_note",
    "appear_count",
    "last_seen",
]
MASTERED_HEADER = [
    "id",
    "item",
    "matched_id",
    "matched_type",
    "mastered_date",
    "evidence_sentence",
    "evidence_context",
    "proof_note",
]

# The formal sentence-pattern surface has one heading plus these fourteen
# fields.  Keep the order stable because it is part of the append-only format.
SP_FIELDS = [
    "title",
    "骨架",
    "难度等级",
    "基本句型",
    "从句类型",
    "场景标签",
    "可复用程度",
    "中文解释",
    "结构拆解",
    "生成模板",
    "相关词汇/搭配",
    "常用变体",
    "来源与示例",
    "use_count",
    "last_used",
]
