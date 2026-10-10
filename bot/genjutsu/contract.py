"""Pure, versioned plan validation and credit quotes; no network or database I/O."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID


class PipelineError(ValueError):
    def __init__(self, code: str, *, status: int = 400):
        self.code = code
        self.status = status
        super().__init__(code)


CATALOG = json.loads(Path(__file__).with_name('catalog.json').read_text())

# Bump when the charging formula changes; stale, unused quotes must be rejected.
GENJUTSU_PRICING_VERSION = 2


def default_settings() -> dict[str, Any]:
    return json.loads(Path(__file__).with_name('defaults.json').read_text())


def fingerprint(value: Any) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(',', ':'),
                            ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(serialized.encode()).hexdigest()


def integer(value: Any, low: int, high: int, code: str) -> int:
    # bool is an int subclass, but is not a valid amount/duration/count.
    if type(value) is not int or not low <= value <= high:
        raise PipelineError(code)
    return value


def object_fields(value: Any, allowed: set[str], code: str) -> dict:
    if not isinstance(value, dict) or set(value) - allowed:
        raise PipelineError(code)
    return value


def text(value: Any, limit: int, code: str) -> str:
    if not isinstance(value, str) or len(value) > limit or '\x00' in value:
        raise PipelineError(code)
    return value


# These keys and substitutions are a closed protocol, not configurable policy.
NOTIFICATION_TEMPLATE_FIELDS = {
    'failed': None, 'canceled': None, 'partial': None,
    'moderation': None, 'provider_failure': None, 'technical_failure': None,
    'canceled_steps': None, 'no_charge': None, 'details': None,
    'refund': '{refunded_credits}', 'charge': '{charged_credits}',
}


def validate_notification_templates(raw: Any) -> dict[str, str]:
    code = 'invalid_notification_templates'
    if not isinstance(raw, dict) or set(raw) != set(NOTIFICATION_TEMPLATE_FIELDS):
        raise PipelineError(code)
    for key, placeholder in NOTIFICATION_TEMPLATE_FIELDS.items():
        value = raw[key]
        if (not isinstance(value, str) or not value.strip()
                or any(unicodedata.category(char).startswith('C') and char != '\n' for char in value)):
            raise PipelineError(code)
        # Count like the browser's maxLength, bounding even astral emoji.
        # At most eight lines are selected, safely below Telegram's text limit.
        if len(value.encode('utf-16-le')) // 2 > 300:
            raise PipelineError(code)
        if placeholder is not None and value.count(placeholder) != 1:
            raise PipelineError(code)
        literal = value.replace(placeholder, '') if placeholder is not None else value
        if '{' in literal or '}' in literal:
            raise PipelineError(code)
    return dict(raw)


def validate_settings(raw: Mapping[str, Any]) -> dict[str, Any]:
    defaults = default_settings()
    object_fields(raw, set(defaults), 'invalid_settings')
    data = copy.deepcopy(defaults)
    data.update(copy.deepcopy(raw))
    data['notification_templates'] = validate_notification_templates(data['notification_templates'])
    for key in ('public_enabled', 'admin_enabled'):
        if type(data[key]) is not bool:
            raise PipelineError('invalid_settings')
    ranges = {
        'owner_storage_bytes': (1024, 1099511627776), 'total_storage_bytes': (1024, 10995116277760),
        'max_parallel_uploads': (1, 10), 'media_parallelism': (1, 8),
        'max_steps': (1, 10), 'max_variants': (1, 10),
        'max_active_runs_per_user': (1, 20), 'max_active_provider_tasks': (1, 100),
        'quote_ttl_seconds': (30, 3600), 'lease_seconds': (120, 900),
        'poll_seconds': (2, 120), 'request_timeout_seconds': (5, 90),
        'media_timeout_seconds': (10, 300), 'input_url_ttl_seconds': (3600, 604800),
        'preview_url_ttl_seconds': (300, 86400), 'presets_ttl_seconds': (30, 3600),
        'unknown_review_seconds': (60, 86400), 'max_quote_credits': (1, 1000000),
        'provider_retry_deadline_seconds': (300, 86400),
        'notification_max_attempts': (1, 20),
        'notification_retry_deadline_seconds': (60, 86400),
        'upload_video_bytes': (1024, 209715200), 'upload_image_bytes': (1024, 67108864),
        'upload_audio_bytes': (1024, 67108864), 'result_max_bytes': (1024, 536870912),
        'max_source_duration_ms': (30000, 3600000),
    }
    for key, bounds in ranges.items():
        integer(data[key], *bounds, 'invalid_settings')
    if data['lease_seconds'] <= max(data['request_timeout_seconds'], data['media_timeout_seconds']) + 20:
        raise PipelineError('lease_too_short')
    operations = data['verified_operations']
    if not isinstance(operations, list) or any(op not in CATALOG for op in operations):
        raise PipelineError('invalid_settings')
    if not isinstance(data['prices'], dict) or set(data['prices']) != set(CATALOG):
        raise PipelineError('invalid_prices')
    for op, caps in CATALOG.items():
        rates = data['prices'][op]
        if not isinstance(rates, dict) or set(rates) != set(caps['resolutions']):
            raise PipelineError('invalid_prices')
        for value in rates.values():
            if value is not None:
                integer(value, 1, 10000, 'invalid_prices')
    return data


def asset_ids(plan: dict) -> set[str]:
    if not isinstance(plan, dict) or not isinstance(plan.get('steps', []), list):
        raise PipelineError('invalid_plan')
    values = [plan.get('source_asset_id')]
    for step in plan.get('steps', []):
        if not isinstance(step, dict) or not isinstance(step.get('references', []), list):
            raise PipelineError('invalid_step')
        for ref in step.get('references', []):
            if not isinstance(ref, dict):
                raise PipelineError('invalid_reference')
            values.append(ref.get('asset_id'))
    if any(value is not None and (not isinstance(value, str) or len(value) > 100) for value in values):
        raise PipelineError('invalid_asset_id')
    return {value for value in values if value}


def compile_plan(raw: dict, assets: Mapping[str, dict], settings: dict,
                 *, presets: set[str] | None = None) -> dict:
    object_fields(raw, {'source_asset_id', 'steps', 'variants', 'continuation'}, 'invalid_plan')
    source_id = text(raw.get('source_asset_id'), 100, 'source_required')
    source = assets.get(source_id)
    if not source or source['kind'] != 'video':
        raise PipelineError('source_unavailable', status=404)
    steps = raw.get('steps')
    if not isinstance(steps, list) or not 1 <= len(steps) <= settings['max_steps']:
        raise PipelineError('invalid_steps')
    variants = integer(raw.get('variants', 1), 1, settings['max_variants'], 'invalid_variants')
    continuation = raw.get('continuation', 'automatic')
    if continuation not in ('automatic', 'manual'):
        raise PipelineError('invalid_continuation')
    result = {'source_asset_id': source_id, 'steps': [], 'variants': variants,
              'continuation': continuation}
    for index, item in enumerate(steps):
        object_fields(item, {'operation', 'resolution', 'prompt', 'preserve',
                             'references', 'preset_id'}, 'invalid_step')
        op = item.get('operation')
        if not isinstance(op, str) or op not in CATALOG:
            raise PipelineError('unsupported_operation')
        caps = CATALOG[op]
        resolution = item.get('resolution', '720p')
        if resolution not in caps['resolutions']:
            raise PipelineError('unsupported_resolution')
        prompt = text(item.get('prompt', ''), caps['max_prompt_length'], 'prompt_too_long')
        preserve = text(item.get('preserve', ''), 2000, 'preserve_too_long')
        refs = item.get('references', [])
        if not isinstance(refs, list) or not caps['min_images'] <= len(refs) <= caps['max_images']:
            raise PipelineError('invalid_reference_count')
        normalized = []
        seen = set()
        for ref in refs:
            object_fields(ref, {'asset_id', 'role', 'label', 'binding'}, 'invalid_reference')
            aid = text(ref.get('asset_id'), 100, 'reference_required')
            if aid not in assets or assets[aid]['kind'] != 'image':
                raise PipelineError('reference_unavailable', status=404)
            if aid in seen:
                raise PipelineError('duplicate_reference')
            seen.add(aid)
            role = ref.get('role', 'character')
            if role not in caps['roles']:
                raise PipelineError('unsupported_reference_role')
            binding = ref.get('binding', 'user')
            if binding not in ('user', 'fixed'):
                raise PipelineError('invalid_reference_binding')
            normalized.append({'asset_id': aid, 'role': role,
                               'label': text(ref.get('label', ''), 200, 'reference_label_too_long'),
                               'binding': binding})
        preset = item.get('preset_id')
        if op == 'restyle':
            try:
                preset = str(UUID(text(preset, 36, 'preset_required')))
            except (ValueError, AttributeError, TypeError) as exc:
                raise PipelineError('preset_required') from exc
            if presets is not None and preset not in presets:
                raise PipelineError('preset_unavailable')
        elif preset is not None:
            raise PipelineError('preset_not_supported')
        compiled = {'operation': op, 'resolution': resolution, 'prompt': prompt,
                    'preserve': preserve, 'references': normalized, 'preset_id': preset}
        # Role guidance is explicit text, not a fabricated provider field.
        provider_prompt(compiled)
        if index == 0:
            validate_duration(source['duration_ms'], op)
            if op == 'object_swap':
                width = source.get('width')
                height = source.get('height')
                if (
                    type(width) is not int
                    or type(height) is not int
                    or width * height < caps['minimum_source_pixels']
                ):
                    raise PipelineError('source_resolution_too_low')
        result['steps'].append(compiled)
    return result


def validate_duration(duration_ms: int, operation: str) -> None:
    caps = CATALOG[operation]
    integer(duration_ms, caps['minimum_video_ms'], caps['maximum_video_ms'], 'invalid_video_duration')


def provider_prompt(step: dict) -> str:
    parts = [step['prompt']] if step['prompt'] else []
    if step.get('preserve'):
        parts.append('Preserve: ' + step['preserve'])
    for i, ref in enumerate(step['references'], 1):
        if ref.get('label'):
            parts.append(f"Image {i}: {ref['role']} - {ref['label']}")
    result = '\n'.join(parts)
    if len(result) > CATALOG[step['operation']]['max_prompt_length']:
        raise PipelineError('compiled_prompt_too_long')
    return result


def provider_input(step: dict, video_url: str, image_urls: list[str]) -> dict:
    if len(image_urls) != len(step['references']):
        raise PipelineError('reference_transport_mismatch')
    payload = {'video_url': video_url, 'image_urls': list(image_urls),
               'prompt': provider_prompt(step), 'resolution': step['resolution']}
    if step['operation'] == 'restyle':
        payload['preset_id'] = step['preset_id']
    return payload


def billable_seconds(reference_duration_ms: int, generation_duration_ms: int) -> tuple[int, int, int]:
    """Bill the video reference and requested generated video separately.

    Higgsfield Genjutsu currently has no independent output-duration input: the
    generated clip follows the selected reference clip. Its callers therefore
    pass the effective source duration for both arguments.
    """
    for duration in (reference_duration_ms, generation_duration_ms):
        if type(duration) is not int or duration <= 0:
            raise PipelineError('invalid_video_duration')
    reference = (reference_duration_ms + 999) // 1000
    generation = (generation_duration_ms + 999) // 1000
    return reference, generation, reference + generation


def quote_plan(plan: dict, assets: Mapping[str, dict], settings: dict) -> dict:
    allocations = []
    for variant in range(plan['variants']):
        for index, step in enumerate(plan['steps']):
            op = step['operation']
            duration = (assets[plan['source_asset_id']]['duration_ms'] if index == 0
                        else CATALOG[op]['maximum_video_ms'])
            reference_seconds, generation_seconds, seconds = billable_seconds(duration, duration)
            rate = settings['prices'][op][step['resolution']]
            if rate is None:
                raise PipelineError('price_not_configured', status=503)
            integer(rate, 1, 10000, 'invalid_prices')
            allocations.append({'variant': variant, 'ordinal': index,
                                'operation': op, 'billable_seconds': seconds,
                                'reference_seconds': reference_seconds,
                                'generation_seconds': generation_seconds,
                                'credits_per_second': rate, 'reserved_credits': seconds * rate,
                                'maximum_reserve': index > 0})
    total = sum(a['reserved_credits'] for a in allocations)
    if total > settings['max_quote_credits']:
        raise PipelineError('quote_budget_exceeded')
    return {'total_credits': total, 'allocations': allocations,
            'pricing_version': GENJUTSU_PRICING_VERSION,
            'plan_hash': fingerprint(plan)}


def request_key(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', value):
        raise PipelineError('invalid_request_key')
    return value
