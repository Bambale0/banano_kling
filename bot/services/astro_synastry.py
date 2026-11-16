"""Two-person synastry facts without fake compatibility scores or houses."""

from __future__ import annotations

from bot.services.astro_lunar import AstroInputError
from bot.services.astro_natal import (
    _ANGLES,
    _angular_delta,
    build_natal_facts,
    load_aspect_orbs,
)

SYNASTRY_SCHEMA = "astro.synastry.facts.v1"


def cross_aspects(
    first: dict[str, dict],
    second: dict[str, dict],
    *,
    orbs: dict[str, float],
    approximate: bool = False,
) -> list[dict]:
    """Return every cross-chart major longitude aspect inside configured orbs.

    Person order is preserved. Unlike a merged chart, same-name bodies in
    separate charts are not deduplicated (Sun A vs Sun B is meaningful).
    """
    result: list[dict] = []
    for name_a, body_a in first.items():
        for name_b, body_b in second.items():
            difference = abs(_angular_delta(body_b["longitude_deg"], body_a["longitude_deg"]))
            candidates = [
                (abs(difference - angle), kind, angle)
                for kind, angle in _ANGLES.items()
                if abs(difference - angle) <= orbs[kind]
            ]
            if not candidates:
                continue
            orb, kind, exact_angle = min(candidates)
            result.append({
                "person_a_body": name_a,
                "person_b_body": name_b,
                "kind": kind,
                "angle_deg": exact_angle,
                "separation_deg": round(difference, 3),
                "orb_deg": round(orb, 3),
                "approximate": approximate,
            })
    return sorted(
        result,
        key=lambda item: (item["orb_deg"], item["person_a_body"], item["person_b_body"]),
    )


def build_compatibility_facts(
    first: dict,
    second: dict,
    *,
    engine=None,
    orbs: dict[str, float] | None = None,
) -> dict:
    if not isinstance(first, dict) or not isinstance(second, dict):
        raise AstroInputError("Для совместимости требуются данные двух людей.")
    rules = orbs if orbs is not None else load_aspect_orbs()
    # Invoke the exact same astronomical engine and input validation for both
    # people; never let an LLM create their chart from a place name.
    def natal(profile: dict) -> dict:
        return build_natal_facts(
            date=profile.get("date"),
            time=profile.get("time"),
            timezone_name=profile.get("timezone"),
            fold=profile.get("fold"),
            engine=engine,
            orbs=rules,
        )

    person_a = natal(first)
    person_b = natal(second)
    approximate = not (person_a["birth_time_known"] and person_b["birth_time_known"])
    cross = cross_aspects(
        person_a["positions"],
        person_b["positions"],
        orbs=rules,
        approximate=approximate,
    )
    warnings = [
        "Наложения на дома, ASC/MC и композит не рассчитаны.",
        "Это перечень геометрических аспектов, не оценка качества отношений.",
    ]
    if approximate:
        warnings.append(
            "Время рождения хотя бы одного человека неизвестно: межкартные "
            "аспекты приближённые; Луна человека без времени исключена."
        )
    return {
        "schema_version": SYNASTRY_SCHEMA,
        "engine": person_a["engine"],
        "person_a": person_a,
        "person_b": person_b,
        "cross_aspects": cross,
        "not_calculated": [
            "house_overlays", "angles", "composite", "compatibility_score",
            "psychological_interpretation",
        ],
        "warnings": warnings,
        "disclaimer": "Астрологическая совместимость не является научной оценкой отношений.",
    }
