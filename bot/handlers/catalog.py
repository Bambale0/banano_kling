import json
import logging
import uuid
from pathlib import Path

import openpyxl as xl
import pandas as pd
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.database import (
    create_shop_order,
    get_or_create_user,
    mark_2loop_promo_used,
    track_event,
)
from bot.states import CatalogStates

logger = logging.getLogger(__name__)
router = Router()

CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "catalog.xlsx"
catalog_df = None


def get_shop_url() -> str:
    base_url = (config.WEBHOOK_HOST or config.static_base_url).rstrip("/")
    return f"{base_url}/shop"


def get_catalog_retry_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🛒 Открыть WB 2Loop",
        url="https://www.wildberries.ru/brands/312149369-2loop",
    )
    builder.button(text="🔍 Новый поиск", callback_data="menu_catalog")
    builder.button(text="🔙 Главное меню", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


async def load_catalog():
    global catalog_df
    try:
        wb = xl.load_workbook(CATALOG_PATH, data_only=True)
        ws = wb.active
        data = list(ws.values)
        if len(data) > 2:
            columns = [str(col).strip() if col is not None else "" for col in data[1]]
            catalog_df = pd.DataFrame(data[2:], columns=columns)
            logger.info(f"Catalog columns: {list(catalog_df.columns)}")
            logger.info(f"Catalog shape: {catalog_df.shape}")
        else:
            catalog_df = pd.DataFrame()
            logger.warning("No data in catalog")
    except Exception as e:
        logger.error(f"Failed to load catalog: {e}")
        catalog_df = pd.DataFrame()


@router.callback_query(F.data == "menu_catalog")
async def catalog_menu(callback: CallbackQuery, state: FSMContext):
    await track_event(callback.from_user.id, "catalog_open")
    await load_catalog()
    if catalog_df.empty:
        await track_event(callback.from_user.id, "catalog_unavailable")
        await callback.message.edit_text("❌ Каталог недоступен.")
        return
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🛍 Открыть мини-магазин",
        web_app=WebAppInfo(url=get_shop_url()),
    )
    builder.button(
        text="🛒 Открыть WB 2Loop",
        url="https://www.wildberries.ru/brands/312149369-2loop",
    )
    builder.button(text="✨ Подбор аксессуара", callback_data="accessory_finder")
    builder.button(text="🔍 Новый поиск", callback_data="menu_catalog")
    builder.adjust(1)

    text = """🛒 <b>Магазин 2Loop</b>

Аксессуары для фигурного катания: выберите товар на Wildberries, затем вернитесь в бот для проверки цены и промокода.

1️⃣ Нажмите "Открыть WB 2Loop".
2️⃣ Введите артикул WB из каталога.
3️⃣ Введите промокод, если он есть. Для теста: <code>2LOOP</code>.
4️⃣ Получите итоговую цену и оформите заказ через поддержку."""
    await callback.message.edit_text(
        text, reply_markup=builder.as_markup(), parse_mode="HTML"
    )
    await state.set_state(CatalogStates.waiting_for_article)


@router.callback_query(F.data == "accessory_finder")
async def accessory_finder(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await track_event(callback.from_user.id, "accessory_finder_open")

    builder = InlineKeyboardBuilder()
    builder.button(
        text="🛍 Мини-магазин 2Loop",
        web_app=WebAppInfo(url=get_shop_url()),
    )
    builder.button(text="🛒 Открыть магазин 2Loop", callback_data="menu_catalog")
    builder.button(text="🖼 Создать образ с AI", callback_data="create_image_refs_new")
    builder.button(text="📸 Фото → промпт", callback_data="photo_to_prompt")
    builder.button(text="🤖 Спросить AI-стилиста", callback_data="menu_ai_assistant")
    builder.button(text="🔙 Главное меню", callback_data="back_main")
    builder.adjust(1)

    text = """✨ <b>Подбор аксессуара 2Loop</b>

Расскажите, к чему подбираем аксессуар: костюм, тренировка, соревнования, подарок или образ для сторис.

Быстрый путь:
1️⃣ Откройте магазин 2Loop и выберите артикул WB.
2️⃣ Вернитесь сюда, введите артикул в каталоге и проверьте промокод.
3️⃣ Если нужна идея образа — создайте AI-визуал или спросите AI-стилиста.

Промокод для теста: <code>2LOOP</code>"""

    await callback.message.edit_text(
        text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(F.web_app_data)
async def handle_catalog_webapp_order(message: Message):
    try:
        payload = json.loads(message.web_app_data.data)
    except (TypeError, json.JSONDecodeError):
        await message.answer("❌ Не удалось прочитать заказ из мини-магазина.")
        return

    if payload.get("type") != "catalog_order":
        return

    items = payload.get("items") or []
    total = payload.get("total", 0)
    promo_code = payload.get("promoCode") or "2LOOP"
    customer = payload.get("customer") or {}
    delivery = payload.get("delivery") or {}
    order_id = f"SHOP-{uuid.uuid4().hex[:10].upper()}"
    await create_shop_order(
        order_id=order_id,
        telegram_id=message.from_user.id,
        customer=customer,
        delivery=delivery,
        items=items,
        total_rub=float(total or 0),
        promo_code=promo_code,
        raw_payload=payload,
    )
    await track_event(
        message.from_user.id,
        "catalog_webapp_order",
        {
            "order_id": order_id,
            "items_count": len(items),
            "total": total,
            "promo": promo_code,
            "delivery": delivery.get("method"),
        },
    )

    lines = []
    for item in items:
        name = item.get("name", "Товар")
        article = item.get("wbArticle", "")
        qty = item.get("qty", 1)
        price = item.get("price", 0)
        lines.append(f"• {name}\n  WB: <code>{article}</code> × {qty} — {price} ₽")

    text = (
        "🛒 <b>Заказ из мини-магазина</b>\n\n"
        f"№ <code>{order_id}</code>\n\n"
        f"{chr(10).join(lines)}\n\n"
        f"💎 Итого: <code>{total} ₽</code>\n"
        f"🎟 Промокод: <code>{promo_code}</code>\n\n"
        f"👤 {customer.get('name') or '-'}\n"
        f"📞 {customer.get('phone') or '-'}\n"
        f"📍 {delivery.get('city') or '-'}, {delivery.get('address') or '-'}\n"
        f"🚚 {delivery.get('method') or 'manual'}\n\n"
        "Для оформления перешлите это сообщение "
        '<a href="https://t.me/design_2Loop7222">@design_2Loop7222</a>'
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Написать в поддержку", url="https://t.me/design_2Loop7222")
    builder.button(
        text="🛍 Открыть мини-магазин", web_app=WebAppInfo(url=get_shop_url())
    )
    builder.button(text="🔙 Главное меню", callback_data="back_main")
    builder.adjust(1)
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.message(StateFilter(CatalogStates.waiting_for_article), F.text)
async def process_article(message: Message, state: FSMContext):
    if catalog_df.empty or catalog_df.shape[1] < 13:
        await track_event(message.from_user.id, "catalog_unavailable")
        await message.answer("❌ Каталог недоступен. Попробуйте позже.")
        return

    article = message.text.strip().upper()
    # Column C (index 2) for article WB
    article_col = catalog_df.iloc[:, 2].astype(str).str.strip().str.upper()
    row_mask = article_col == article
    row = catalog_df[row_mask]
    if row.empty:
        await track_event(
            message.from_user.id,
            "catalog_article_not_found",
            {"article": article},
        )
        await message.answer(
            "❌ Артикул WB не найден.\n\n"
            "Введите другой артикул или выберите действие ниже:",
            reply_markup=get_catalog_retry_keyboard(),
        )
        return
    # Column M (index 12) for 'Цена со скидкой'
    price = row.iloc[0, 12]
    if pd.isna(price):
        await track_event(
            message.from_user.id,
            "catalog_article_without_price",
            {"article": article},
        )
        await message.answer(
            "❌ Цена не указана для этого артикула.",
            reply_markup=get_catalog_retry_keyboard(),
        )
        await state.clear()
        return
    await track_event(
        message.from_user.id,
        "catalog_article_found",
        {"article": article, "price": float(price)},
    )
    await state.update_data(article=article, base_price=float(price))
    text = f"""✅ Артикул WB: <code>{article}</code>

💰 Цена: <code>{price} ₽</code>

💳 Введите промокод (или нажмите "Нет промокода"):"""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Нет промокода", callback_data="catalog_no_promo")
    builder.button(text="🔍 Новый поиск", callback_data="menu_catalog")
    builder.adjust(1)
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await state.set_state(CatalogStates.waiting_for_promo)


@router.message(StateFilter(CatalogStates.waiting_for_promo), F.text)
async def process_promo(message: Message, state: FSMContext):
    promo = message.text.strip().upper()
    data = await state.get_data()
    base_price = data["base_price"]
    article = data["article"]
    telegram_id = message.from_user.id

    user = await get_or_create_user(telegram_id)

    if promo == "2LOOP":
        if user.used_2loop_promo:
            discount = 0
            final_price = base_price
            discount_text = "0% (уже использован)"
            promo_text = "Промокод уже использован ранее"
        else:
            discount = 0.2
            final_price = base_price * (1 - discount)
            discount_text = "20%"
            await mark_2loop_promo_used(telegram_id)
            promo_text = "Промокод успешно применён (одноразовый)"
    else:
        discount = 0
        final_price = base_price
        discount_text = "0%"
        promo_text = "Промокод не найден"

    await track_event(
        telegram_id,
        "catalog_promo_checked",
        {
            "article": article,
            "promo": promo,
            "discount_percent": int(discount * 100),
            "final_price": round(final_price, 2),
        },
    )

    text = f"""✅ Артикул WB: <code>{article}</code>

💰 Цена: <code>{base_price} ₽</code>
🆔 Промокод: <code>{promo}</code> ({discount_text})
{promo_text}
💎 Итого: <code>{final_price:.0f} ₽</code>

📦 Раздел доставки в разработке"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🛒 Заказать", callback_data=f"catalog_order:{article}:{final_price:.0f}"
    )
    builder.button(text="🔍 Новый поиск", callback_data="menu_catalog")
    builder.adjust(1)
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await state.clear()


@router.callback_query(
    StateFilter(CatalogStates.waiting_for_promo),
    F.data == "catalog_no_promo",
)
async def no_promo(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    article = data["article"]
    base_price = data["base_price"]
    final_price = base_price
    await track_event(
        callback.from_user.id,
        "catalog_promo_skipped",
        {"article": article, "final_price": round(final_price, 2)},
    )
    text = f"""✅ Артикул WB: <code>{article}</code>

💰 Цена: <code>{base_price} ₽</code>
🆔 Промокод: нет (0% скидка)
💎 Итого: <code>{final_price:.0f} ₽</code>

📦 Раздел доставки в разработке"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🛒 Заказать", callback_data=f"catalog_order:{article}:{final_price:.0f}"
    )
    builder.button(text="🔍 Новый поиск", callback_data="menu_catalog")
    builder.adjust(1)
    await callback.message.edit_text(
        text, reply_markup=builder.as_markup(), parse_mode="HTML"
    )
    await state.clear()


@router.callback_query(F.data.startswith("catalog_order"))
async def catalog_order(callback: CallbackQuery):
    if callback.data.startswith("catalog_order:"):
        _, article, price = callback.data.split(":", 2)
    else:
        payload = callback.data.replace("catalog_order_", "", 1)
        article, price = payload.rsplit("_", 1)
    await track_event(
        callback.from_user.id,
        "catalog_order_click",
        {"article": article, "price": price},
    )
    text = f"""🛒 <b>Заказ</b>

Артикул: <code>{article}</code>
💎 Итого: <code>{price} ₽</code>

📦 Раздел доставки в разработке
По вопросам доставки перешлите это сообщение <a href="https://t.me/design_2Loop7222">@design_2Loop7222</a>"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔍 Новый поиск", callback_data="menu_catalog")
    builder.adjust(1)
    await callback.message.edit_text(
        text, reply_markup=builder.as_markup(), parse_mode="HTML"
    )


@router.message()
async def invalid_catalog_input(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state and current_state.startswith("CatalogStates"):
        await message.answer(
            "❌ Неверный ввод.\n\n"
            "Введите артикул WB текстом или выберите действие ниже:",
            reply_markup=get_catalog_retry_keyboard(),
        )
