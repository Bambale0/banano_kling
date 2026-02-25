#!/usr/bin/env python3
"""
Тест верификации токена уведомления от Т-Банка

Пример из документации:
Параметры уведомления (без Password):
- TerminalKey: 1234567890DEMO
- OrderId: 000000
- Success: true
- Status: AUTHORIZED
- PaymentId: 0000000
- ErrorCode: 0
- Amount: 1111
- CardId: 000000
- Pan: 200000******0000
- ExpDate: 1111
- RebillId: 000000
- Password: 11111111111 (ДОБАВЛЯЕТСЯ К ПАРАМЕТРАМ!)

Ожидаемый токен: 1c0964277d0213349243065a0d5b838b8e90d2d25f740d0f2767836e710e80c8
"""

import hashlib


def generate_webhook_token(data: dict, password: str) -> str:
    """
    Генерация токена для верификации уведомления от Т-Банка

    Алгоритм (из документации):
    1. Собрать массив всех параметров, кроме Token и вложенных объектов (Data, Receipt)
    2. Добавить Password к параметрам
    3. Отсортировать по алфавиту по ключу
    4. Конкатенировать только значения в строку
    5. SHA-256 хеш
    """
    # Шаг 1: Собираем скалярные параметры (исключая Token и вложенные объекты)
    token_params = {}
    for key, value in data.items():
        if key == "Token":
            continue
        # Включаем все скалярные значения
        if isinstance(value, (str, int, float, bool)):
            token_params[key] = str(value)

    # Шаг 2: Добавляем Password
    token_params["Password"] = password

    # Шаг 3: Сортируем по алфавиту
    sorted_keys = sorted(token_params.keys())
    print(f"Отсортированные ключи: {sorted_keys}")

    # Шаг 4: Конкатенируем значения
    values_str = "".join(token_params[k] for k in sorted_keys)
    print(f"Конкатенированная строка: '{values_str}'")

    # Шаг 5: SHA-256
    token = hashlib.sha256(values_str.encode("utf-8")).hexdigest()

    return token


def verify_webhook_token(data: dict, password: str) -> bool:
    """Проверка токена уведомления"""
    received_token = data.get("Token")
    if not received_token:
        return False

    expected_token = generate_webhook_token(data, password)

    print(f"Полученный токен:   {received_token}")
    print(f"Ожидаемый токен:    {expected_token}")

    return received_token == expected_token


if __name__ == "__main__":
    # Данные из примера документации
    webhook_data = {
        "TerminalKey": "1234567890DEMO",
        "OrderId": "000000",
        "Success": "true",
        "Status": "AUTHORIZED",
        "PaymentId": "0000000",
        "ErrorCode": "0",
        "Amount": "1111",
        "CardId": "000000",
        "Pan": "200000******0000",
        "ExpDate": "1111",
        "RebillId": "000000",
        # Password добавляется к параметрам!
        "Password": "11111111111",
        "Token": "1c0964277d0213349243065a0d5b838b8e90d2d25f740d0f2767836e710e80c8",
    }

    # Пароль из личного кабинета
    password = "11111111111"

    expected_token = "1c0964277d0213349243065a0d5b838b8e90d2d25f740d0f2767836e710e80c8"

    print("=" * 70)
    print("Тест верификации токена уведомления от Т-Банка")
    print("=" * 70)
    print(f"Данные уведомления: {webhook_data}")
    print("-" * 70)

    # Генерируем токен
    token = generate_webhook_token(webhook_data, password)

    print("-" * 70)
    print(f"Сгенерированный токен: {token}")
    print(f"Ожидаемый токен:      {expected_token}")
    print("-" * 70)

    if token == expected_token:
        print("✅ ТОКЕН СОВПАЛ! Верификация работает корректно.")
    else:
        print("❌ ТОКЕН НЕ СОВПАЛ!")

    print()
    print("=" * 70)
    print("Тест verify_webhook_token()")
    print("=" * 70)

    # Тест функции верификации
    if verify_webhook_token(webhook_data, password):
        print("✅ Верификация УСПЕШНА!")
    else:
        print("❌ Верификация ПРОВАЛЕНА!")
