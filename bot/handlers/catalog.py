import logging

import openpyxl as xl
import pandas as pd
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database import (
    check_2loop_promo_used,
    get_or_create_user,
    mark_2loop_promo_used,
)
from bot.states import CatalogStates

logger = logging.getLogger(__name__)
router = Router()

CATALOG_PATH = "/root/2loop/data/catalog.xlsx"
catalog_df = None


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
    await load_catalog()
    if catalog_df.empty:
        await callback.message.edit_text("❌ Каталог недоступен.")
        return
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🛒 WB магазин", url="https://www.wildberries.ru/brands/312149369-2loop"
    )
    builder.button(text="🔍 Новый поиск", callback_data="menu_catalog")
    builder.adjust(2)

    text = """🛒 <b>Каталог товаров</b>\\n\\n : 
1️⃣ Нажмите кнопку \"WB магазин\", чтобы открыть каталог на сайте Wildberries.\\n
2️⃣ Введите артикул WB из каталога.\\n
3️⃣ Введите промокод (если есть) для получения скидки.\\n
4️⃣ Получите итоговую цену и информацию о доставке.\\n
            """
    await callback.message.edit_text(
        text, reply_markup=builder.as_markup(), parse_mode="HTML"
    )
    await state.set_state(CatalogStates.waiting_for_article)


@router.message(StateFilter(CatalogStates.waiting_for_article))
async def process_article(message: Message, state: FSMContext):
    if catalog_df.empty or catalog_df.shape[1] < 9:
        await message.answer("❌ Каталог недоступен. Попробуйте позже.")
        return

    article = message.text.strip().upper()
    # Column C (index 2) for article WB
    article_col = catalog_df.iloc[:, 2].astype(str).str.strip().str.upper()
    row_mask = article_col == article
    row = catalog_df[row_mask]
    if row.empty:
        await message.answer("❌ Артикул WB не найден. Введите другой:")
        return
    # Column M (index 12) for 'Цена со скидкой'
    price = row.iloc[0, 12]
    if pd.isna(price):
        await message.answer("❌ Цена не указана для этого артикула.")
        await state.clear()
        return
    await state.update_data(article=article, base_price=float(price))
    text = f"""✅ Артикул WB: <code>{article}</code>

💰 Цена: <code>{price} ₽</code>

💳 Введите промокод (или нажмите "Нет промокода"):"""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Нет промокода", callback_data="catalog_no_promo").adjust(1)
    builder.button(text="🔍 Новый поиск", callback_data="menu_catalog").adjust(1)
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await state.set_state(CatalogStates.waiting_for_promo)


@router.message(StateFilter(CatalogStates.waiting_for_promo))
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

    text = f"""✅ Артикул WB: <code>{article}</code>

💰 Цена: <code>{base_price} ₽</code>
🆔 Промокод: <code>{promo}</code> ({discount_text})
{promo_text}
💎 Итого: <code>{final_price:.0f} ₽</code>

📦 Раздел доставки в разработке"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🛒 Заказать", callback_data=f"catalog_order_{article}_{final_price:.0f}"
    ).adjust(1)
    builder.button(text="🔍 Новый поиск", callback_data="menu_catalog").adjust(1)
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await state.clear()


@router.callback_query(F.data == "catalog_no_promo")
async def no_promo(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    article = data["article"]
    base_price = data["base_price"]
    final_price = base_price
    text = f"""✅ Артикул WB: <code>{article}</code>

💰 Цена: <code>{base_price} ₽</code>
🆔 Промокод: нет (0% скидка)
💎 Итого: <code>{final_price:.0f} ₽</code>

📦 Раздел доставки в разработке"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🛒 Заказать", callback_data=f"catalog_order_{article}_{final_price:.0f}"
    ).adjust(1)
    builder.button(text="🔍 Новый поиск", callback_data="menu_catalog").adjust(1)
    await callback.message.edit_text(
        text, reply_markup=builder.as_markup(), parse_mode="HTML"
    )
    await state.clear()


@router.callback_query(F.data.startswith("catalog_order_"))
async def catalog_order(callback: CallbackQuery):
    _, article, price = callback.data.split("_", 2)
    text = f"""🛒 <b>Заказ</b>

Артикул: <code>{article}</code>
💎 Итого: <code>{price} ₽</code>

📦 Раздел доставки в разработке
По вопросам доставки перешлите это сообщение <a href="tg://user?id=design_2Loop">@design_2Loop</a>"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔍 Новый поиск", callback_data="menu_catalog").adjust(1)
    await callback.message.edit_text(
        text, reply_markup=builder.as_markup(), parse_mode="HTML"
    )


@router.message()
async def invalid_catalog_input(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state and current_state.startswith("CatalogStates"):
        await message.answer("❌ Неверный ввод. Следуйте инструкциям.")
