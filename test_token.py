#!/usr/bin/env python3
"""
Тест генерации токена по документации Т-Банк (Тинькофф)
https://github.com/Tinkoff/tinkoff-api-v2

Пример из документации:
- TerminalKey: MerchantTerminalKey
- Amount: 19200
- OrderId: 00000
- Description: Подарочная карта на 1000 рублей
- Password: 11111111111111

Ожидаемый токен: 72dd466f8ace0a37a1f740ce5fb78101712bc0665d91a8108c7c8a0ccd426db2
"""

import hashlib


def generate_token(
    terminal_key: str, amount: int, order_id: str, description: str, password: str
) -> str:
    """
    Генерация токена подписи по документации Т-Банк

    Алгоритм:
    1. Собрать массив передаваемых параметров в виде пар ключ:значение
    2. Добавить пару {"Password": "значение пароля"}
    3. Отсортировать массив по алфавиту по ключу
    4. Конкатенировать только значения пар в одну строку
    5. Применить к строке хеш-функцию SHA-256 (с поддержкой UTF-8)
    """
    # Шаг 1: Собираем параметры
    params = {
        "TerminalKey": terminal_key,
        "Amount": amount,
        "OrderId": order_id,
        "Description": description,
    }

    # Шаг 2: Добавляем Password
    params["Password"] = password

    # Шаг 3: Сортируем по алфавиту по ключу
    sorted_keys = sorted(params.keys())
    print(f"Отсортированные ключи: {sorted_keys}")

    # Шаг 4: Конкатенируем только значения
    values_str = "".join(str(params[key]) for key in sorted_keys)
    print(f"Конкатенированная строка: '{values_str}'")

    # Шаг 5: SHA-256 хеш
    token = hashlib.sha256(values_str.encode("utf-8")).hexdigest()

    return token


if __name__ == "__main__":
    # Тестовые данные из документации
    terminal_key = "MerchantTerminalKey"
    amount = 19200
    order_id = "00000"
    description = "Подарочная карта на 1000 рублей"
    password = "11111111111111"

    expected_token = "72dd466f8ace0a37a1f740ce5fb78101712bc0665d91a8108c7c8a0ccd426db2"

    print("=" * 60)
    print("Тест генерации токена по документации Т-Банк")
    print("=" * 60)
    print(f"TerminalKey: {terminal_key}")
    print(f"Amount: {amount}")
    print(f"OrderId: {order_id}")
    print(f"Description: {description}")
    print(f"Password: {password}")
    print("-" * 60)

    token = generate_token(terminal_key, amount, order_id, description, password)

    print("-" * 60)
    print(f"Сгенерированный токен: {token}")
    print(f"Ожидаемый токен:      {expected_token}")
    print("-" * 60)

    if token == expected_token:
        print("✅ ТОКЕН СОВПАЛ! Тест пройден успешно.")
    else:
        print("❌ ТОКЕН НЕ СОВПАЛ! Тест провален.")
