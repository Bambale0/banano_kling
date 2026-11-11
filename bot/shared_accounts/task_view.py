"""Native VK tasks projected into the SAME Mini App history card contract.

This is a view only. The native SQLite DB remains authoritative for tasks
and credits. Namespaced IDs prevent accidental Telegram/VK task collisions.
"""
from __future__ import annotations

import math
from urllib.parse import urlsplit

_STATUSES = {
    'pending': 'pending',
    'submitting': 'pending',
    'processing': 'pending',
    'completed': 'completed',
    'failed': 'failed',
    'cancelled': 'failed',
}
_TYPES = {'photo': 'image', 'image': 'image', 'video': 'video',
          'ref_video': 'video', 'motion_control': 'video'}


def serialize_native_vk_tasks(tasks: list[dict], *, strict: bool = True) -> list[dict]:
    if not isinstance(tasks, list) or len(tasks) > 40:
        raise ValueError('Invalid native VK history')
    result = []
    seen: set[int] = set()
    for row in tasks:
        if not isinstance(row, dict):
            if strict:
                raise TypeError('Invalid native VK history row')
            continue
        task_id = row.get('task_id')
        cost = row.get('cost')
        model = row.get('model')
        status = row.get('status')
        task_type = row.get('task_type')
        timestamp = row.get('created_at')
        url = row.get('result_url')
        if (type(task_id) is not int or not 0 < task_id < 2**63
            or task_id in seen or type(cost) not in (float, int)
            or not math.isfinite(cost) or cost < 0 or cost > 2**53
            or not isinstance(model, str) or not 1 <= len(model) <= 120
            or any(ord(c) < 32 for c in model)
            or status not in _STATUSES or task_type not in _TYPES
            or not isinstance(timestamp, str) or not 1 <= len(timestamp) <= 100):
            if strict:
                raise ValueError('Invalid native VK task history')
            continue
        if url is not None:
            if not isinstance(url, str) or len(url) > 4096:
                if strict:
                    raise ValueError('Invalid VK media URL')
                continue
            parts = urlsplit(url)
            if (parts.scheme not in {'http', 'https'} or not parts.hostname
                or parts.username is not None or parts.password is not None):
                if strict:
                    raise ValueError('Invalid VK media URL')
                continue
        seen.add(task_id)
        result.append({
            'task_id': f'vk:{task_id}',
            'type': _TYPES[task_type],
            'model': model,
            'model_label': model,
            # Native status endpoint does not provide ratio or original
            # prompt. Do NOT invent private recipe or metadata.
            'aspect_ratio': '',
            'status': _STATUSES[status],
            'result_url': url,
            'created_at': timestamp,
            'prompt_preview': '',
            'cost': cost,
        })
    return result
