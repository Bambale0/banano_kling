import asyncio
import logging
import time
from typing import Optional
from urllib.parse import urlparse

from bot.config import config

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as redis
except Exception:  # pragma: no cover - optional dependency fallback
    redis = None


def _safe_redis_url(value: str) -> str:
    parsed = urlparse(str(value or ""))
    if not parsed.scheme:
        return "[not configured]"
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return f"{parsed.scheme}://{host}{parsed.path or ''}"


class RedisService:
    """Small async Redis wrapper with graceful fallback when Redis is unavailable."""

    def __init__(self):
        self._client = None
        self._retry_at = 0.0
        self._connect_lock = asyncio.Lock()
        self._warned_unavailable = False

    def build_key(self, suffix: str) -> str:
        return f"{config.REDIS_PREFIX}:{suffix}"

    async def get_client(self):
        if redis is None:
            if redis is None and not self._warned_unavailable:
                logger.warning("redis package is unavailable, Redis cache disabled")
                self._warned_unavailable = True
            return None

        if self._client is not None:
            return self._client
        if time.monotonic() < self._retry_at:
            return None
        async with self._connect_lock:
            if self._client is not None:
                return self._client
            if time.monotonic() < self._retry_at:
                return None
            client = None
            try:
                client = redis.from_url(
                    config.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    health_check_interval=30,
                )
                await client.ping()
                self._client = client
                logger.info("Redis connected: %s", _safe_redis_url(config.redis_url))
            except Exception as exc:  # noqa: BLE001 - optional cache fails open and reconnects
                logger.warning("Redis connection unavailable: error_type=%s", type(exc).__name__)
                self._retry_at = time.monotonic() + max(0.0, config.REDIS_RECOVERY_INTERVAL_SECONDS)
                if client is not None:
                    try:
                        await client.aclose()
                    except Exception:
                        logger.debug("Failed to close unavailable Redis client", exc_info=True)
                return None

        return self._client

    async def get(self, key: str) -> Optional[str]:
        client = await self.get_client()
        if client is None:
            return None
        try:
            value = await client.get(key)
            return value if isinstance(value, str) and value else None
        except Exception:
            logger.exception("Redis GET failed for key=%s", key)
            return None

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> bool:
        client = await self.get_client()
        if client is None:
            return False
        try:
            await client.set(key, value, ex=ttl_seconds)
            return True
        except Exception:
            logger.exception("Redis SET failed for key=%s", key)
            return False

    async def delete(self, key: str) -> bool:
        client = await self.get_client()
        if client is None:
            return False
        try:
            await client.delete(key)
            return True
        except Exception:
            logger.exception("Redis DELETE failed for key=%s", key)
            return False

    async def close(self):
        if self._client is None:
            return
        try:
            await self._client.aclose()
        except Exception:
            logger.exception("Failed to close Redis client")
        finally:
            self._client = None


redis_service = RedisService()
