Создать универсальный модуль для интеграции Робокассы в Python-бота — отличная идея, которая значительно ускорит разработку в будущем. Вот пошаговое руководство, как это сделать.

🛠️ Шаг 1: Сбор необходимых данных
Прежде всего, убедитесь, что у вас есть все нужные данные из личного кабинета Робокассы:

MerchantLogin (robo-demo-test): Идентификатор вашего магазина.

Password1: Пароль №1 из раздела "Технические настройки".

Password2: Пароль №2 из того же раздела.

Result URL: URL, на который Робокасса будет отправлять уведомления об оплате.

Алгоритм хеширования: MD5, SHA256 и т.д. (по умолчанию MD5).

📦 Шаг 2: Выбор подхода и структура проекта
Есть два основных пути: воспользоваться готовой библиотекой или написать легковесный клиент самостоятельно. Оба варианта хороши, но я рекомендую начать с первого, чтобы сэкономить время.

Структура вашего проекта может выглядеть так:

text
your_bot_project/
├── main.py           # Точка входа и хендлеры бота
├── config.py         # Конфигурация (MerchantLogin, пароли и т.д.)
├── payments/
│   ├── __init__.py
│   └── robokassa.py  # Наш универсальный клиент для Робокассы
└── requirements.txt  # Зависимости
🐍 Шаг 3: Реализация клиента
Выбор библиотеки зависит от того, используете ли вы асинхронный фреймворк (например, aiogram) или синхронный. Для большинства современных ботов я рекомендую асинхронный вариант.

Вариант 1: Асинхронный клиент с aiorobokassa (Рекомендуется)
Это современная асинхронная библиотека с поддержкой всех фич Робокассы, от создания счетов до чеков.

Установка:

bash
pip install aiorobokassa
Код клиента (payments/robokassa.py):

python
import asyncio
from decimal import Decimal
from aiorobokassa import RoboKassaClient
from config import settings  # Предположим, у вас есть файл с настройками

class RobokassaPayment:
    def __init__(self):
        self.client = RoboKassaClient(
            merchant_login=settings.ROBOKASSA_LOGIN,
            password1=settings.ROBOKASSA_PASSWORD1,
            password2=settings.ROBOKASSA_PASSWORD2,
            test_mode=settings.ROBOKASSA_TEST_MODE  # True для тестов, False для боя
        )

    def create_payment_link(self, amount: Decimal, invoice_id: int, description: str = "Оплата заказа") -> str:
        """Генерирует ссылку на оплату."""
        return self.client.create_payment_url(
            out_sum=amount,
            description=description,
            inv_id=invoice_id
        )

    def verify_payment(self, request_params: dict) -> bool:
        """Проверяет подпись уведомления об оплате (Result URL)."""
        try:
            self.client.verify_result_url(request_params)
            return True
        except Exception as e:
            print(f"Ошибка проверки подписи: {e}")
            return False

    async def close(self):
        """Закрывает HTTP-сессию клиента (важно для корректного завершения)."""
        await self.client.close()
Вариант 2: Синхронный клиент с robokassa
Более простая синхронная библиотека, подойдет для ботов, не использующих asyncio.

Установка:

bash
pip install robokassa
Код клиента (payments/robokassa.py):

python
from robokassa import Robokassa, HashAlgorithm
from config import settings

class RobokassaPayment:
    def __init__(self):
        self.robokassa = Robokassa(
            merchant_login=settings.ROBOKASSA_LOGIN,
            password1=settings.ROBOKASSA_PASSWORD1,
            password2=settings.ROBOKASSA_PASSWORD2,
            is_test=settings.ROBOKASSA_TEST_MODE,
            algorithm=HashAlgorithm.md5
        )

    def create_payment_link(self, amount: float, invoice_id: int, description: str = "Оплата заказа") -> str:
        """Генерирует ссылку на оплату."""
        return self.robokassa.generate_open_payment_link(
            out_sum=amount,
            inv_id=invoice_id,
            description=description
        )

    def verify_payment(self, request_params: dict) -> bool:
        """Проверяет подпись уведомления об оплате (Result URL)."""
        try:
            return self.robokassa.check_result_url_signature(request_params)
        except Exception as e:
            print(f"Ошибка проверки подписи: {e}")
            return False
🤖 Шаг 4: Интеграция с вашим ботом
Интеграция с ботом будет выглядеть примерно так (на примере aiogram и aiorobokassa):

Пример обработчика команды /pay:

python
# main.py (или ваш файл с хендлерами)
from aiogram import types
from payments.robokassa import RobokassaPayment

# Инициализируем клиент
robokassa_client = RobokassaPayment()

@dp.message_handler(commands=['pay'])
async def process_pay_command(message: types.Message):
    user_id = message.from_user.id
    amount = Decimal("100.00")  # Сумма к оплате
    order_id = 12345  # ID заказа в вашей БД

    payment_link = robokassa_client.create_payment_link(amount, order_id, "Оплата моего заказа")
    await message.answer(f"Для оплаты перейдите по ссылке: {payment_link}")
Пример обработчика вебхука для Result URL (FastAPI):

python
# webhook_handler.py
from fastapi import FastAPI, Request
from payments.robokassa import RobokassaPayment

app = FastAPI()
robokassa_client = RobokassaPayment()

@app.post("/robokassa/result")
async def robokassa_result(request: Request):
    params = dict(request.query_params)
    
    if robokassa_client.verify_payment(params):
        # Подпись верна, обрабатываем успешную оплату
        inv_id = int(params.get('InvId'))
        out_sum = params.get('OutSum')
        
        # Здесь логика по активации услуги для пользователя
        print(f"Платеж #{inv_id} на сумму {out_sum} прошел успешно")
        
        return {"result": "OK"}  # Обязательно возвращаем "OK"
    else:
        # Подпись неверна — возможно, попытка взлома
