#!/usr/bin/env python3
"""Скрипт для отмены платежа и возврата денег"""
import asyncio
import os
import sqlite3
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from bot.services.tbank_service import TBankService


async def cancel_last_payment():
    """Отменяет последний платёж и возвращает деньги"""

    # Получаем последнюю транзакцию
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, order_id, payment_id, credits, amount_rub, status, created_at 
        FROM transactions 
        ORDER BY id DESC LIMIT 1
    """
    )
    row = cursor.fetchone()

    if not row:
        print("❌ Нет транзакций в базе данных")
        return

    transaction_id, order_id, payment_id, credits, amount_rub, status, created_at = row

    print(f"📋 Последняя транзакция:")
    print(f"   ID: {transaction_id}")
    print(f"   Order ID: {order_id}")
    print(f"   Payment ID: {payment_id}")
    print(f"   Сумма: {amount_rub}₽")
    print(f"   Статус: {status}")
    print(f"   Дата: {created_at}")
    print()

    if not payment_id:
        print("❌ У транзакции нет Payment ID - невозможно отменить")
        conn.close()
        return

    # Инициализируем сервис Т-Банка
    tbank = TBankService(
        terminal_key=os.getenv("TBANK_TERMINAL_KEY", ""),
        secret_key=os.getenv("TBANK_SECRET_KEY", ""),
        api_url=os.getenv("TBANK_API_URL", "https://securepay.tinkoff.ru/v2/"),
    )

    # Сначала проверяем статус платежа
    print(f"🔍 Проверка статуса платежа {payment_id}...")
    state = await tbank.get_state(payment_id)

    if not state:
        print("❌ Не удалось получить статус платежа")
        conn.close()
        return

    print(f"   Статус в Т-Банк: {state.get('Status', 'N/A')}")
    print(f"   Success: {state.get('Success')}")
    print()

    # Отменяем платёж
    print(f"🔄 Отмена платежа {payment_id}...")
    result = await tbank.cancel(payment_id)

    if not result:
        print("❌ Не удалось отменить платёж")
        conn.close()
        return

    print(f"   Success: {result.get('Success')}")
    print(f"   Status: {result.get('Status', 'N/A')}")
    print(f"   Message: {result.get('Message', 'N/A')}")

    if result.get("Success"):
        # Обновляем статус в базе
        cursor.execute(
            "UPDATE transactions SET status = 'cancelled' WHERE id = ?",
            (transaction_id,),
        )
        conn.commit()
        print(f"\n✅ Платёж успешно отменён и деньги возвращены!")
        print(f"   Сумма возврата: {amount_rub}₽")
    else:
        error_code = result.get("ErrorCode", "N/A")
        print(f"\n⚠️ Ошибка отмены: {error_code} - {result.get('Message', 'N/A')}")

    conn.close()


if __name__ == "__main__":
    asyncio.run(cancel_last_payment())
