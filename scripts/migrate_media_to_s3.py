#!/usr/bin/env python3
"""Copy and verify existing ``static/uploads`` files in configured S3 storage.

The command is intentionally non-destructive. It never removes local files or
changes database rows; `/uploads/...` keys remain unchanged.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from bot.services.media_storage import (
    file_sha256,
    is_s3_enabled,
    persist_upload_file,
    remote_upload_fingerprint,
)


@dataclass(frozen=True)
class MigrationResult:
    relative_path: str
    size_bytes: int
    status: str
    detail: str = ""


def iter_source_files(root: Path, prefixes: tuple[str, ...] = ()):
    normalized_prefixes = tuple(value.strip().strip("/") for value in prefixes if value.strip().strip("/"))
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if path.name.endswith((".part", ".tmp", ".s3-cache")) or ".tmp." in path.name:
            continue
        relative = path.relative_to(root).as_posix()
        if normalized_prefixes and not any(
            relative == prefix or relative.startswith(prefix + "/")
            for prefix in normalized_prefixes
        ):
            continue
        yield path


def _cache_control(relative_path: str) -> str:
    if relative_path.startswith(("feed/", "trend-previews/")):
        return "public, max-age=31536000, immutable"
    return "private, max-age=0"


def migrate_one(
    path: Path,
    *,
    root: Path,
    dry_run: bool,
    verify_only: bool,
) -> MigrationResult:
    relative = path.relative_to(root).as_posix()
    size = path.stat().st_size
    if size <= 0:
        return MigrationResult(relative, size, "skipped", "empty source file")

    source_digest = file_sha256(path)
    remote = remote_upload_fingerprint(relative)
    if remote == (size, source_digest):
        return MigrationResult(relative, size, "verified")
    if verify_only:
        detail = "missing" if remote is None else "size or SHA-256 mismatch"
        return MigrationResult(relative, size, "missing", detail)
    if dry_run:
        detail = "new" if remote is None else "replace remote with unverified content"
        return MigrationResult(relative, size, "planned", detail)

    persist_upload_file(
        relative,
        path,
        content_type=mimetypes.guess_type(path.name)[0],
        cache_control=_cache_control(relative),
        retain_local_copy=True,
    )
    verified = remote_upload_fingerprint(relative)
    if verified != (size, source_digest) or file_sha256(path) != source_digest:
        return MigrationResult(
            relative,
            size,
            "failed",
            "verification mismatch: remote/local size or SHA-256",
        )
    return MigrationResult(relative, size, "uploaded")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy and verify NEUROMIX references/media in configured S3 storage"
    )
    parser.add_argument("--root", default="static/uploads", help="local upload root")
    parser.add_argument(
        "--prefix",
        action="append",
        default=[],
        help="relative subtree to include; repeat for multiple prefixes",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--manifest", help="append JSONL results to this file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not is_s3_enabled():
        print("MEDIA_STORAGE_BACKEND must be s3", file=sys.stderr)
        return 2
    root = Path(args.root)
    if not root.is_dir():
        print(f"Upload root is not a directory: {root}", file=sys.stderr)
        return 2
    workers = max(1, min(int(args.workers), 16))
    files = list(iter_source_files(root, tuple(args.prefix)))
    if args.limit > 0:
        files = files[: args.limit]

    results: list[MigrationResult] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                migrate_one,
                path,
                root=root,
                dry_run=bool(args.dry_run),
                verify_only=bool(args.verify_only),
            ): path
            for path in files
        }
        for future in as_completed(futures):
            path = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001 - per-file migration boundary
                result = MigrationResult(
                    path.relative_to(root).as_posix(),
                    path.stat().st_size,
                    "failed",
                    type(exc).__name__,
                )
            results.append(result)
            print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))

    if args.manifest:
        manifest = Path(args.manifest)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with manifest.open("a", encoding="utf-8") as output:
            for result in sorted(results, key=lambda item: item.relative_path):
                output.write(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True) + "\n")

    summary: dict[str, int] = {}
    for result in results:
        summary[result.status] = summary.get(result.status, 0) + 1
    print(json.dumps({"summary": summary, "total": len(results)}, sort_keys=True))
    return 1 if any(result.status in {"failed", "missing"} for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
