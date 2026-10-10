"""Bounded synchronous filesystem work, called only with asyncio.to_thread."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path

from bot.services.wan3_prime_media import Wan3PrimeValidationError, canonical_child_path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_chunk(path: Path, content: bytes, digest: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and sha256_file(path) == digest:
        return
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def copy_atomic(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with source.open("rb") as src, temporary.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(temporary, destination)
        _sync_directory(destination.parent)
        return sha256_file(destination)
    finally:
        temporary.unlink(missing_ok=True)


def assemble_chunks(session_dir: Path, destination: Path, hashes: dict[str, str], total: int, expected_size: int) -> None:
    with destination.open("wb") as out:
        for index in range(total):
            part = canonical_child_path(session_dir, f"{index:06d}.part")
            if not part.is_file() or sha256_file(part) != hashes.get(str(index)):
                raise Wan3PrimeValidationError("Upload chunk is missing or incomplete", status=409)
            with part.open("rb") as handle:
                shutil.copyfileobj(handle, out, length=1024 * 1024)
        out.flush()
        os.fsync(out.fileno())
    if destination.stat().st_size != expected_size:
        raise Wan3PrimeValidationError("Upload size mismatch", status=409)


def document_pages(path: Path) -> int | None:
    extension = path.suffix.lower()
    if extension == ".pdf":
        # A child process bounds both wall-clock and memory for untrusted PDFs.
        program = (
            "import resource,sys; "
            "resource.setrlimit(resource.RLIMIT_AS,(768*1024**2,768*1024**2)); "
            "from pypdf import PdfReader; "
            "r=PdfReader(sys.argv[1],strict=False,root_object_recovery_limit=10000); "
            "assert not r.is_encrypted,'encrypted PDF'; "
            "print(len(r.pages))"
        )
        try:
            result = subprocess.run([sys.executable, "-I", "-c", program, str(path.resolve())],
                                    capture_output=True, text=True, timeout=12, check=False)
            count = int(result.stdout.strip()) if result.returncode == 0 else 0
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise Wan3PrimeValidationError("Cannot safely read PDF pages") from exc
        if count <= 0:
            raise Wan3PrimeValidationError("Invalid or encrypted PDF")
        return count
    if extension in {".docx", ".xlsx", ".pptx", ".key", ".pages", ".numbers"} and zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                if len(entries) > 10000 or sum(entry.file_size for entry in entries) > 250 * 1024**2:
                    raise Wan3PrimeValidationError("Document archive expands beyond the safe limit")
                if extension == ".pptx":
                    count = sum(bool(re.fullmatch(r"ppt/slides/slide\d+\.xml", entry.filename)) for entry in entries)
                    if not count:
                        raise Wan3PrimeValidationError("Presentation has no slides")
                    return count
        except zipfile.BadZipFile as exc:
            raise Wan3PrimeValidationError("Invalid document archive") from exc
    # Word/Keynote page count depends on layout. Do not invent an exact count;
    # this is disclosed in the quote and remains checked by the provider.
    return None
