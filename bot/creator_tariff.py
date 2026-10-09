"""Server-owned Seedance price profiles and immutable per-launch quotes.

Membership grants pricing only. Missing/disabled/invalid configuration uses
ordinary rates; no creator economics are supplied by code or by a client.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any

from bot.config import config
from bot.model_capabilities import get_video_capability
from bot.services.preset_manager import preset_manager
from bot.video_reference_policy import apply_video_reference_cost

CREATOR_MODELS = ('seedance_2', 'seedance_2_5')


def _required_qualities(raw: dict[str, Any] | None = None) -> dict[str, list[str]]:
    ordinary = preset_manager.get_price_config().get('costs_reference', {}).get('video_models', {})
    models = (raw or {}).get('video_models', {})
    if not isinstance(models, dict):
        models = {}
    result = {}
    for model in CREATOR_MODELS:
        capability = get_video_capability(model)
        keys = set(capability.resolutions or ('720p',)) if capability else {'720p'}
        for entry in (ordinary.get(model, {}), models.get(model, {})):
            rates = entry.get('quality_costs', {}) if isinstance(entry, dict) else {}
            if isinstance(rates, dict):
                keys.update(str(key).strip().lower() for key in rates)
        result[model] = sorted(keys, key=lambda q: (len(q), q))
    return result


def _parse_config(raw: Any) -> tuple[dict[str, Any], list[str], list[str]]:
    if not isinstance(raw, dict):
        return {'enabled': False, 'video_models': {}}, ['Тариф не настроен'], []
    enabled = raw.get('enabled', False)
    invalid = []
    if not isinstance(enabled, bool):
        invalid.append('enabled должен быть логическим значением')
        enabled = False
    models = raw.get('video_models', {})
    if not isinstance(models, dict):
        invalid.append('video_models должен быть объектом')
        models = {}
    if set(models) - set(CREATOR_MODELS):
        invalid.append('Креаторский тариф поддерживает только Seedance 2.0 и 2.5')
    normalized = {'enabled': enabled, 'video_models': {}}
    missing = []
    for model, qualities in _required_qualities(raw).items():
        entry = models.get(model, {})
        if not isinstance(entry, dict):
            invalid.append(f'{model}: настройки должны быть объектом')
            entry = {}
        rates = entry.get('quality_costs', {})
        if not isinstance(rates, dict):
            invalid.append(f'{model}: quality_costs должен быть объектом')
            rates = {}
        normalized_rates = {}
        for quality, rate in rates.items():
            key = str(quality).strip().lower()
            if not key or len(key) > 20 or not key.replace('_', '').isalnum():
                invalid.append(f'{model}: неверное качество')
                continue
            try:
                numeric_rate = float(rate)
            except (TypeError, ValueError, OverflowError):
                numeric_rate = float("nan")
            if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(numeric_rate) or numeric_rate <= 0:
                invalid.append(f'{model}/{key}: нужна конечная положительная цена')
                continue
            capability = get_video_capability(model)
            minimum = min(d for d in capability.durations if d > 0) if capability else 4
            maximum = max(d for d in capability.durations if d > 0) if capability else 30
            ordinary = preset_manager.get_price_config().get('costs_reference', {}).get('video_models', {}).get(model, {})
            maximum = max(maximum, int(ordinary.get('duration_max', 30) or 30))
            # Existing half-credit rounding multiplies by 2, then references
            # multiply the total by 2. Reject overflow for every allowed length.
            if not math.isfinite(numeric_rate * maximum * 4):
                invalid.append(f'{model}/{key}: цена слишком велика для расчёта')
                continue
            total = numeric_rate * minimum
            if preset_manager._format_cost(total) <= 0:
                invalid.append(f'{model}/{key}: цена после округления должна быть больше нуля')
                continue
            normalized_rates[key] = numeric_rate
        if model in models:
            normalized['video_models'][model] = {'quality_costs': normalized_rates}
        for quality in qualities:
            if quality not in normalized_rates:
                missing.append(f'{model}/{quality}: цена не задана')
    return normalized, missing, invalid


def validate_creator_tariff_config(raw: Any) -> dict[str, Any]:
    normalized, missing, invalid = _parse_config(raw)
    if invalid or (normalized['enabled'] and missing):
        raise ValueError('; '.join(invalid + (missing if normalized['enabled'] else [])))
    return deepcopy(normalized)


def creator_tariff_status() -> dict[str, Any]:
    raw = preset_manager.get_price_config().get('creator_tariff', {})
    normalized, missing, invalid = _parse_config(raw)
    return {
        **normalized,
        'configured': not missing and not invalid,
        'required_qualities': _required_qualities(raw if isinstance(raw, dict) else {}),
        'errors': invalid + missing,
    }


async def get_actor_tariff(telegram_id: int | None) -> str:
    """Resolve only from authenticated actor identity and server membership."""
    if telegram_id is None:
        return 'standard'
    if config.is_admin(int(telegram_id)):
        return 'admin'
    status = creator_tariff_status()
    if not status['enabled'] or not status['configured']:
        return 'standard'
    from bot.creator_tariff_membership import get_creator_tariff_membership
    return 'creator' if await get_creator_tariff_membership(int(telegram_id)) else 'standard'


def video_quality_rates(model: str, *, tariff: str = 'standard') -> dict[str, float]:
    model = preset_manager.normalize_video_model_key(model)
    rates = preset_manager.get_video_quality_costs(model)
    status = creator_tariff_status()
    if tariff == 'creator' and model in CREATOR_MODELS and status['enabled'] and status['configured']:
        rates.update(status['video_models'][model]['quality_costs'])
    return rates


@dataclass(frozen=True, slots=True)
class VideoQuote:
    model: str
    duration: int
    quality: str | None
    cost: float
    charge_cost: float
    profile: str
    base_cost: float
    reference_multiplier: float
    revision: str
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_video_quote(
    model: str,
    duration: int = 5,
    quality: str | None = None,
    video_references: Iterable[str] | None = None,
    *,
    tariff: str = 'standard',
) -> VideoQuote:
    """Pure quote seam. ``tariff`` is supplied only by authenticated server code."""
    if tariff not in {'standard', 'creator', 'admin'}:
        raise ValueError('Unknown server price profile')
    model = preset_manager.normalize_video_model_key(model)
    quality = str(quality).strip().lower() if quality else None
    duration = 5 if int(duration) == -1 and model == 'seedance_2_5' else int(duration)
    prices = preset_manager.get_price_config()
    ordinary_model = prices.get('costs_reference', {}).get('video_models', {}).get(model, {})
    billable_duration = preset_manager._clamp_video_duration(duration, ordinary_model)
    profile = 'admin' if tariff == 'admin' else 'standard'
    base_cost = float(preset_manager.get_video_cost_with_quality(model, duration, quality))
    status = creator_tariff_status()
    creator_model = status['video_models'].get(model, {})
    rate = creator_model.get('quality_costs', {}).get(quality or '720p')
    if tariff == 'creator' and model in CREATOR_MODELS and status['enabled'] and status['configured'] and rate is not None:
        candidate = float(preset_manager._format_cost(float(rate) * billable_duration))
        if math.isfinite(candidate) and candidate > 0:
            base_cost = candidate
            profile = 'creator'
    multiplier = float(apply_video_reference_cost(model, 1.0, video_references))
    cost = base_cost * multiplier
    if not math.isfinite(cost) or cost <= 0:
        raise ValueError('Generation price must be finite and positive')
    revision_data = {'profile': profile, 'model': model, 'ordinary': ordinary_model, 'creator': creator_model if profile == 'creator' else None}
    revision = hashlib.sha256(json.dumps(revision_data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16]
    return VideoQuote(model, billable_duration, quality, cost, 0.0 if profile == 'admin' else cost, profile, base_cost, multiplier, revision)


async def quote_video_for_actor(
    telegram_id: int,
    model: str,
    duration: int = 5,
    quality: str | None = None,
    video_references: Iterable[str] | None = None,
) -> VideoQuote:
    return resolve_video_quote(model, duration, quality, video_references, tariff=await get_actor_tariff(telegram_id))
