"""Tests for bot.services.rate_limiter — sliding window rate limiter."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.services.rate_limiter import (
    _cleanup_loop,
    _client_ip,
    _counters,
    _is_exempt_request,
    _SlidingWindowCounter,
    rate_limiter_middleware,
    start_cleanup_task,
)


class TestSlidingWindowCounter:
    """Unit tests for the sliding window counter internals."""

    def test_init_empty(self):
        c = _SlidingWindowCounter()
        assert c.count() == 0

    def test_hit_increments(self):
        c = _SlidingWindowCounter()
        assert c.hit() == 1
        assert c.hit() == 2
        assert c.count() == 2

    def test_hit_returns_current_count(self):
        c = _SlidingWindowCounter()
        c.hit()
        c.hit()
        assert c.hit() == 3

    def test_prune_empty_does_not_raise(self):
        c = _SlidingWindowCounter()
        c.prune(time.monotonic())  # should not raise

    def test_prune_removes_old_entries(self):
        c = _SlidingWindowCounter()
        # add an old timestamp
        old = time.monotonic() - 120  # 2 min ago, outside 60s window
        c.timestamps.append(old)
        assert c.count() == 0  # pruned during count()
        assert len(c.timestamps) == 0

    def test_prune_fast_path_clears_all(self):
        c = _SlidingWindowCounter()
        old = time.monotonic() - 120
        c.timestamps.append(old)
        c.prune(time.monotonic())
        assert len(c.timestamps) == 0

    def test_hit_after_prune(self):
        c = _SlidingWindowCounter()
        old = time.monotonic() - 120
        c.timestamps.append(old)
        assert c.hit() == 1  # old pruned, new added

    def test_multiple_hits_within_window(self):
        c = _SlidingWindowCounter()
        now = time.monotonic()
        c.timestamps = [now - 10, now - 20, now - 30]
        assert c.count() == 3


class TestClientIP:
    """Tests for _client_ip — IP extraction from request headers."""

    def make_request(self, headers=None, peername=None):
        req = MagicMock()
        req.headers = headers or {}
        transport = MagicMock()
        transport.get_extra_info.return_value = peername
        req.transport = transport
        return req

    def test_x_forwarded_for(self):
        req = self.make_request(
            headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"},
            peername=("10.0.0.1", 54321),
        )
        assert _client_ip(req) == "1.2.3.4"

    def test_x_real_ip(self):
        req = self.make_request(
            headers={"X-Real-IP": "4.3.2.1"},
            peername=("10.0.0.1", 54321),
        )
        assert _client_ip(req) == "4.3.2.1"

    def test_peername_fallback(self):
        req = self.make_request(
            headers={},
            peername=("192.168.1.1", 8888),
        )
        assert _client_ip(req) == "192.168.1.1"

    def test_unknown_when_no_peername(self):
        req = self.make_request(headers={}, peername=None)
        assert _client_ip(req) == "unknown"

    def test_x_forwarded_for_priority(self):
        req = self.make_request(
            headers={"X-Forwarded-For": "8.8.8.8", "X-Real-IP": "1.1.1.1"},
            peername=("10.0.0.1", 54321),
        )
        assert _client_ip(req) == "8.8.8.8"


class TestRateLimiterMiddleware:
    """Tests for rate_limiter_middleware — the actual aiohttp middleware."""

    @pytest.fixture
    def mock_request(self):
        req = MagicMock()
        req.method = "POST"
        req.path = "/webhook"
        peername = ("1.2.3.4", 54321)
        transport = MagicMock()
        transport.get_extra_info.return_value = peername
        req.transport = transport
        req.headers = {}
        return req

    @pytest.fixture
    def clean_counters(self):
        _counters.clear()
        yield
        _counters.clear()

    async def test_passes_through_below_limit(self, mock_request, clean_counters):
        handler = AsyncMock(return_value=MagicMock())
        await rate_limiter_middleware(mock_request, handler)
        handler.assert_awaited_once()

    async def test_exempts_health_endpoint(self, clean_counters):
        req = MagicMock()
        req.method = "GET"
        req.path = "/health"
        req.transport = MagicMock()
        req.transport.get_extra_info.return_value = ("1.2.3.4", 54321)
        req.headers = {}
        handler = AsyncMock(return_value=MagicMock())

        await rate_limiter_middleware(req, handler)
        handler.assert_awaited_once()
        assert _counters["1.2.3.4"].count() == 0

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/uploads/feed/thumbs/a.jpg"),
            ("GET", "/uploads/trend-previews/1/a.mp4"),
            ("GET", "/mini-app/"),
            ("GET", "/mini-app/index.html"),
        ],
    )
    async def test_exempts_static_and_media_fanout(
        self,
        clean_counters,
        method,
        path,
    ):
        req = MagicMock()
        req.method = method
        req.path = path
        req.transport = MagicMock()
        req.transport.get_extra_info.return_value = ("1.2.3.4", 54321)
        req.headers = {}
        handler = AsyncMock(return_value=MagicMock())

        await rate_limiter_middleware(req, handler)

        handler.assert_awaited_once()
        assert _counters["1.2.3.4"].count() == 0

    @pytest.mark.parametrize(
        "path",
        [
            "/mini-app/api/bootstrap",
            "/mini-app/api/client-log",
        ],
    )
    def test_api_routes_still_count_against_limit(self, path):
        req = MagicMock()
        req.method = "POST"
        req.path = path
        assert not _is_exempt_request(req)

    async def test_whitelisted_ip_always_passes(self, clean_counters):
        from bot.services.rate_limiter import _whitelist
        _whitelist.add("9.9.9.9")
        req = MagicMock()
        req.method = "POST"
        req.path = "/webhook"
        req.transport = MagicMock()
        req.transport.get_extra_info.return_value = ("9.9.9.9", 54321)
        req.headers = {}
        handler = AsyncMock(return_value=MagicMock())

        await rate_limiter_middleware(req, handler)
        handler.assert_awaited_once()
        _whitelist.discard("9.9.9.9")

    def test_start_cleanup_task_creates_loop(self):
        """start_cleanup_task should schedule a background task."""
        loop = MagicMock()
        with patch("asyncio.get_event_loop", return_value=loop):
            start_cleanup_task()
            loop.create_task.assert_called_once()
            loop.create_task.call_args.args[0].close()


class TestCleanupLoop:
    """Tests for _cleanup_loop — stale counter eviction."""

    @pytest.mark.asyncio
    async def test_evicts_stale_keys(self):
        _counters.clear()
        c = _SlidingWindowCounter()
        c.timestamps.append(time.monotonic() - 3600)  # very old
        _counters["stale_ip"] = c

        sleep = AsyncMock(side_effect=[None, asyncio.CancelledError()])
        with patch("asyncio.sleep", sleep), pytest.raises(asyncio.CancelledError):
            await _cleanup_loop()
        assert "stale_ip" not in _counters
        _counters.clear()
