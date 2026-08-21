"""Verify the frozen historical English source-closure manifest.

This standalone utility is not imported by the English runtime.  Canonical mode
never reads the historical root.  External mode reads only the manifest's
ordered fixed paths after the caller supplies --source-root explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "study-intake-historical-source-closure-v1"
SUBJECT = "english"
EXPECTED_BUNDLE_SHA256 = (
    "ca3e027286f3cc32e2fbb4c8f365d281fa4763f9987a70bf0690f3d26a86a356"
)
EXPECTED_FILE_COUNT = 20
EXPECTED_TOTAL_BYTES = 251077
ALLOWED_CLASSIFICATIONS = (
    "restore_required",
    "evidence_only",
    "replaced_by_current",
    "reject_private_or_runtime",
)
ALGORITHM_SPEC: dict[str, str] = {
    "name": "sha256-file-lines-v1",
    "file_bytes": (
        "Read each file as raw bytes; do not normalize, decode, or re-encode "
        "file contents."
    ),
    "record": "<file_sha256><two spaces><repo-relative-path><LF>",
    "aggregate": (
        "SHA-256 of the UTF-8 bytes of all records concatenated in "
        "ordered_paths order."
    ),
    "ordering": "Use ordered_paths exactly; do not sort or repackage.",
}
EXPECTED_ROWS: tuple[tuple[str, str, int], ...] = (
    ("english_pipeline/__init__.py", "c8ad28fd24a00652e7b93db1be9c514cd2a94b26cfd7c3f30ed68e004d94fdc5", 165),
    ("english_pipeline/candidates.py", "e7b919cc02fb94fdbf186905c6a5a55670d7a00a2156fe56b925748facfb5cec", 29261),
    ("english_pipeline/constants.py", "4da68734e169c8967145f6b9486991edc744431a8384033d6b58aeabbe031d8e", 1599),
    ("english_pipeline/errors.py", "b7bbac217af7a72e0fb768139fd9ba1286a0060b6d5549c6bba3a0a8ad18ea43", 352),
    ("english_pipeline/formal.py", "96b3236b0c549e02cfd00962c279efa5146a9c36c71dc027c755eaab63fcfaad", 3814),
    ("english_pipeline/migrations.py", "99a9baab167c65305d6c8a013360fb71219fac8995ff6edd3729dc4064b3849b", 6070),
    ("english_pipeline/nightly.py", "ae2a22a72f30af5daf3a802a32edc4c750fbe0cd2c169f015fa48b974beaec3a", 10542),
    ("english_pipeline/quick_flush.py", "70b3bbcd9c7c4966755267d9479ec341a1eb0ed333d74e8931975174aa33ee91", 15368),
    ("english_pipeline/review_status.py", "fe79ddf97a8222f40e8e9339d8999dfc81388a1f95a5aca8a1145ac64dce59b2", 14761),
    ("english_pipeline/util.py", "837814cffa1012414a7d6d9647895365cea34b821fbb2f85e38afc5006adffbf", 2930),
    ("english_pipeline/views.py", "86c6ddb1bf98cd6df39bc5439795eb2631aeef1f48409b568c18a8866c58a13e", 14675),
    ("english_pipeline/writer.py", "4aa66bfd4607df8e7035405a89a4bb5e071a49573a4f5baafc6d4f76de91f8aa", 44179),
    ("scripts/build_old_word_memory_curve_index.py", "31ea428453b54260e2b82226d883476fd30dcbef82630e6763ca3fe6309a7177", 18937),
    ("scripts/build_review_status_proposals.py", "ee2ee556a40f0dd6dee3f170add94f977b1715d5800c23dffd2c78550ef3002e", 2768),
    ("scripts/select_bbdc_foundation.py", "e21e5e082e0a640c38fd406f0d06db3fe3e76111db37da793b716b03a4bb0745", 48183),
    ("schema/english_pipeline/luna-candidate-v2.schema.json", "986ad5de45dc2004e58d157c5526fda99d9ef76dd86709494e89972671340892", 3458),
    ("prompts/codex_prompt.md", "2d47853e3d96b00adbef3ac1f8e761100115dc486aa9a02f38a84ee4df0d5a36", 15912),
    ("schema/schema.md", "f5f3e576079ddbd253467e92dbd072959179b1c48edb433750251c4e25937591", 7511),
    ("schema/protected_exam_analysis.md", "454a57467992c17e26bb6fefa2eb4adba02f7b37fa93f9c1d214085572f872a6", 4834),
    ("schema/reference_grounded_examples.md", "f5e86ca75fbfe1b5edbea9b07e75222d93f7d9461a4b0868584152eebe753134", 5758),
)
EXPECTED_CLASSIFICATIONS: tuple[str, ...] = (
    "replaced_by_current",
    "replaced_by_current",
    "replaced_by_current",
    "replaced_by_current",
    "replaced_by_current",
    "replaced_by_current",
    "replaced_by_current",
    "replaced_by_current",
    "replaced_by_current",
    "replaced_by_current",
    "replaced_by_current",
    "replaced_by_current",
    "evidence_only",
    "replaced_by_current",
    "evidence_only",
    "replaced_by_current",
    "restore_required",
    "restore_required",
    "restore_required",
    "restore_required",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_KEYS = {
    "schema_version",
    "subject",
    "bundle_sha256",
    "ordered_raw_bytes_algorithm",
    "ordered_paths",
    "file_count",
    "total_bytes",
    "files",
}
ENTRY_KEYS = {
    "path",
    "file_sha256",
    "size",
    "classification",
    "active_caller_or_reference",
    "replacement_reference",
}


class VerificationError(RuntimeError):
    """A fail-closed, user-actionable verification error."""


def _is_safe_relative_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and "." not in path.parts
        and ".." not in path.parts
        and path.as_posix() == value
    )


def _checked_path(root: Path, relative: str) -> Path:
    if not _is_safe_relative_path(relative):
        raise VerificationError(f"unsafe relative path: {relative!r}")
    root = root.expanduser().resolve()
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    if candidate.is_symlink():
        raise VerificationError(f"symlink is not an accepted source file: {relative}")
    try:
        candidate.resolve().relative_to(root)
    except ValueError as exc:
        raise VerificationError(f"path escapes root: {relative}") from exc
    return candidate


def _raw_file(path: Path, relative: str) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise VerificationError(f"source file missing or not regular: {relative}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise VerificationError(f"cannot read source file: {relative}") from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ordered_bytes_digest(rows: Iterable[tuple[str, str]]) -> str:
    payload = b"".join(
        f"{file_sha256}  {relative_path}\n".encode("utf-8")
        for file_sha256, relative_path in rows
    )
    return _sha256(payload)


def _load_manifest(repo_root: Path) -> dict[str, Any]:
    manifest_path = repo_root / "schema" / "study-intake-historical-source-closure-v1.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise VerificationError("historical source-closure manifest is missing") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError("historical source-closure manifest is unreadable") from exc
    if not isinstance(manifest, dict):
        raise VerificationError("historical source-closure manifest must be an object")
    _validate_manifest(manifest)
    return manifest


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    if set(manifest) != MANIFEST_KEYS:
        raise VerificationError("manifest top-level fields mismatch")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise VerificationError("manifest schema_version mismatch")
    if manifest.get("subject") != SUBJECT:
        raise VerificationError("manifest subject mismatch")
    if manifest.get("bundle_sha256") != EXPECTED_BUNDLE_SHA256:
        raise VerificationError("manifest bundle_sha256 mismatch")
    if manifest.get("ordered_raw_bytes_algorithm") != ALGORITHM_SPEC:
        raise VerificationError("manifest ordered raw-bytes algorithm mismatch")
    ordered_paths = manifest.get("ordered_paths")
    if ordered_paths != [row[0] for row in EXPECTED_ROWS]:
        raise VerificationError("manifest ordered_paths mismatch")
    if manifest.get("file_count") != EXPECTED_FILE_COUNT:
        raise VerificationError("manifest file_count mismatch")
    if manifest.get("total_bytes") != EXPECTED_TOTAL_BYTES:
        raise VerificationError("manifest total_bytes mismatch")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != EXPECTED_FILE_COUNT:
        raise VerificationError("manifest files list mismatch")
    metadata_rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, entry in enumerate(files):
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            raise VerificationError(f"manifest file entry fields mismatch at index {index}")
        path, expected_sha256, expected_size = EXPECTED_ROWS[index]
        if entry.get("path") != path or path in seen:
            raise VerificationError(f"manifest file path mismatch at index {index}")
        seen.add(path)
        if not _is_safe_relative_path(entry.get("path")):
            raise VerificationError(f"manifest file path is not safe: {path}")
        if entry.get("file_sha256") != expected_sha256 or not HEX64.fullmatch(
            str(entry.get("file_sha256"))
        ):
            raise VerificationError(f"manifest file hash mismatch: {path}")
        if (
            entry.get("size") != expected_size
            or not isinstance(entry.get("size"), int)
            or isinstance(entry.get("size"), bool)
        ):
            raise VerificationError(f"manifest file size mismatch: {path}")
        classification = entry.get("classification")
        if classification not in ALLOWED_CLASSIFICATIONS:
            raise VerificationError(f"manifest classification is invalid: {path}")
        if classification != EXPECTED_CLASSIFICATIONS[index]:
            raise VerificationError(f"manifest classification mismatch: {path}")
        caller = entry.get("active_caller_or_reference")
        if (
            not isinstance(caller, str)
            or not caller.strip()
            or "\n" in caller
            or "/Users/" in caller
            or "/home/" in caller
        ):
            raise VerificationError(f"manifest caller/reference is invalid: {path}")
        replacement = entry.get("replacement_reference")
        if classification == "replaced_by_current":
            if not _is_safe_relative_path(replacement):
                raise VerificationError(f"replacement reference is invalid: {path}")
        elif replacement is not None:
            raise VerificationError(f"unexpected replacement reference: {path}")
        metadata_rows.append((expected_sha256, path))
    if sum(row[2] for row in EXPECTED_ROWS) != EXPECTED_TOTAL_BYTES:
        raise VerificationError("verifier frozen total_bytes is inconsistent")
    if ordered_bytes_digest(metadata_rows) != EXPECTED_BUNDLE_SHA256:
        raise VerificationError("manifest file metadata does not reproduce bundle hash")


def _classification_counts(manifest: Mapping[str, Any]) -> dict[str, int]:
    counts = Counter(entry["classification"] for entry in manifest["files"])
    return {
        classification: counts.get(classification, 0)
        for classification in ALLOWED_CLASSIFICATIONS
    }


def _verify_external(repo_root: Path, source_root: Path) -> dict[str, Any]:
    manifest = _load_manifest(repo_root)
    if not source_root.expanduser().is_dir():
        raise VerificationError("external source root is missing or not a directory")
    actual_rows: list[tuple[str, str]] = []
    for entry in manifest["files"]:
        relative = entry["path"]
        data = _raw_file(_checked_path(source_root, relative), relative)
        actual_sha256 = _sha256(data)
        if actual_sha256 != entry["file_sha256"] or len(data) != entry["size"]:
            raise VerificationError(f"historical source bytes mismatch: {relative}")
        actual_rows.append((actual_sha256, relative))
    if ordered_bytes_digest(actual_rows) != manifest["bundle_sha256"]:
        raise VerificationError("historical source aggregate hash mismatch")
    return _success_payload("external", manifest, restore_required=[])


def _verify_canonical(repo_root: Path) -> dict[str, Any]:
    manifest = _load_manifest(repo_root)
    restore_required: list[str] = []
    replacement_checked = 0
    for entry in manifest["files"]:
        relative = entry["path"]
        classification = entry["classification"]
        replacement = entry["replacement_reference"]
        if classification == "restore_required":
            data = _raw_file(_checked_path(repo_root, relative), relative)
            if _sha256(data) != entry["file_sha256"] or len(data) != entry["size"]:
                raise VerificationError(f"restore-required bytes mismatch: {relative}")
            restore_required.append(relative)
        elif classification == "replaced_by_current":
            _raw_file(_checked_path(repo_root, replacement), replacement)
            replacement_checked += 1
        elif classification in {"evidence_only", "reject_private_or_runtime"}:
            candidate = _checked_path(repo_root, relative)
            if candidate.exists() or candidate.is_symlink():
                raise VerificationError(
                    f"{classification} file unexpectedly present in canonical: {relative}"
                )
    return _success_payload(
        "canonical",
        manifest,
        restore_required=restore_required,
        replacement_references_checked=replacement_checked,
    )


def _success_payload(
    mode: str,
    manifest: Mapping[str, Any],
    *,
    restore_required: Sequence[str],
    replacement_references_checked: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mode": mode,
        "status": "PASS",
        "subject": manifest["subject"],
        "bundle_sha256": manifest["bundle_sha256"],
        "file_count": manifest["file_count"],
        "total_bytes": manifest["total_bytes"],
        "classification_counts": _classification_counts(manifest),
        "restore_required": list(restore_required),
    }
    if replacement_references_checked is not None:
        payload["replacement_references_checked"] = replacement_references_checked
    return payload


def _failure_payload(mode: str, message: str) -> dict[str, Any]:
    return {"mode": mode, "status": "FAIL", "errors": [message]}


def _emit(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode")
    external = subparsers.add_parser("external", help="verify the historical source root")
    external.add_argument("--source-root", help="explicit historical source root")
    canonical = subparsers.add_parser("canonical", help="verify canonical replacement references")
    canonical.add_argument("--repo-root", help="canonical repository root")
    args = parser.parse_args(argv)
    if args.mode not in {"external", "canonical"}:
        _emit(_failure_payload("unknown", "a subcommand is required: external or canonical"))
        return 2
    repo_root = Path(__file__).resolve().parents[1]
    try:
        if args.mode == "external":
            if not args.source_root:
                raise VerificationError("external requires explicit --source-root")
            payload = _verify_external(repo_root, Path(args.source_root))
        else:
            payload = _verify_canonical(Path(args.repo_root) if args.repo_root else repo_root)
    except VerificationError as exc:
        _emit(_failure_payload(args.mode, str(exc)))
        return 1
    _emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
