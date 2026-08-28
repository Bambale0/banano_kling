# FreeKassa — настройка оплаты

В ветке `tanyapi` рублёвые способы оплаты разделены по провайдерам:

- **карта РФ** — Lava;
- **СБП** — FreeKassa (`KASSA` в пользовательском интерфейсе);
- FreeKassa также остаётся доступной как резервный раздел `РФ — KASSA (резерв)`.

Новые СБП-платежи через Lava не создаются. Старые уже отправленные Telegram-кнопки `buy_lava_sbp_*` и legacy `buy_lava_<package>` перенаправляются в текущий FreeKassa SBP flow.

## Быстро: что вставить в кабинет FreeKassa

Для текущего продакшн-домена:

```text
URL оповещения: https://tanyapi.chillcreative.ru/freekassa/webhook
Метод оповещения: POST
```

```text
URL успешной оплаты: https://tanyapi.chillcreative.ru/payment/success
Метод успешной оплаты: GET
```

```text
URL возврата в случае неудачи: https://tanyapi.chillcreative.ru/payment/fail
Метод возврата в случае неудачи: GET
```

Секреты:

```text
Секретное слово: значение FREEKASSA_SECRET_WORD из .env
Секретное слово 2: значение FREEKASSA_SECRET_WORD_2 из .env
```

Не вставляйте секреты в Git и публичные документы. Значения должны совпадать между кабинетом FreeKassa и `.env` на сервере.

## 1. Переменные окружения

Обязательные:

```env
FREEKASSA_MERCHANT_ID=12345
FREEKASSA_SECRET_WORD=secret_word_1
FREEKASSA_SECRET_WORD_2=secret_word_2
```

Для прямого СБП также обязателен API key:

```env
FREEKASSA_API_KEY=merchant_api_key
```

Рекомендуемые:

```env
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

`FREEKASSA_API_KEY` обязателен для методов `36` и `44`: заказ создаётся через API `POST /orders/create`. Он также используется для ручной проверки и фоновой сверки `pending`-транзакций.

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

### Прямой СБП

1. Пользователь выбирает пакет и нажимает `⚡ СБП`.
2. Callback сразу идёт в FreeKassa с методом **СБП `i=44`**; Lava в этом пути не вызывается.
3. Бот формирует локальный `order_id`, сохраняет `pending`-транзакцию с `provider=freekassa` и выдаёт подписанную ссылку `/freekassa/checkout`.
4. Промежуточная страница запрашивает реальный email, а сервер получает реальный IP из доверенного reverse proxy.
5. Сервер отправляет JSON в `POST https://api.fk.life/v1/orders/create` с `shopId`, уникальным `nonce`, HMAC-SHA256 `signature`, `paymentId`, `i=44`, `email`, `ip`, `amount` и `currency`.
6. Пользователь перенаправляется только на `location` из успешного ответа FreeKassa.
7. FreeKassa отправляет form-data на Result URL.
8. Бот проверяет:
   - IP отправителя, если `FREEKASSA_VERIFY_IP=1`;
   - `MERCHANT_ID`;
   - MD5-подпись по секретному слову 2;
   - существование заказа;
   - provider транзакции;
   - точное совпадение суммы.
9. `complete_payment_atomic()` атомарно начисляет бананы, промокод и реферальные бонусы.
10. Повторный webhook получает `YES`, но повторного начисления не происходит.

### Карта РФ

Кнопка `💳 Картой` остаётся на текущем Lava flow. Замена СБП не меняет карточные платежи Lava, CryptoBot, Stars и остальные способы оплаты.

### Резервный раздел KASSA

В `РФ — KASSA (резерв)` по-прежнему доступны:

- карта РФ — `i=36`;
- СБП — `i=44`.

Методы `36` и `44` нельзя передавать в SCI-ссылке `pay.fk.money`: runtime создаёт их через API `orders/create`.

## 4. Совместимость старых кнопок

Старые сообщения Telegram могут содержать callbacks:

```text
buy_lava_sbp_<package>
buy_lava_<package>
```

Оба варианта исторически означали СБП. После миграции они адаптируются к `freekassa_sbp_<package>` и не создают Lava invoice.

Если пользователь находился в старом FSM-шаге ввода email для Lava SBP непосредственно во время обновления, такой checkout блокируется: бот предлагает повторно выбрать СБП, уже через FreeKassa. Это исключает создание нового Lava SBP после переключения провайдера.

## 5. Nginx

Прокси должен передавать реальный IP:

```nginx
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
```

Если перед приложением есть дополнительный доверенный proxy/CDN, настройте получение реального IP на его уровне. Не отключайте IP-проверку без необходимости.

## 6. Проверка после развёртывания

1. Запустить бота с заполненными переменными FreeKassa, включая `FREEKASSA_API_KEY`.
2. Убедиться в логе:

```text
FreeKassa routes registered: ... enabled=True
```

3. Открыть пополнение и проверить:
   - `💳 Картой` создаёт `provider=lava`;
   - `⚡ СБП` создаёт `provider=freekassa`;
   - в новых кнопках отсутствует `buy_lava_sbp_*`.
4. Создать минимальный СБП-платёж.
5. Проверить строку в `transactions`: provider=`freekassa`, status=`pending`.
6. На `/freekassa/checkout` ввести реальный email; API-заказ должен создаваться с `i=44`.
7. Оплатить.
8. Убедиться, что:
   - status стал `completed`;
   - бананы начислены один раз;
   - пользователь получил Telegram-уведомление;
   - Mini App получил уведомление;
   - повтор той же формы webhook отвечает `YES` и не меняет баланс.

## 7. Совместимость

Внутренний символ `yookassa_service` временно оставлен как адаптер для старых импортов. Он не содержит YooKassa SDK и выполняет операции через `freekassa_service` только для legacy-вызовов.

Новый production routing для RUB:

```text
Карта РФ -> Lava
СБП      -> FreeKassa (i=44)
```
