"""Portable adapters for the English formal bank surface."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from .constants import MASTERED_HEADER, MASTER_HEADER, SP_FIELDS
from .util import file_sha256


FORMAL_RELATIVE_PATHS = (
    Path("bank/master_bank.csv"),
    Path("bank/mastered_items.csv"),
    Path("bank/sentence_patterns.md"),
)


def formal_hashes(repo_root: Path) -> dict[str, str | None]:
    root = Path(repo_root)
    return {
        str(relative): file_sha256(root / relative) if (root / relative).is_file() else None
        for relative in FORMAL_RELATIVE_PATHS
    }


def _read_csv(path: Path, header: list[str]) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            {key: str(row.get(key, "")) for key in header}
            for row in reader
        ]


def read_master_bank(repo_root: Path) -> list[dict[str, str]]:
    return _read_csv(Path(repo_root) / "bank/master_bank.csv", MASTER_HEADER)


def read_mastered_items(repo_root: Path) -> list[dict[str, str]]:
    return _read_csv(Path(repo_root) / "bank/mastered_items.csv", MASTERED_HEADER)


def _sentence_pattern_cards(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    cards: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in lines:
        if line.startswith("## "):
            if current is not None:
                cards.append(current)
            current = {"title": line[3:].strip()}
            continue
        if current is None or not line.startswith("- ") or "：" not in line:
            continue
        key, value = line[2:].split("：", 1)
        current[key.strip()] = value.strip()
    if current is not None:
        cards.append(current)
    return cards


def read_sentence_patterns(repo_root: Path) -> list[dict[str, Any]]:
    return _sentence_pattern_cards(Path(repo_root) / "bank/sentence_patterns.md")


def formal_snapshot(repo_root: Path) -> dict[str, Any]:
    cards = read_sentence_patterns(repo_root)
    field_count = 15 if cards else 0
    if cards:
        field_count = max(
            len(set().union(*(set(card) for card in cards))),
            len(SP_FIELDS),
        )
    return {
        "master_bank": {"row_count": len(read_master_bank(repo_root))},
        "mastered_items": {"row_count": len(read_mastered_items(repo_root))},
        "sentence_patterns": {
            "field_count": field_count,
            "card_count": len(cards),
        },
        "formal_hashes": formal_hashes(Path(repo_root)),
    }
