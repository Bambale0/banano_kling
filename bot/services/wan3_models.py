"""Immutable provider identity for the two distinct Wan 3.0 models."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class Wan3ModelSpec:
    key: str
    provider_model: str
    label: str


WAN3_MODELS = MappingProxyType({
    "wan_3_prime": Wan3ModelSpec("wan_3_prime", "wan/3-0-video-prime", "Wan 3.0 Video Prime"),
    "wan_3": Wan3ModelSpec("wan_3", "wan/3-0-video", "Wan 3.0 Video"),
})
_ALIASES = {
    "wan3_prime": "wan_3_prime", "wan/3-0-video-prime": "wan_3_prime",
    "wan3": "wan_3", "wan/3-0-video": "wan_3",
}


def wan3_model_spec(value: str | None = None) -> Wan3ModelSpec:
    key = str(value or "wan_3_prime").strip()
    key = _ALIASES.get(key, key)
    if key not in WAN3_MODELS:
        raise ValueError("Unknown Wan 3.0 model")
    return WAN3_MODELS[key]


def wan3_service_for_model(value: str | None = None):
    spec = wan3_model_spec(value)
    if spec.key == "wan_3":
        from bot.services.wan3_standard_service import wan3_standard_service

        return wan3_standard_service
    from bot.services.wan3_prime_service import wan3_prime_service

    return wan3_prime_service
