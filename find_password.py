#!/usr/bin/env python3
"""
Скрипт для подбора пароля по токену вебхука
"""

import hashlib
import itertools


def generate_token(data: dict, password: str) -> str:
    """Генерация токена"""
    token_params = {}
    for key, value in data.items():
        if key == "Token":
            continue
        if isinstance(value, (str, int, float, bool)):
            token_params[key] = str(value)
    
    token_params["Password"] = password
    sorted_keys = sorted(token_params.keys())
    values_str = "".join(token_params[k] for k in sorted_keys)
    
    return hashlib.sha256(values_str.encode("utf-8")).hexdigest()


# Данные из лога
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

# Полученный токен
received_token = "db5b482995ba1da64444f0d45570ab54e42c1fcb11c3b66fac0f6d9e5b1b2460"

# Варианты паролей для DEMO терминала
password_variations = [
    "11111111111",  # Стандартный тестовый пароль
    "1771510448563DEMO",  # Пароль = TerminalKey
    "1771510448563",  # Без DEMO
    "demo",  # Просто demo
    "Demo123!",  # Демо с цифрами
    "Password123!",
    "Tinkoff123!",
    "securepay",
    "",
]

print("Пробуем стандартные пароли...")

for password in password_variations:
    token = generate_token(webhook_data, password)
    if token == received_token:
        print(f"✅ НАЙДЕН ПАРОЛЬ: '{password}'")
        exit(0)

# Пробуем числовые пароли
print("Пробуем числовые пароли...")
for length in [8, 11, 12, 13, 14, 15]:
    for num in itertools.product("0123456789", repeat=length):
        password = "".join(num)
        token = generate_token(webhook_data, password)
        if token == received_token:
            print(f"✅ НАЙДЕН ПАРОЛЬ: '{password}'")
            exit(0)

print("❌ Пароль не найден среди простых вариантов")
print(f"   Полученный токен: {received_token}")
