"""Incident regression: durable trend templates are outside temporary reference cleanup."""

import pytest

from bot.database import cleanup_orphaned_reference_files


@pytest.mark.asyncio
async def test_orphan_reference_cleanup_cannot_delete_durable_trend_asset(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    ref = (
        tmp_path
        / "static"
        / "uploads"
        / "trend-assets"
        / "image"
        / "owner"
        / "original.png"
    )
    ref.parent.mkdir(parents=True)
    ref.write_bytes(b"original reference")
    result = await cleanup_orphaned_reference_files(max_age_seconds=0)
    assert result["removed_count"] == 0
    assert result["removed_bytes"] == 0
    assert ref.read_bytes() == b"original reference"
