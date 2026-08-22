"""Strict product contract for the Pinterest repeat trend.

The Pinterest flow is intentionally different from ordinary one-tap trends:
users must provide a scene reference, their own identity photo, body
measurements, and explicitly confirm generation. Additional identity angles are
allowed to improve likeness but never trigger generation by themselves.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web

from bot import pinterest_trend_api as pinterest_api
from bot.trend_api import TrendRunValidationError

MIN_PINTEREST_REFERENCES = 2
MAX_PINTEREST_IDENTITY_ANGLES = 5
MAX_PINTEREST_REFERENCES = MIN_PINTEREST_REFERENCES + MAX_PINTEREST_IDENTITY_ANGLES


def _strict_reference_urls(body: dict[str, Any]) -> tuple[str, ...]:
    raw = body.get("reference_urls")
    if not isinstance(raw, list):
        raise TrendRunValidationError(
            "Для этого тренда нужны референс и ваше фото"
        )
    if not MIN_PINTEREST_REFERENCES <= len(raw) <= MAX_PINTEREST_REFERENCES:
        raise TrendRunValidationError(
            "Загрузите референс, ваше фото и при желании до 5 дополнительных ракурсов"
        )

    cleaned: list[str] = []
    for item in raw:
        url = str(item or "").strip()
        if not url:
            raise TrendRunValidationError("Дождитесь окончания загрузки всех фото")
        if url in cleaned:
            raise TrendRunValidationError("Не добавляйте одно и то же фото несколько раз")
        if url.startswith(("blob:", "data:", "file:")):
            raise TrendRunValidationError("Дождитесь окончания загрузки всех фото")
        if not url.startswith(("https://", "http://", "/uploads/")):
            raise TrendRunValidationError("Некорректная ссылка на фото")
        cleaned.append(url)

    return tuple(cleaned)


def _required_measurement(
    body: dict[str, Any],
    key: str,
    *,
    minimum: int,
    maximum: int,
    label: str,
) -> int:
    raw = body.get(key)
    if raw in (None, ""):
        raise TrendRunValidationError(f"Укажите {label.lower()}")
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise TrendRunValidationError(f"{label} должен быть числом") from exc
    if value < minimum or value > maximum:
        raise TrendRunValidationError(f"{label} вне допустимого диапазона")
    return value


def install_pinterest_trend_flow_contract() -> None:
    """Install guards before Pinterest routes are registered."""

    if getattr(pinterest_api, "_strict_manual_flow_installed", False):
        return

    original_handler = pinterest_api.miniapp_run_pinterest_repeat
    original_augmented_prompt = pinterest_api._augmented_prompt

    async def strict_manual_run(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise TrendRunValidationError("Некорректный запрос")
            if body.get("confirmed") is not True:
                raise TrendRunValidationError(
                    "Подтвердите генерацию кнопкой «Создать»"
                )
            _required_measurement(
                body,
                "height_cm",
                minimum=120,
                maximum=230,
                label="Рост",
            )
            _required_measurement(
                body,
                "weight_kg",
                minimum=30,
                maximum=250,
                label="Вес",
            )
        except TrendRunValidationError as error:
            return web.json_response({"ok": False, "error": str(error)}, status=400)
        except Exception:
            return web.json_response(
                {"ok": False, "error": "Некорректные параметры Pinterest-тренда"},
                status=400,
            )

        return await original_handler(request)

    def augmented_prompt(
        base_prompt: str,
        *,
        height_cm: int | None,
        weight_kg: int | None,
    ) -> str:
        prompt = original_augmented_prompt(
            base_prompt,
            height_cm=height_cm,
            weight_kg=weight_kg,
        )
        return (
            f"{prompt}\n"
            "ADDITIONAL USER ANGLES CONTRACT\n"
            "- Image 1 is always the scene/composition reference.\n"
            "- Image 2 and every later image are photographs of the SAME user.\n"
            "- Treat Images 2..N only as additional identity/body-angle evidence.\n"
            "- Never copy identity from Image 1 into the result.\n"
            "- Resolve disagreements between user angles by preserving the consistent identity "
            "visible across Images 2..N."
        )

    pinterest_api._reference_urls = _strict_reference_urls
    pinterest_api._augmented_prompt = augmented_prompt
    pinterest_api.miniapp_run_pinterest_repeat = strict_manual_run
    pinterest_api._strict_manual_flow_installed = True
