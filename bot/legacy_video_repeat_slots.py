"""Describe legacy retained slots without creating or changing a consent grant."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def legacy_selection_plan(
    recipe: dict[str, Any], selection: dict[str, Any], *,
    resolve: Callable[[str, list[str]], str | None],
) -> dict[str, Any] | None:
    """Bridge only closed, retained-tail multimodal layouts supported by the UI.

    Legacy optional trailing uploads keep their old form, rather than becoming
    required or disappearing. No authorization or persistence happens here.
    """
    if recipe.get("model") != "seedance_2_5" or recipe.get("scenario") != "multimodal":
        return None
    result = {**recipe}
    any_fixed = False
    for kind in ("images", "videos"):
        slots = recipe[kind]
        candidates = [slot["url"] for slot in slots]
        values = selection.get(kind, [])
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError("Invalid legacy reference selection")
        fixed = set()
        for value in values:
            matched = resolve(value, candidates)
            if matched is None:
                raise ValueError("Selected legacy reference is unavailable")
            fixed.add(matched)
        if slots and (not fixed or slots[-1]["url"] not in fixed):
            return None
        any_fixed = any_fixed or bool(fixed)
        result[kind] = [{**slot, "binding": "fixed" if slot["url"] in fixed else "upload"}
                        for slot in slots]
    return result if any_fixed else None
