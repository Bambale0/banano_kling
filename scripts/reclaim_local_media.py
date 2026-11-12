#!/usr/bin/env python3
"""Reclaim local upload copies only after exact S3 size verification.

Dry-run is the default. Destructive execution requires both ``--execute`` and
an exact ``--confirm-bucket`` value, and every file is checked immediately
before deletion. S3 objects and database rows are never changed.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import time
from contextlib import nullcontext
from dataclasses import asdict, dataclass
from itertools import islice
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


def reclaim_one(
    path: Path, *, root: Path, execute: bool, min_age_seconds: int = 0
) -> ReclaimResult:
    relative = path.relative_to(root).as_posix()
    initial = path.lstat()
    size = initial.st_size
    if not stat.S_ISREG(initial.st_mode):
        return ReclaimResult(relative, size, "skipped", "not a regular source file")
    if min_age_seconds and time.time() - initial.st_mtime < min_age_seconds:
        return ReclaimResult(relative, size, "skipped", "recently modified source")
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
    current = path.lstat()
    def identity(st):
        return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns
    if (
        not stat.S_ISREG(current.st_mode)
        or identity(current) != identity(initial)
        or file_sha256(path) != source_digest
        or identity(path.lstat()) != identity(initial)
    ):
        return ReclaimResult(
            relative,
            current.st_size,
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
    parser.add_argument(
        "--min-age-seconds", type=int, default=86400,
        help="skip recently modified source files (default: 24 hours)",
    )
    parser.add_argument("--quiet", action="store_true", help="write per-file results only to manifest")
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
    if args.min_age_seconds < 0 or args.limit < 0:
        print("--min-age-seconds and --limit must not be negative", file=sys.stderr)
        return 2
    if args.execute and not args.manifest:
        print("--execute requires --manifest for durable per-file audit", file=sys.stderr)
        return 2
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
    # Never materialize the whole multi-million-file catalog in RAM.
    files = iter_source_files(root, tuple(args.prefix))
    if args.limit > 0:
        files = islice(files, args.limit)

    summary: dict[str, int] = {}
    total = 0
    reclaimed_bytes = 0
    journal = Path(args.manifest) if args.manifest else None
    if journal:
        journal.parent.mkdir(parents=True, exist_ok=True)
    with (journal.open("a", encoding="utf-8") if journal else nullcontext(None)) as output:
        for path in files:
            try:
                result = reclaim_one(
                    path, root=root, execute=bool(args.execute),
                    min_age_seconds=args.min_age_seconds,
                )
            except Exception as exc:  # noqa: BLE001 - per-file boundary
                result = ReclaimResult(
                    path.relative_to(root).as_posix(),
                    path.stat().st_size if path.exists() else 0,
                    "failed",
                    type(exc).__name__,
                )
            record = json.dumps(asdict(result), ensure_ascii=False, sort_keys=True)
            if output is not None:
                output.write(record + "\n")
                output.flush()
            if not args.quiet:
                print(record)
            summary[result.status] = summary.get(result.status, 0) + 1
            total += 1
            if result.status == "deleted":
                reclaimed_bytes += result.size_bytes

        if output is not None:
            output.flush()
            os.fsync(output.fileno())

    print(json.dumps({
        "summary": summary, "total": total, "reclaimed_bytes": reclaimed_bytes,
    }, sort_keys=True))
    return 1 if summary.get("blocked", 0) or summary.get("failed", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
