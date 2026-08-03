from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Expected anchor not found in {path}: {old[:160]!r}")
    write(path, text.replace(old, new, 1))


def regex_replace_once(path: str, pattern: str, replacement: str) -> None:
    text = read(path)
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise RuntimeError(f"Expected one regex match in {path}, got {count}: {pattern[:160]!r}")
    write(path, updated)


# Canonical price config: 1 credit remains 10 RUB; photo prompt costs 1 RUB = 0.1 credit.
price_path = ROOT / "data/price.json"
price_data = json.loads(price_path.read_text(encoding="utf-8"))
price_data["credit_rub_value"] = 10
service_prices = dict(price_data.get("service_prices") or {})
service_prices["photo_prompt_rub"] = 1
price_data["service_prices"] = service_prices
price_path.write_text(json.dumps(price_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

replace_once(
    "bot/services/preset_manager.py",
    """DEFAULT_PARTNER_EXCHANGE_RUB_PER_CREDIT = 10
DEFAULT_VIDEO_PROMPT_COST = 3
""",
    """DEFAULT_PARTNER_EXCHANGE_RUB_PER_CREDIT = 10
DEFAULT_CREDIT_RUB_VALUE = 10
DEFAULT_PHOTO_PROMPT_PRICE_RUB = 1
DEFAULT_VIDEO_PROMPT_COST = 3
""",
)
replace_once(
    "bot/services/preset_manager.py",
    """    def get_partner_exchange_rub_per_credit(self) -> float:
        exchange_cfg = self._price_config.get("partner_exchange", {}) or {}
        value = exchange_cfg.get("rub_per_credit", DEFAULT_PARTNER_EXCHANGE_RUB_PER_CREDIT)
        return float(value or DEFAULT_PARTNER_EXCHANGE_RUB_PER_CREDIT)

    def get_video_prompt_cost(self) -> float:
""",
    """    def get_partner_exchange_rub_per_credit(self) -> float:
        exchange_cfg = self._price_config.get("partner_exchange", {}) or {}
        value = exchange_cfg.get("rub_per_credit", DEFAULT_PARTNER_EXCHANGE_RUB_PER_CREDIT)
        return float(value or DEFAULT_PARTNER_EXCHANGE_RUB_PER_CREDIT)

    def get_credit_rub_value(self) -> float:
        value = self._price_config.get("credit_rub_value", DEFAULT_CREDIT_RUB_VALUE)
        normalized = float(value or DEFAULT_CREDIT_RUB_VALUE)
        return normalized if normalized > 0 else float(DEFAULT_CREDIT_RUB_VALUE)

    def get_photo_prompt_price_rub(self) -> float:
        service_prices = self._price_config.get("service_prices", {}) or {}
        value = service_prices.get("photo_prompt_rub", DEFAULT_PHOTO_PROMPT_PRICE_RUB)
        return round(float(value or DEFAULT_PHOTO_PROMPT_PRICE_RUB), 2)

    def get_photo_prompt_cost(self) -> float:
        return round(self.get_photo_prompt_price_rub() / self.get_credit_rub_value(), 4)

    def get_video_prompt_cost(self) -> float:
""",
)

# SQLite can store REAL in an existing INTEGER-affinity column. New installs and Postgres
# get an explicit fractional type. Existing Postgres installs are migrated at startup.
replace_once(
    "bot/database.py",
    """                credits INTEGER DEFAULT 0,
""",
    """                credits REAL DEFAULT 0,
""",
)
replace_once(
    "bot/database.py",
    """        # Таблица транзакций
""",
    """        if db_backend.is_postgres():
            await db.execute(
                "ALTER TABLE users ALTER COLUMN credits TYPE NUMERIC(12, 4) USING credits::numeric"
            )

        # Таблица транзакций
""",
)
replace_once(
    "bot/database.py",
    """async def get_user_credits(telegram_id: int) -> int:
    \"\"\"Получает баланс кредитов пользователя\"\"\"
    user = await get_or_create_user(telegram_id)
    return int(user.credits)
""",
    """async def get_user_credits(telegram_id: int) -> Credits:
    \"\"\"Получает баланс без потери дробной части кредита.\"\"\"
    user = await get_or_create_user(telegram_id)
    return Credits(user.credits)
""",
)
replace_once(
    "schema_postgres.sql",
    """    credits INTEGER DEFAULT 0,
""",
    """    credits NUMERIC(12, 4) DEFAULT 0,
""",
)

write(
    "bot/services/photo_prompt_billing.py",
    '''from __future__ import annotations

from dataclasses import dataclass

from bot.config import config
from bot.database import add_credits, deduct_credits, get_or_create_user
from bot.services.preset_manager import preset_manager


@dataclass(frozen=True)
class PhotoPromptCharge:
    telegram_id: int
    cost_credits: float
    price_rub: float
    charged: bool
    balance_after: float


class PhotoPromptInsufficientBalance(ValueError):
    def __init__(self, *, balance: float, cost_credits: float, price_rub: float):
        self.balance = round(float(balance), 4)
        self.cost_credits = round(float(cost_credits), 4)
        self.price_rub = round(float(price_rub), 2)
        super().__init__(
            f"Недостаточно бананов. Стоимость: {self.price_rub:g} ₽ "
            f"({self.cost_credits:g} 🍌), баланс: {self.balance:g} 🍌."
        )


def photo_prompt_price_rub() -> float:
    return preset_manager.get_photo_prompt_price_rub()


def photo_prompt_cost_credits() -> float:
    return preset_manager.get_photo_prompt_cost()


def photo_prompt_price_label() -> str:
    return f"{photo_prompt_price_rub():g} ₽ ({photo_prompt_cost_credits():g} 🍌)"


async def reserve_photo_prompt_charge(telegram_id: int) -> PhotoPromptCharge:
    price_rub = photo_prompt_price_rub()
    cost_credits = photo_prompt_cost_credits()
    user = await get_or_create_user(telegram_id)

    if config.is_admin(telegram_id):
        return PhotoPromptCharge(
            telegram_id=telegram_id,
            cost_credits=cost_credits,
            price_rub=price_rub,
            charged=False,
            balance_after=round(float(user.credits), 4),
        )

    if float(user.credits) + 1e-9 < cost_credits:
        raise PhotoPromptInsufficientBalance(
            balance=float(user.credits),
            cost_credits=cost_credits,
            price_rub=price_rub,
        )

    deducted = await deduct_credits(telegram_id, cost_credits)
    if not deducted:
        current = await get_or_create_user(telegram_id)
        raise PhotoPromptInsufficientBalance(
            balance=float(current.credits),
            cost_credits=cost_credits,
            price_rub=price_rub,
        )

    current = await get_or_create_user(telegram_id)
    return PhotoPromptCharge(
        telegram_id=telegram_id,
        cost_credits=cost_credits,
        price_rub=price_rub,
        charged=True,
        balance_after=round(float(current.credits), 4),
    )


async def refund_photo_prompt_charge(charge: PhotoPromptCharge | None) -> float | None:
    if charge is None:
        return None
    if charge.charged:
        await add_credits(charge.telegram_id, charge.cost_credits)
    current = await get_or_create_user(charge.telegram_id)
    return round(float(current.credits), 4)
''',
)

# Mini App: validate input, reserve 0.1 credit, refund on provider failure, return fresh balance.
replace_once(
    "bot/miniapp.py",
    """from bot.services.preset_manager import preset_manager
""",
    """from bot.services.preset_manager import preset_manager
from bot.services.photo_prompt_billing import (
    PhotoPromptInsufficientBalance,
    refund_photo_prompt_charge,
    reserve_photo_prompt_charge,
)
""",
)
old_miniapp = '''async def miniapp_photo_to_prompt(request: web.Request) -> web.Response:
    """Analyze a reference image and return generation prompts via GPT 5.4."""
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        image_url = str(body.get("image_url", "") or "").strip()
        preserve = str(body.get("preserve", "") or "").strip()
        goal = str(body.get("goal", "") or "").strip()

        await _get_user_context(request.app, init_data, body.get("start_param_fallback"))

        if not image_url:
            return web.json_response(
                {"ok": False, "error": "Загрузите фото для анализа"},
                status=400,
            )

        from bot.services.photo_prompt_service import photo_prompt_service

        result = await photo_prompt_service.analyze_photo(
            image_url=image_url,
            preserve=preserve,
            goal=goal,
        )

        return web.json_response(
            {
                "ok": True,
                "prompt_en": result["prompt_en"],
                "prompt_ru": result["prompt_ru"],
                "negative_prompt": result["negative_prompt"],
                "model_hint": result["model_hint"],
                "gemini_omni_prompt": result.get("gemini_omni_prompt", ""),
                "voice_transcript": result.get("voice_transcript", ""),
                "voice_prompt_summary_ru": result.get("voice_prompt_summary_ru", ""),
                "voice_description_ru": result.get("voice_description_ru", ""),
                "key_details": result.get("key_details", []),
            }
        )
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App photo-to-prompt failed")
'''
new_miniapp = '''async def miniapp_photo_to_prompt(request: web.Request) -> web.Response:
    """Analyze a photo for 1 RUB (0.1 credit) without changing generation prices."""
    charge = None
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        image_url = str(body.get("image_url", "") or "").strip()
        preserve = str(body.get("preserve", "") or "").strip()
        goal = str(body.get("goal", "") or "").strip()

        telegram_id, _ctx = await _get_user_context(
            request.app,
            init_data,
            body.get("start_param_fallback"),
        )

        if not image_url:
            return web.json_response(
                {"ok": False, "error": "Загрузите фото для анализа"},
                status=400,
            )

        try:
            charge = await reserve_photo_prompt_charge(telegram_id)
        except PhotoPromptInsufficientBalance as exc:
            return web.json_response(
                {
                    "ok": False,
                    "error": str(exc),
                    "credits": exc.balance,
                    "cost_credits": exc.cost_credits,
                    "price_rub": exc.price_rub,
                },
                status=402,
            )

        from bot.services.photo_prompt_service import photo_prompt_service

        try:
            result = await photo_prompt_service.analyze_photo(
                image_url=image_url,
                preserve=preserve,
                goal=goal,
            )
        except Exception:
            await refund_photo_prompt_charge(charge)
            raise

        return web.json_response(
            {
                "ok": True,
                "prompt_en": result["prompt_en"],
                "prompt_ru": result["prompt_ru"],
                "negative_prompt": result["negative_prompt"],
                "model_hint": result["model_hint"],
                "gemini_omni_prompt": result.get("gemini_omni_prompt", ""),
                "voice_transcript": result.get("voice_transcript", ""),
                "voice_prompt_summary_ru": result.get("voice_prompt_summary_ru", ""),
                "voice_description_ru": result.get("voice_description_ru", ""),
                "key_details": result.get("key_details", []),
                "credits": charge.balance_after,
                "cost_credits": charge.cost_credits,
                "price_rub": charge.price_rub,
            }
        )
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App photo-to-prompt failed")
'''
replace_once("bot/miniapp.py", old_miniapp, new_miniapp)

# Telegram bot: same canonical price. Voice-only prompt remains free; any analysis with a photo costs 1 RUB.
replace_once(
    "bot/handlers/image_analyzer.py",
    """from bot.services.preset_manager import preset_manager
""",
    """from bot.services.preset_manager import preset_manager
from bot.services.photo_prompt_billing import (
    PhotoPromptInsufficientBalance,
    photo_prompt_price_label,
    refund_photo_prompt_charge,
    reserve_photo_prompt_charge,
)
""",
)
replace_once(
    "bot/handlers/image_analyzer.py",
    """        "📸 <b>Промпт по фото</b>\\n\\n"
        "Отправьте фото, голосовой промпт или сначала голос, а затем фото.\\n"
""",
    """        "📸 <b>Промпт по фото</b>\\n\\n"
        f"Стоимость анализа фото: <b>{photo_prompt_price_label()}</b>\\n\\n"
        "Отправьте фото, голосовой промпт или сначала голос, а затем фото.\\n"
""",
)
replace_once(
    "bot/handlers/image_analyzer.py",
    """async def analyze_photo(message: Message, state: FSMContext):
    processing = await message.answer("🔍 Анализирую фото и собираю точный prompt…")

    try:
""",
    """async def analyze_photo(message: Message, state: FSMContext):
    processing = await message.answer("🔍 Анализирую фото и собираю точный prompt…")
    charge = None

    try:
""",
)
replace_once(
    "bot/handlers/image_analyzer.py",
    """        result = await photo_prompt_service.analyze_photo(
            image_url=image_url,
""",
    """        charge = await reserve_photo_prompt_charge(message.from_user.id)

        result = await photo_prompt_service.analyze_photo(
            image_url=image_url,
""",
)
replace_once(
    "bot/handlers/image_analyzer.py",
    """    except Exception as e:
        logger.exception("Photo to prompt analysis failed")
        await _safe_edit_or_answer(
            processing,
            message,
            _clip_text(f"❌ Не удалось разобрать фото: {e}", 700),
            reply_markup=get_main_menu_button_keyboard(),
        )
        await state.clear()


@router.message(
    ImageAnalyzerStates.waiting_for_video_prompt,
""",
    """    except PhotoPromptInsufficientBalance as e:
        await _safe_edit_or_answer(
            processing,
            message,
            f"❌ {html.escape(str(e))}",
            reply_markup=get_main_menu_button_keyboard(),
            parse_mode="HTML",
        )
        await state.clear()
    except Exception as e:
        logger.exception("Photo to prompt analysis failed")
        await refund_photo_prompt_charge(charge)
        await _safe_edit_or_answer(
            processing,
            message,
            _clip_text(f"❌ Не удалось разобрать фото: {e}", 700),
            reply_markup=get_main_menu_button_keyboard(),
        )
        await state.clear()


@router.message(
    ImageAnalyzerStates.waiting_for_video_prompt,
""",
)

# Frontend API returns the backend-authoritative fresh balance.
replace_once(
    "frontend/miniapp-v0/lib/api.ts",
    """}): Promise<{
  prompt_en: string
  prompt_ru: string
  negative_prompt: string
  model_hint: string
}> {
""",
    """}): Promise<{
  prompt_en: string
  prompt_ru: string
  negative_prompt: string
  model_hint: string
  credits: number
  cost_credits: number
  price_rub: number
}> {
""",
)

replace_once(
    "frontend/miniapp-v0/components/workspace-sheet.tsx",
    """function PhotoPromptPanel({ onOpenPhoto }: { onOpenPhoto: () => void }) {
  const [reference, setReference] = useState<{ name: string; url: string } | null>(null)
""",
    """function PhotoPromptPanel({ onOpenPhoto }: { onOpenPhoto: () => void }) {
  const { setCredits } = useApp()
  const [reference, setReference] = useState<{ name: string; url: string } | null>(null)
""",
)
replace_once(
    "frontend/miniapp-v0/components/workspace-sheet.tsx",
    """      setРезультат(data)
      toast.success('Промпт собран')
""",
    """      setРезультат(data)
      setCredits(data.credits)
      toast.success('Промпт собран', { description: 'Списано 1 ₽ (0,1 🍌).' })
""",
)
replace_once(
    "frontend/miniapp-v0/components/workspace-sheet.tsx",
    """          композиция, объект, свет, стиль, цвета и важные детали.
        </p>
""",
    """          композиция, объект, свет, стиль, цвета и важные детали.
        </p>
        <p className="mt-3 inline-flex rounded-full border border-gold/25 bg-gold/10 px-3 py-1.5 text-xs font-medium text-gold">
          Стоимость: 1 ₽ · 0,1 🍌
        </p>
""",
)
replace_once(
    "frontend/miniapp-v0/components/workspace-sheet.tsx",
    """        {isAnalyzing ? 'Анализирую фото…' : 'Собрать точный промпт'}
""",
    """        {isAnalyzing ? 'Анализирую фото…' : 'Собрать точный промпт · 1 ₽'}
""",
)
replace_once(
    "frontend/miniapp-v0/components/service-grid.tsx",
    """    badge: 'Разбор фото',
""",
    """    badge: '1 ₽ · 0,1 🍌',
""",
)

write(
    "tests/test_photo_prompt_pricing.py",
    '''from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from bot.database import Credits, get_user_credits
from bot.services.photo_prompt_billing import (
    PhotoPromptCharge,
    PhotoPromptInsufficientBalance,
    photo_prompt_cost_credits,
    photo_prompt_price_rub,
    refund_photo_prompt_charge,
    reserve_photo_prompt_charge,
)
from bot.services.preset_manager import preset_manager


ROOT = Path(__file__).resolve().parents[1]


def test_photo_prompt_is_one_ruble_and_one_tenth_credit() -> None:
    assert preset_manager.get_credit_rub_value() == 10
    assert photo_prompt_price_rub() == 1
    assert photo_prompt_cost_credits() == 0.1


def test_credit_balance_keeps_fractional_part() -> None:
    assert str(Credits(14.9)) == "14.9"
    assert inspect.signature(get_user_credits).return_annotation is Credits


@pytest.mark.asyncio
async def test_photo_prompt_charge_deducts_only_point_one_credit(mocker) -> None:
    mocker.patch("bot.services.photo_prompt_billing.config.is_admin", return_value=False)
    get_user = mocker.patch(
        "bot.services.photo_prompt_billing.get_or_create_user",
        new=mocker.AsyncMock(
            side_effect=[mocker.Mock(credits=2.0), mocker.Mock(credits=1.9)]
        ),
    )
    deduct = mocker.patch(
        "bot.services.photo_prompt_billing.deduct_credits",
        new=mocker.AsyncMock(return_value=True),
    )

    charge = await reserve_photo_prompt_charge(123)

    assert charge.charged is True
    assert charge.cost_credits == 0.1
    assert charge.price_rub == 1
    assert charge.balance_after == 1.9
    deduct.assert_awaited_once_with(123, 0.1)
    assert get_user.await_count == 2


@pytest.mark.asyncio
async def test_photo_prompt_charge_rejects_insufficient_fractional_balance(mocker) -> None:
    mocker.patch("bot.services.photo_prompt_billing.config.is_admin", return_value=False)
    mocker.patch(
        "bot.services.photo_prompt_billing.get_or_create_user",
        new=mocker.AsyncMock(return_value=mocker.Mock(credits=0.09)),
    )
    deduct = mocker.patch(
        "bot.services.photo_prompt_billing.deduct_credits",
        new=mocker.AsyncMock(),
    )

    with pytest.raises(PhotoPromptInsufficientBalance) as error:
        await reserve_photo_prompt_charge(123)

    assert error.value.cost_credits == 0.1
    assert error.value.price_rub == 1
    deduct.assert_not_awaited()


@pytest.mark.asyncio
async def test_photo_prompt_refund_returns_exact_reserved_amount(mocker) -> None:
    add = mocker.patch(
        "bot.services.photo_prompt_billing.add_credits",
        new=mocker.AsyncMock(return_value=True),
    )
    mocker.patch(
        "bot.services.photo_prompt_billing.get_or_create_user",
        new=mocker.AsyncMock(return_value=mocker.Mock(credits=2.0)),
    )
    charge = PhotoPromptCharge(
        telegram_id=123,
        cost_credits=0.1,
        price_rub=1,
        charged=True,
        balance_after=1.9,
    )

    balance = await refund_photo_prompt_charge(charge)

    assert balance == 2.0
    add.assert_awaited_once_with(123, 0.1)


def test_photo_prompt_contract_charges_both_surfaces_and_updates_ui() -> None:
    miniapp = (ROOT / "bot/miniapp.py").read_text(encoding="utf-8")
    handler = (ROOT / "bot/handlers/image_analyzer.py").read_text(encoding="utf-8")
    workspace = (ROOT / "frontend/miniapp-v0/components/workspace-sheet.tsx").read_text(
        encoding="utf-8"
    )
    schema = (ROOT / "schema_postgres.sql").read_text(encoding="utf-8")

    assert "await reserve_photo_prompt_charge(telegram_id)" in miniapp
    assert "await refund_photo_prompt_charge(charge)" in miniapp
    assert "await reserve_photo_prompt_charge(message.from_user.id)" in handler
    assert "await refund_photo_prompt_charge(charge)" in handler
    assert "setCredits(data.credits)" in workspace
    assert "Собрать точный промпт · 1 ₽" in workspace
    assert "credits NUMERIC(12, 4) DEFAULT 0" in schema
''',
)

# Remove this temporary codemod from the resulting feature branch.
Path(__file__).unlink()
