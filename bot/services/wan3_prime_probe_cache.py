"""Bound repeated quote I/O; reuse metadata only for a verified immutable file."""
from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from weakref import WeakKeyDictionary

from bot.services.wan3_prime_media import MediaInfo, Wan3PrimeValidationError
from bot.services.wan3_prime_storage_policy import positive_setting


@dataclass
class _LoopState:
    active: int = 0
    users: dict[int, int] = field(default_factory=dict)
    verified: OrderedDict[tuple, MediaInfo] = field(default_factory=OrderedDict)


_STATES: WeakKeyDictionary = WeakKeyDictionary()


def _state() -> _LoopState:
    loop = asyncio.get_running_loop()
    if loop not in _STATES:
        _STATES[loop] = _LoopState()
    return _STATES[loop]


@asynccontextmanager
async def probe_slot(user_id: int):
    """Bound per-worker expensive I/O with no unbounded waiter/task queue."""
    state = _state()
    if (state.active >= positive_setting('WAN3_PROBE_GLOBAL_CONCURRENCY', 4)
            or state.users.get(user_id, 0) >= positive_setting('WAN3_PROBE_USER_CONCURRENCY', 1)):
        raise Wan3PrimeValidationError('Too many concurrent media checks; retry shortly', status=429)
    state.active += 1
    state.users[user_id] = state.users.get(user_id, 0) + 1
    try:
        yield
    finally:
        state.active -= 1
        state.users[user_id] -= 1
        if not state.users[user_id]:
            del state.users[user_id]


def _signature(local: Path) -> tuple:
    stat = local.stat()
    return (str(local), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


async def verified_metadata(row, local: Path, hash_file) -> MediaInfo:
    state = _state()
    try:
        signature = _signature(local)
        key = (row['sha256'], row['media_info'], *signature)
        if key in state.verified:
            state.verified.move_to_end(key)
            return state.verified[key]
        async with probe_slot(int(row['user_id'])):
            hash_task = asyncio.create_task(asyncio.to_thread(hash_file, local))
            try:
                digest = await asyncio.shield(hash_task)
            except asyncio.CancelledError:
                # A disconnected HTTP client must not free its admission slot
                # while the underlying thread still consumes disk bandwidth.
                await asyncio.shield(hash_task)
                raise
            if digest != row['sha256'] or _signature(local) != signature:
                raise Wan3PrimeValidationError('Owned media has changed; upload it again', status=409)
            # Upload/finalization already ran format, duration and dimensions
            # validation. Metadata is backend-owned, never copied from a client.
            try:
                info = MediaInfo(**json.loads(row['media_info']))
            except (ValueError, TypeError) as exc:
                raise Wan3PrimeValidationError('Stored media metadata is invalid; upload again', status=409) from exc
            if info.kind != row['kind'] or info.size_bytes != signature[3]:
                raise Wan3PrimeValidationError('Stored media metadata has changed; upload again', status=409)
            info = replace(info, path=str(local), url=row['public_url'], sha256=digest)
            state.verified[key] = info
            while len(state.verified) > positive_setting('WAN3_VERIFIED_MEDIA_CACHE_ENTRIES', 2048):
                state.verified.popitem(last=False)
            return info
    except OSError as exc:
        raise Wan3PrimeValidationError('Owned media is no longer available', status=409) from exc
