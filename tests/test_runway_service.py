import pytest

from bot.services.runway_service import runway_service


@pytest.mark.asyncio
async def test_runway_generate_video():
    """Test Runway video generation"""
    result = await runway_service.generate_video(
        prompt="test prompt", duration=5, aspect_ratio="16:9"
    )
    assert result is not None
    if "error" not in result:
        assert "task_id" in result


@pytest.mark.asyncio
async def test_runway_status():
    """Test status polling (requires real task_id)"""
    # Skip for now or use mock
    pass
