#!/usr/bin/env python3
"""Reclaim local upload copies only after exact S3 size verification.

Dry-run is the default. Destructive execution requires both ``--execute`` and
an exact ``--confirm-bucket`` value, and every file is checked immediately
before deletion. S3 objects and database rows are never changed.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from bot.services.media_storage import (
    S3Settings,
    file_sha256,
    is_s3_enabled,
    remote_upload_fingerprint,
)
from scripts.migrate_media_to_s3 import iter_source_files


@dataclass(frozen=True)
class ReclaimResult:
    relative_path: str
    size_bytes: int
    status: str
    detail: str = ""


def reclaim_one(path: Path, *, root: Path, execute: bool) -> ReclaimResult:
    relative = path.relative_to(root).as_posix()
    size = path.stat().st_size
    if size <= 0:
        return ReclaimResult(relative, size, "skipped", "empty source file")
    source_digest = file_sha256(path)
    remote = remote_upload_fingerprint(relative)
    if remote != (size, source_digest):
        detail = "missing" if remote is None else "remote size or SHA-256 mismatch"
        return ReclaimResult(relative, size, "blocked", detail)
    if not execute:
        return ReclaimResult(relative, size, "reclaimable")

    # Re-read local metadata after the remote check to avoid deleting a file
    # replaced concurrently with a different payload.
    current_size = path.stat().st_size
    if current_size != size or file_sha256(path) != source_digest:
        return ReclaimResult(
            relative,
            current_size,
            "blocked",
            "local file changed during verification",
        )
    path.unlink()
    path.with_name(f".{path.name}.s3-cache").unlink(missing_ok=True)
    return ReclaimResult(relative, size, "deleted")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify S3 copies and optionally reclaim NEUROMIX local media"
    )
    parser.add_argument("--root", default="static/uploads", help="local upload root")
    parser.add_argument(
        "--prefix",
        action="append",
        default=[],
        help="relative subtree to include; repeat for multiple prefixes",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--manifest", help="append JSONL results to this file")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="delete exact-size verified local copies; otherwise dry-run",
    )
    parser.add_argument(
        "--confirm-bucket",
        default="",
        help="required with --execute and must exactly match MEDIA_S3_BUCKET",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not is_s3_enabled():
        print("MEDIA_STORAGE_BACKEND must be s3", file=sys.stderr)
        return 2
    settings = S3Settings.from_config()
    if args.execute and args.confirm_bucket != settings.bucket:
        print(
            "--execute requires --confirm-bucket matching MEDIA_S3_BUCKET",
            file=sys.stderr,
        )
        return 2

    root = Path(args.root)
    if not root.is_dir() or root.is_symlink():
        print(f"Upload root is not a safe directory: {root}", file=sys.stderr)
        return 2
    files = list(iter_source_files(root, tuple(args.prefix)))
    if args.limit > 0:
        files = files[: args.limit]

    results: list[ReclaimResult] = []
    for path in files:
        try:
            result = reclaim_one(path, root=root, execute=bool(args.execute))
        except Exception as exc:  # noqa: BLE001 - per-file reclamation boundary
            result = ReclaimResult(
                path.relative_to(root).as_posix(),
                path.stat().st_size if path.exists() else 0,
                "failed",
                type(exc).__name__,
            )
        results.append(result)
        print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))

    if args.manifest:
        manifest = Path(args.manifest)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with manifest.open("a", encoding="utf-8") as output:
            for result in results:
                output.write(
                    json.dumps(asdict(result), ensure_ascii=False, sort_keys=True) + "\n"
                )

    summary: dict[str, int] = {}
    for result in results:
        summary[result.status] = summary.get(result.status, 0) + 1
    print(json.dumps({"summary": summary, "total": len(results)}, sort_keys=True))
    return 1 if any(item.status in {"blocked", "failed"} for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
