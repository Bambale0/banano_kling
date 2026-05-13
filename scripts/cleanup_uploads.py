#!/usr/bin/env python3
"""Clean static/uploads according to retention policy.

Defaults are conservative for production:
- images/reference files: 24h
- videos/results: 7d
- never deletes unknown extensions unless --include-unknown is set
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".dng"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}


def cleanup_uploads(root: Path, *, image_hours: int, video_hours: int, dry_run: bool, include_unknown: bool = False) -> dict:
    now = time.time()
    stats = {"scanned": 0, "deleted": 0, "bytes_deleted": 0, "kept": 0}
    if not root.exists():
        return stats

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        stats["scanned"] += 1
        suffix = path.suffix.lower()
        if suffix in IMAGE_EXTS:
            ttl = image_hours * 3600
        elif suffix in VIDEO_EXTS:
            ttl = video_hours * 3600
        elif include_unknown:
            ttl = video_hours * 3600
        else:
            stats["kept"] += 1
            continue

        try:
            age = now - path.stat().st_mtime
            if age < ttl:
                stats["kept"] += 1
                continue
            size = path.stat().st_size
            if not dry_run:
                path.unlink()
            stats["deleted"] += 1
            stats["bytes_deleted"] += size
        except FileNotFoundError:
            continue
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/root/bot/banano_kling/static/uploads")
    parser.add_argument("--image-hours", type=int, default=24)
    parser.add_argument("--video-hours", type=int, default=24 * 7)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-unknown", action="store_true")
    args = parser.parse_args()
    stats = cleanup_uploads(
        Path(args.root),
        image_hours=args.image_hours,
        video_hours=args.video_hours,
        dry_run=args.dry_run,
        include_unknown=args.include_unknown,
    )
    mb = stats["bytes_deleted"] / (1024 * 1024)
    mode = "DRY_RUN" if args.dry_run else "CLEANED"
    print(f"{mode} scanned={stats['scanned']} deleted={stats['deleted']} kept={stats['kept']} bytes_deleted={stats['bytes_deleted']} ({mb:.1f} MiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
