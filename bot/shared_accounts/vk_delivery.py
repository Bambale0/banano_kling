"""Owner-only VK delivery status and explicit acceptance for older results."""
import asyncio
import json
import logging
import time

from bot.database import get_task_by_id
from bot.services.vk_result_delivery import VKDeliveryQueue
from bot.services.vk_result_transport import VKResultTransport

from .errors import AuthenticationError
from .policy import load_policy
from .store import get_session, linked_telegram_id

logger = logging.getLogger(__name__)


async def vk_delivery(request):
    from .api import _bearer, _body, response

    policy = await load_policy()
    if not policy.enabled:
        return response({'ok': False, 'error': 'Preview unavailable'}, 404)
    account = await get_session(_bearer(request), policy.revision)
    if account.identity.platform != 'vk' or not policy.allows_public(account.identity):
        raise PermissionError('VK account session required')
    lookup = request.match_info['task_id']
    if len(lookup) > 200:
        return response({'ok': False, 'error': 'Result unavailable'}, 404)
    task = await get_task_by_id(lookup)
    telegram_id = await linked_telegram_id(account.id)
    if not task or telegram_id is None or task.telegram_id != telegram_id:
        return response({'ok': False, 'error': 'Result unavailable'}, 404)
    if task.type not in {'image', 'video'} or task.status != 'completed' or not task.result_url:
        return response({'ok': True, 'delivery': {'state': 'not_applicable', 'can_request': False, 'community_id': None}})
    metadata = json.loads(task.request_data or '{}')
    if not isinstance(metadata, dict) or metadata.get('origin_platform') != 'vk':
        return response({'ok': True, 'delivery': {'state': 'not_applicable', 'can_request': False, 'community_id': None}})
    recipient = metadata.get('origin_vk_user_id')
    if recipient is not None and recipient != account.identity.external_id:
        return response({'ok': False, 'error': 'Result unavailable'}, 404)
    queue = VKDeliveryQueue(VKResultTransport())

    async def current_job():
        async with queue.transaction() as db:
            row = await (await db.execute('SELECT * FROM vk_result_deliveries WHERE task_id = ?', (task.id,))).fetchone()
            return dict(row) if row else None

    job = await current_job()
    configured = VKResultTransport.configured_for(policy.vk_community_id)
    active = policy.vk_result_delivery_enabled and configured
    if request.method == 'POST':
        if not active or job and job['community_id'] != policy.vk_community_id:
            return response({'ok': False, 'error_code': 'vk_delivery_unavailable'}, 409)
        if request.content_length is None or request.content_length > 256:
            return response({'ok': False, 'error_code': 'invalid_request'}, 400)
        async with asyncio.timeout(10):
            body = await _body(request)
        if body:
            return response({'ok': False, 'error_code': 'invalid_request'}, 400)
        fresh_policy = await load_policy()
        fresh = await get_session(_bearer(request), fresh_policy.revision)
        if fresh != account or not fresh_policy.allows_public(fresh.identity):
            raise AuthenticationError('Session changed; reopen the application')
        if job and job['state'] == 'uncertain':
            return response({'ok': False, 'error_code': 'vk_delivery_uncertain'}, 409)
        # Missing legacy snapshot is bound only by this explicit verified owner
        # action, never by a background guess from a Telegram numeric ID.
        if not job:
            old_json = task.request_data or '{}'
            if recipient is None and metadata.get('origin_account_id') is None:
                metadata.update(origin_vk_user_id=account.identity.external_id, origin_account_id=account.id)
            metadata.update(vk_chat_delivery_requested=True, vk_delivery_explicit_requested_at_epoch=int(time.time()))
            async with queue.transaction() as db:
                changed = await db.execute('''UPDATE generation_tasks SET request_data = ? WHERE id = ?
                    AND status = 'completed' AND COALESCE(request_data, '{}') = ?''',
                    (json.dumps(metadata, ensure_ascii=False), task.id, old_json))
                if changed.rowcount != 1:
                    return response({'ok': False, 'error_code': 'vk_delivery_changed'}, 409)
            logger.info('vk_delivery_explicit_acceptance task_id=%s account_id=%s', task.id, account.id)
        if not await queue.enqueue(task.task_id):
            return response({'ok': False, 'error_code': 'vk_delivery_changed'}, 409)
        if job and job['state'] in {'permission_required', 'failed', 'configuration_required', 'access_revoked'}:
            async with queue.transaction() as db:
                await db.execute('''UPDATE vk_result_deliveries SET state = 'pending', attempts = 0,
                    next_attempt_epoch = 0, lease_until_epoch = 0, reason = 'owner_requested', updated_at_epoch = ?
                    WHERE task_id = ? AND state IN ('permission_required','failed','configuration_required','access_revoked')''',
                    (int(time.time()), task.id))
        job = await current_job()
    state = job['state'] if job else 'not_requested'
    if state not in {'delivered', 'uncertain'} and not active:
        state = 'disabled' if not policy.vk_result_delivery_enabled else 'configuration_required'
    elif state not in {'delivered', 'uncertain'} and job and job['community_id'] != policy.vk_community_id:
        state = 'configuration_required'
    can_request = bool(active and state not in {'uncertain', 'delivered', 'sending', 'preparing', 'pending'}
                       and (not job or job['community_id'] == policy.vk_community_id))
    community_id = job['community_id'] if job else policy.vk_community_id
    representation = ('photo' if job['attachment'] else 'link') if job and job['prepared'] else None
    return response({'ok': True, 'delivery': {'state': state, 'community_id': community_id,
                                            'can_request': can_request, 'representation': representation}})
