"""Restoration publishes verified bytes once and never replaces existing data."""

import hashlib
import runpy
from pathlib import Path

import pytest

restore_one = runpy.run_path(
    str(Path(__file__).parents[1] / "scripts/restore_trend_assets.py")
)["restore_one"]


def test_restore_exact_bytes_and_retry_is_idempotent(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"verified original")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    destination = tmp_path / "published" / "asset.png"
    assert restore_one(source, destination, digest, source.stat().st_size) == "restored"
    assert destination.read_bytes() == source.read_bytes()
    assert (
        restore_one(source, destination, digest, source.stat().st_size)
        == "already_valid"
    )
    assert not list(tmp_path.rglob(".restore-*"))


def test_restore_never_overwrites_different_destination(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"verified original")
    destination = tmp_path / "asset.png"
    destination.write_bytes(b"existing different original")
    with pytest.raises(ValueError, match="refusing overwrite"):
        restore_one(
            source,
            destination,
            hashlib.sha256(source.read_bytes()).hexdigest(),
            source.stat().st_size,
        )
    assert destination.read_bytes() == b"existing different original"


@pytest.mark.parametrize("hash_mismatch", [True, False])
def test_restore_rejects_incorrect_hash_or_size(tmp_path, hash_mismatch):
    source = tmp_path / "source.png"
    source.write_bytes(b"verified original")
    destination = tmp_path / "asset.png"
    digest = (
        "0" * 64 if hash_mismatch else hashlib.sha256(source.read_bytes()).hexdigest()
    )
    size = source.stat().st_size if hash_mismatch else source.stat().st_size + 1
    with pytest.raises(ValueError, match="no longer matches"):
        restore_one(source, destination, digest, size)
    assert not destination.exists()
