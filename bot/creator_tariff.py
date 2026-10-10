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
STRICT_QUALITY_PRICED_VIDEO_MODELS = {'wan_3_prime', 'wan_3'}


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
    billing_mode: str | None = None
    input_seconds: float | None = None
    selected_output_seconds: float | None = None
    billable_seconds: float | None = None
    rate: float | None = None
    references_fingerprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if self.version == 1:
            # Preserve the exact historical snapshot representation.
            for key in ("billing_mode", "input_seconds", "selected_output_seconds",
                        "billable_seconds", "rate", "references_fingerprint"):
                result.pop(key)
        return result


def resolve_video_quote(
    model: str,
    duration: int = 5,
    quality: str | None = None,
    video_references: Iterable[str] | None = None,
    *,
    tariff: str = 'standard',
    input_video_seconds: float | None = None,
    references_fingerprint: str | None = None,
    selected_output_seconds: float | None = None,
) -> VideoQuote:
    """Pure quote seam. ``tariff`` is supplied only by authenticated server code."""
    if tariff not in {'standard', 'creator', 'admin'}:
        raise ValueError('Unknown server price profile')
    model = preset_manager.normalize_video_model_key(model)
    quality = str(quality).strip().lower() if quality else None
    # Normal Seedance 2 launches send 720p to the provider without a quality
    # selector. Price that same resolution for every quote consumer; otherwise
    # admin edits to its per-second rate lose to legacy duration totals.
    # The pricing manager still falls back to legacy totals when no rate exists.
    if model == 'seedance_2' and not quality:
        quality = '720p'
    if input_video_seconds is not None:
        return _measured_video_quote(
            model, duration, quality, tariff=tariff,
            input_seconds=input_video_seconds,
            selected_output_seconds=selected_output_seconds,
            references_fingerprint=references_fingerprint,
        )
    duration = (
        5 if int(duration) == -1 and model == 'seedance_2_5'
        else 30 if int(duration) == -1 and model in {'wan_3_prime', 'wan_3'}
        else int(duration)
    )
    prices = preset_manager.get_price_config()
    ordinary_model = prices.get('costs_reference', {}).get('video_models', {}).get(model, {})
    if model in STRICT_QUALITY_PRICED_VIDEO_MODELS:
        quality_key = quality or '1080p'
        quality_lookup = {
            str(key).strip().lower(): value
            for key, value in (ordinary_model.get('quality_costs', {}) if isinstance(ordinary_model, dict) else {}).items()
        }
        if quality_key not in quality_lookup:
            if tariff == 'admin':
                billable_duration = duration if int(duration) == 30 else preset_manager._clamp_video_duration(duration, ordinary_model)
                revision_data = {'profile': 'admin', 'model': model, 'ordinary': ordinary_model, 'creator': None, 'missing_quality': quality_key}
                revision = hashlib.sha256(json.dumps(revision_data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16]
                return VideoQuote(model, billable_duration, quality, 0.0, 0.0, 'admin', 0.0, 1.0, revision)
            raise ValueError('Generation price is not configured for this model quality')
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
    *,
    input_video_seconds: float | None = None,
    references_fingerprint: str | None = None,
    selected_output_seconds: float | None = None,
) -> VideoQuote:
    return resolve_video_quote(
        model, duration, quality, video_references,
        tariff=await get_actor_tariff(telegram_id),
        input_video_seconds=input_video_seconds,
        references_fingerprint=references_fingerprint,
        selected_output_seconds=selected_output_seconds,
    )


def _measured_video_quote(
    model: str, duration: int, quality: str | None, *, tariff: str,
    input_seconds: float, selected_output_seconds: float | None,
    references_fingerprint: str | None,
) -> VideoQuote:
    """Opt-in v2: server-measured input plus selected/source-locked output.

    Output validation belongs to the provider recipe validator. Never clamp the
    sum using output-only duration limits, or reinterpret a free Auto as 5s.
    """
    if model not in CREATOR_MODELS:
        raise ValueError("Measured quote is not enabled for this model")
    output = float(duration if selected_output_seconds is None else selected_output_seconds)
    source = float(input_seconds)
    if (isinstance(input_seconds, bool) or not math.isfinite(source) or source < 0
            or not math.isfinite(output) or output <= 0):
        raise ValueError("A measured input and explicit output duration are required")
    if not references_fingerprint or len(references_fingerprint) != 64:
        raise ValueError("Verified video-reference fingerprint is required")
    status = creator_tariff_status()
    profile = "admin" if tariff == "admin" else "standard"
    if tariff == "creator" and status["enabled"] and status["configured"]:
        profile = "creator"
    rates = video_quality_rates(model, tariff=profile)
    raw_rate = rates.get(quality or "720p")
    if isinstance(raw_rate, bool) or raw_rate is None:
        raise ValueError("Generation price is not configured for this model quality")
    rate = float(raw_rate)
    total = source + output
    if not math.isfinite(rate) or rate <= 0 or not math.isfinite(rate * total):
        raise ValueError("Generation price must be finite and positive")
    cost = float(preset_manager._format_cost(rate * total))
    if cost <= 0:
        raise ValueError("Generation price must be positive after rounding")
    revision_data = {"version": 2, "profile": profile, "model": model,
                     "quality": quality, "rate": rate}
    revision = hashlib.sha256(json.dumps(revision_data, sort_keys=True).encode()).hexdigest()[:16]
    return VideoQuote(
        model, duration, quality, cost, 0.0 if profile == "admin" else cost,
        profile, cost, 1.0, revision, version=2,
        billing_mode="input_plus_selected_output", input_seconds=source,
        selected_output_seconds=output, billable_seconds=total, rate=rate,
        references_fingerprint=references_fingerprint,
    )
