"""Bounded synchronous filesystem work, called only with asyncio.to_thread."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import uuid
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


class Wan3PrimeDocumentError(Wan3PrimeValidationError):
    """Invalid or resource-exhausting document; do not reparse its upload."""


def document_pages(path: Path) -> int | None:
    extension = path.suffix.lower()
    if extension not in {'.pdf', '.docx', '.xlsx', '.pptx', '.key', '.pages', '.numbers'}:
        return None
    worker = Path(__file__).with_name('wan3_prime_document_probe.py').resolve()
    try:
        result = subprocess.run([sys.executable, '-I', str(worker), str(path.resolve())],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=12, check=False)
        if result.returncode != 0:
            raise Wan3PrimeDocumentError('Invalid, encrypted or resource-intensive document')
        value = result.stdout.strip()
        if value == 'unknown' and extension != '.pdf':
            return None
        count = int(value)
        if count <= 0:
            raise Wan3PrimeDocumentError('Document has no readable pages')
        return count
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        if isinstance(exc, Wan3PrimeDocumentError):
            raise
        raise Wan3PrimeDocumentError('Cannot safely inspect document') from exc


def convert_voice_to_mp3(source: Path, destination: Path) -> None:
    """Preserve the complete audio; final media validation enforces input limits."""
    try:
        subprocess.run(
            ['ffmpeg', '-nostdin', '-v', 'error', '-protocol_whitelist', 'file,pipe',
             '-format_whitelist', 'ogg,mov,wav,mp3,aac', '-i', str(source), '-map', '0:a:0',
             '-vn', '-c:a', 'libmp3lame', '-b:a', '128k', '-y', str(destination)],
            capture_output=True, timeout=30, check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        destination.unlink(missing_ok=True)
        raise Wan3PrimeValidationError('Could not convert this audio to MP3') from exc
