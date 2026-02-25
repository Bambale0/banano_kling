#!/usr/bin/env python3
"""
Тест верификации webhook с РЕАЛЬНЫМИ данными из лога

Данные из лога (первый webhook):
- TerminalKey: 1771510448563DEMO
- OrderId: 339795159_1771719385_mini
- Success: True
- Status: AUTHORIZED
- PaymentId: 8019236410
- ErrorCode: 0
- Amount: 15000
- CardId: 657049766
- Pan: 430000******0777
- ExpDate: 1230
"""

import hashlib


def generate_webhook_token(data: dict, password: str) -> str:
    """
    Генерация токена для верификации уведомления от Т-Банка

    Алгоритм:
    1. Собрать все скалярные параметры, кроме Token
    2. Добавить Password
    3. Отсортировать по алфавиту
    4. Конкатенировать значения
    5. SHA-256
    """
    token_params = {}
    for key, value in data.items():
        if key == "Token":
            continue
        if isinstance(value, (str, int, float, bool)):
            token_params[key] = str(value)

    # Добавляем Password
    token_params["Password"] = password

    sorted_keys = sorted(token_params.keys())
    print(f"Отсортированные ключи: {sorted_keys}")

    values_str = "".join(token_params[k] for k in sorted_keys)
    print(f"Конкатенированная строка: '{values_str}'")

    token = hashlib.sha256(values_str.encode("utf-8")).hexdigest()

    return token


if __name__ == "__main__":
    # ДАННЫЕ ИЗ ЛОГА (нужно подставить реальный пароль!)
    webhook_data = {
        "TerminalKey": "1771510448563DEMO",
        "OrderId": "339795159_1771719385_mini",
        "Success": "True",
        "Status": "AUTHORIZED",
        "PaymentId": "8019236410",
        "ErrorCode": "0",
        "Amount": "15000",
        "CardId": "657049766",
        "Pan": "430000******0777",
        "ExpDate": "1230",
    }

    # Это TOKEN, который ПРИШЁЛ от Т-Банка (из лога)
    received_token = "db5b482995ba1da64444f0d45570ab54e42c1fcb11c3b66fac0f6d9e5b1b2460"

    print("=" * 70)
    print("Тест верификации webhook с реальными данными из лога")
    print("=" * 70)
    print(f"Данные webhook: {webhook_data}")
    print(f"Полученный токен: {received_token}")
    print("-" * 70)

    # ЗАПРОС: Введите пароль для тестирования
    # Это пароль от личного кабинета Т-Банка (не из лога!)
    password = input("Введите пароль (Password) от Т-Банка: ").strip()

    if not password:
        print("Пароль не введён!")
        exit(1)

    print(f"Используемый пароль: {password}")
    print("-" * 70)

    # Генерируем токен
    expected_token = generate_webhook_token(webhook_data, password)

    print("-" * 70)
    print(f"Сгенерированный токен: {expected_token}")
    print(f"Полученный токен:      {received_token}")
    print("-" * 70)

    if expected_token == received_token:
        print("✅ ТОКЕН СОВПАЛ! Пароль верный.")
    else:
        print("❌ ТОКЕН НЕ СОВПАЛ! Неверный пароль.")
        print()
        print("Попробуйте другой пароль.")
