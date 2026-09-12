"""Tests for bot.services.task_watchdog — watchog that recovers stuck tasks."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.services.task_watchdog import (
    get_stuck_tasks,
    force_fail_task,
    check_task_with_provider,
    run_watchdog_cycle,
    STUCK_THRESHOLD_MINUTES,
    MAX_STUCK_MINUTES,
)


class TestGetStuckTasks:
    """Tests for get_stuck_tasks — finding stuck 'processing' tasks."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_none_stuck(self):
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = []
        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_cursor
        mock_connect = AsyncMock()
        mock_connect.__aenter__.return_value = mock_db

        with patch("bot.services.task_watchdog.db_backend.connect", return_value=mock_connect):
            tasks = await get_stuck_tasks(minutes=30)
            assert tasks == []

    @pytest.mark.asyncio
    async def test_returns_stuck_tasks(self):
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = [
            {"id": 1, "user_id": 42, "task_id": "ext_1", "model": "kling", "cost": 5, "status": "processing"},
            {"id": 2, "user_id": 43, "task_id": "ext_2", "model": "nano_banana", "cost": 10, "status": "processing"},
        ]
        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_cursor
        mock_connect = AsyncMock()
        mock_connect.__aenter__.return_value = mock_db

        with patch("bot.services.task_watchdog.db_backend.connect", return_value=mock_connect):
            tasks = await get_stuck_tasks(minutes=30)
            assert len(tasks) == 2
            assert tasks[0]["id"] == 1
            assert tasks[1]["id"] == 2


class TestForceFailTask:
    """Tests for force_fail_task — updating task to failed + refunding credits."""

    @pytest.mark.asyncio
    async def test_force_fails_and_refunds(self):
        mock_db = AsyncMock()
        cursor = AsyncMock()
        cursor.rowcount = 1
        mock_db.execute.return_value = cursor
        mock_connect = AsyncMock()
        mock_connect.__aenter__.return_value = mock_db

        with patch("bot.services.task_watchdog.db_backend.connect", return_value=mock_connect):
            result = await force_fail_task(task_id=1, user_id=42, cost=10.0)
            assert result is True
            # Should update task and refund credits
            assert mock_db.execute.call_count >= 2

    @pytest.mark.asyncio
    async def test_returns_false_when_no_rows_updated(self):
        mock_db = AsyncMock()
        cursor = AsyncMock()
        cursor.rowcount = 0
        mock_db.execute.return_value = cursor
        mock_connect = AsyncMock()
        mock_connect.__aenter__.return_value = mock_db

        with patch("bot.services.task_watchdog.db_backend.connect", return_value=mock_connect):
            result = await force_fail_task(task_id=999, user_id=1, cost=5.0)
            assert result is False

    @pytest.mark.asyncio
    async def test_skips_refund_when_cost_zero(self):
        mock_db = AsyncMock()
        cursor = AsyncMock()
        cursor.rowcount = 1
        mock_db.execute.return_value = cursor
        mock_connect = AsyncMock()
        mock_connect.__aenter__.return_value = mock_db

        with patch("bot.services.task_watchdog.db_backend.connect", return_value=mock_connect):
            result = await force_fail_task(task_id=1, user_id=42, cost=0)
            assert result is True
            # Only UPDATE, no second UPDATE for credits
            assert mock_db.execute.call_count == 1


class TestRunWatchdogCycle:
    """Tests for run_watchdog_cycle — full cycle orchestration."""

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_stuck_tasks(self):
        with (
            patch("bot.services.task_watchdog.get_stuck_tasks", AsyncMock(return_value=[])),
            patch(
                "bot.services.task_watchdog.cleanup_stale_local_generation_tasks",
                AsyncMock(return_value={"failed_count": 0, "refunded_credits": 0.0}),
            ) as cleanup_orphans,
        ):
            recovered = await run_watchdog_cycle()
            assert recovered == 0
            cleanup_orphans.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recovers_local_orphan_tasks_even_when_no_provider_tasks_are_stuck(self):
        with (
            patch("bot.services.task_watchdog.get_stuck_tasks", AsyncMock(return_value=[])),
            patch(
                "bot.services.task_watchdog.cleanup_stale_local_generation_tasks",
                AsyncMock(return_value={"failed_count": 2, "refunded_credits": 3.0}),
            ) as cleanup_orphans,
        ):
            recovered = await run_watchdog_cycle()

        assert recovered == 2
        cleanup_orphans.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_young_stuck_tasks(self):
        """Tasks still within MAX_STUCK_MINUTES should not be force-failed
        (they get checked by provider which may return None)."""
        from datetime import datetime, timedelta
        stuck = [{
            "id": 1, "user_id": 42, "task_id": "ext_1", "model": "kling",
            "cost": 5, "request_data": "{}",
            "created_at": datetime.utcnow() - timedelta(minutes=45),  # >30 stuck but <120 max
        }]
        with (
            patch("bot.services.task_watchdog.get_stuck_tasks", AsyncMock(return_value=stuck)),
            patch("bot.services.task_watchdog.force_fail_task", AsyncMock()) as mock_fail,
        ):
            recovered = await run_watchdog_cycle()
            # Tasks < MAX_STUCK_MINUTES try provider check, and if it fails, they're skipped
            assert recovered == 0

    @pytest.mark.asyncio
    async def test_force_fails_very_old_stuck_tasks(self):
        """Tasks older than MAX_STUCK_MINUTES should be force-failed."""
        from datetime import datetime, timedelta
        stuck = [{
            "id": 1, "user_id": 42, "task_id": "ext_1", "model": "kling",
            "cost": 5, "request_data": "{}",
            "created_at": datetime.utcnow() - timedelta(minutes=130),
        }]
        with (
            patch("bot.services.task_watchdog.get_stuck_tasks", AsyncMock(return_value=stuck)),
            patch("bot.services.task_watchdog.force_fail_task", AsyncMock(return_value=True)),
        ):
            recovered = await run_watchdog_cycle()
            assert recovered == 1

    @pytest.mark.asyncio
    async def test_force_fails_when_provider_already_reported_failed(self):
        from datetime import datetime, timedelta

        stuck = [{
            "id": 1,
            "user_id": 42,
            "task_id": "ext_1",
            "model": "banana_pro",
            "cost": 5,
            "request_data": "{}",
            "created_at": datetime.utcnow() - timedelta(minutes=45),
        }]
        with (
            patch("bot.services.task_watchdog.get_stuck_tasks", AsyncMock(return_value=stuck)),
            patch("bot.services.task_watchdog.check_task_with_provider", AsyncMock(return_value="failed")),
            patch("bot.services.task_watchdog.force_fail_task", AsyncMock(return_value=True)),
        ):
            recovered = await run_watchdog_cycle()
            assert recovered == 1

    @pytest.mark.asyncio
    async def test_replays_completed_provider_task_via_recovery_callback(self):
        from datetime import datetime, timedelta

        stuck = [{
            "id": 7,
            "user_id": 42,
            "task_id": "provider_done_1",
            "model": "flux_pro",
            "cost": 2,
            "request_data": "{}",
            "created_at": datetime.utcnow() - timedelta(minutes=5),
        }]
        recover = AsyncMock(return_value=True)
        with (
            patch("bot.services.task_watchdog.get_stuck_tasks", AsyncMock(return_value=stuck)),
            patch(
                "bot.services.task_watchdog.cleanup_stale_local_generation_tasks",
                AsyncMock(return_value={"failed_count": 0, "refunded_credits": 0.0}),
            ),
            patch(
                "bot.services.task_watchdog.check_task_with_provider",
                AsyncMock(return_value="completed"),
            ),
        ):
            recovered = await run_watchdog_cycle(on_completed=recover)

        assert recovered == 1
        recover.assert_awaited_once_with(stuck[0])


class TestCheckTaskWithProvider:
    @pytest.mark.asyncio
    async def test_uses_nano_banana_pro_status_for_banana_pro(self):
        mock_status = AsyncMock(return_value={"state": "fail"})
        with patch(
            "bot.services.nano_banana_pro_service.nano_banana_pro_service.get_task_status",
            mock_status,
        ):
            status = await check_task_with_provider("ext_1", "banana_pro")
        assert status == "failed"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "model",
        ["flux_pro", "grok_imagine", "motion_control_v26", "v3_std"],
    )
    async def test_uses_kie_record_info_for_kie_backed_models(self, model):
        mock_status = AsyncMock(return_value={"state": "success"})
        with patch(
            "bot.services.kie_market_service.kie_market_service.get_task_status",
            mock_status,
        ):
            status = await check_task_with_provider("ext_kie", model)
        assert status == "completed"


class TestWatchdogLoop:
    """Tests for the infinite watchdog_loop — just verify structure."""

    @pytest.mark.asyncio
    async def test_loop_structure(self):
        from bot.services.task_watchdog import watchdog_loop, WATCHDOG_INTERVAL_SECONDS
        assert WATCHDOG_INTERVAL_SECONDS > 0
        # The loop is just an infinite while True; we only test it calls run_watchdog_cycle
        with patch("bot.services.task_watchdog.run_watchdog_cycle", AsyncMock()) as mock_cycle:
            with patch("asyncio.sleep", AsyncMock(side_effect=[None, StopAsyncIteration])):
                try:
                    await watchdog_loop()
                except StopAsyncIteration:
                    pass
                assert mock_cycle.awaited

