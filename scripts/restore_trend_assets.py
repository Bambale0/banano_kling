"""Restore only exact hash/size-matched trend assets; never edit DB rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


def digest_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def restore_one(
    source: Path, destination: Path, expected_hash: str, expected_size: int
) -> str:
    if source.stat().st_size != expected_size or digest_file(source) != expected_hash:
        raise ValueError("Source no longer matches expected bytes")
    if destination.exists():
        if (
            destination.is_file()
            and destination.stat().st_size == expected_size
            and digest_file(destination) == expected_hash
        ):
            return "already_valid"
        raise ValueError("Existing destination differs; refusing overwrite")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, prefix=".restore-", delete=False
        ) as out:
            staged = Path(out.name)
            with source.open("rb") as inp:
                shutil.copyfileobj(inp, out)
            out.flush()
            os.fsync(out.fileno())
        if (
            staged.stat().st_size != expected_size
            or digest_file(staged) != expected_hash
        ):
            raise ValueError("Staged copy differs; refusing publish")
        staged.chmod(0o644)
        try:
            os.link(staged, destination)
        except FileExistsError:
            if (
                destination.stat().st_size != expected_size
                or digest_file(destination) != expected_hash
            ):
                raise ValueError("Concurrent conflicting destination")
            return "already_valid"
        descriptor = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return "restored"
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def main() -> None:
    import psycopg
    from psycopg.rows import dict_row

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", action="append", required=True)
    parser.add_argument("--media-root", default="/app/static/uploads/trend-assets")
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with psycopg.connect(
        os.environ["DATABASE_URL"],
        row_factory=dict_row,
        options="-c default_transaction_read_only=on -c statement_timeout=15000",
    ) as connection:
        assets = connection.execute(
            "SELECT id,prompt_id,media_type,position,file_url,file_hash,size_bytes FROM trend_reference_assets ORDER BY id"
        ).fetchall()
    media_root = Path(args.media_root).resolve()
    sizes = {int(a["size_bytes"]) for a in assets}
    hashes = {a["file_hash"] for a in assets}
    matches = defaultdict(list)
    scanned = 0
    for base in args.source_root:
        for root, dirs, names in os.walk(base, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
            for name in names:
                path = Path(root) / name
                try:
                    scanned += 1
                    if (
                        path.is_symlink()
                        or path.stat().st_size not in sizes
                        or not path.is_file()
                    ):
                        continue
                    digest = digest_file(path)
                    if digest in hashes:
                        matches[digest].append(path)
                except (FileNotFoundError, PermissionError):
                    continue
    required_bytes = sum(int(a["size_bytes"]) for a in assets)
    if args.apply and shutil.disk_usage(media_root).free < required_bytes * 2:
        raise RuntimeError("Insufficient space for atomic restore")
    receipt_path = Path(args.receipt)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    if receipt_path.exists():
        raise FileExistsError("Receipt already exists; use a new run receipt")
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "apply": args.apply,
        "scanned_files": scanned,
        "assets": [],
    }
    with receipt_path.open("x", encoding="utf-8") as receipt:
        receipt.write(
            json.dumps(
                {"event": "begin", "scanned_files": scanned, "apply": args.apply}
            )
            + "\n"
        )
        receipt.flush()
        os.fsync(receipt.fileno())
        for asset in assets:
            path = urlparse(asset["file_url"]).path
            if not path.startswith("/uploads/trend-assets/"):
                raise ValueError("Asset destination outside trend storage")
            destination = (
                media_root / path.removeprefix("/uploads/trend-assets/")
            ).resolve()
            if (
                not destination.is_relative_to(media_root)
                or destination.stem != asset["file_hash"]
            ):
                raise ValueError("Untrusted destination or hash mismatch")
            item = {**asset, "destination": str(destination)}
            try:
                if (
                    destination.is_file()
                    and destination.stat().st_size == asset["size_bytes"]
                    and digest_file(destination) == asset["file_hash"]
                ):
                    item["status"] = "already_valid"
                elif matches.get(asset["file_hash"]):
                    source = min(matches[asset["file_hash"]])
                    item["source"] = str(source)
                    item["status"] = (
                        restore_one(
                            source,
                            destination,
                            asset["file_hash"],
                            int(asset["size_bytes"]),
                        )
                        if args.apply
                        else "recoverable"
                    )
                else:
                    item["status"] = "source_not_found"
            except (OSError, ValueError) as error:
                item["status"] = "error"
                item["error"] = str(error)
            report["assets"].append(item)
            receipt.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
            receipt.flush()
            os.fsync(receipt.fileno())
    print(json.dumps(report, ensure_ascii=False, default=str))
    if any(item["status"] == "error" for item in report["assets"]):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
