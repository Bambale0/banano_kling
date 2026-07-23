# FreeKassa — настройка оплаты

Ветка `tanyapi` использует FreeKassa вместо YooKassa.

## 1. Переменные окружения

Обязательные:

```env
FREEKASSA_MERCHANT_ID=12345
FREEKASSA_SECRET_WORD=secret_word_1
FREEKASSA_SECRET_WORD_2=secret_word_2
```

Рекомендуемые:

```env
FREEKASSA_API_KEY=merchant_api_key
FREEKASSA_CURRENCY=RUB
FREEKASSA_LANGUAGE=ru
FREEKASSA_WEBHOOK_PATH=/freekassa/webhook
FREEKASSA_VERIFY_IP=1
```

Опциональные overrides:

```env
FREEKASSA_PAY_BASE_URL=https://pay.fk.money/
FREEKASSA_API_BASE_URL=https://api.fk.life/v1
FREEKASSA_ALLOWED_IPS=168.119.157.136,168.119.60.227,178.154.197.79,51.250.54.238
```

`FREEKASSA_API_KEY` не нужен для создания SCI-ссылки и обработки webhook. Он нужен для кнопки ручной проверки и фоновой сверки зависших `pending`-транзакций.

## 2. Настройки магазина FreeKassa

В кабинете магазина укажите:

- **URL оповещения:** `https://<WEBHOOK_HOST>/freekassa/webhook`
- **Метод оповещения:** `POST`
- **URL успеха:** ссылка на бота или Mini App
- **URL ошибки:** ссылка на бота или Mini App
- **Секретное слово:** значение `FREEKASSA_SECRET_WORD`
- **Секретное слово 2:** значение `FREEKASSA_SECRET_WORD_2`

Альтернативный зарегистрированный путь: `/webhook/freekassa`.

После успешной и полностью обработанной транзакции endpoint отвечает строго `YES`. При временной ошибке БД ответ `YES` не отправляется, чтобы FreeKassa повторила уведомление.

## 3. Платёжный поток

1. Пользователь выбирает пакет.
2. Бот формирует локальный `order_id` и подписанную SCI-ссылку.
3. Транзакция сохраняется со статусом `pending` и provider=`freekassa`.
4. FreeKassa отправляет form-data на Result URL.
5. Бот проверяет:
   - IP отправителя, если `FREEKASSA_VERIFY_IP=1`;
   - `MERCHANT_ID`;
   - MD5-подпись по секретному слову 2;
   - существование заказа;
   - provider транзакции;
   - точное совпадение суммы.
6. `complete_payment_atomic()` атомарно начисляет бананы, промокод и реферальные бонусы.
7. Повторный webhook получает `YES`, но повторного начисления не происходит.

## 4. Nginx

Прокси должен передавать реальный IP:

```nginx
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
```

Если перед приложением есть дополнительный доверенный proxy/CDN, настройте получение реального IP на его уровне. Не отключайте IP-проверку без необходимости.

## 5. Проверка после развёртывания

1. Запустить бота с заполненными переменными.
2. Убедиться в логе:

```text
FreeKassa routes registered: ... enabled=True
```

3. Создать минимальный платёж.
4. Проверить строку в `transactions`: provider=`freekassa`, status=`pending`.
5. Оплатить.
6. Убедиться, что:
   - status стал `completed`;
   - бананы начислены один раз;
   - пользователь получил Telegram-уведомление;
   - Mini App получил уведомление;
   - повтор той же формы webhook отвечает `YES` и не меняет баланс.

## 6. Совместимость

Внутренний символ `yookassa_service` временно оставлен как адаптер для старых импортов и старых версий Mini App. Он не содержит YooKassa SDK и всегда выполняет операции через `freekassa_service`. Новые Telegram-транзакции сохраняются с provider=`freekassa`.
