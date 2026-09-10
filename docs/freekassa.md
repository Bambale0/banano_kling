# FreeKassa — настройка оплаты

В ветке `tanyapi` FreeKassa возвращена как отдельный резервный рублёвый способ оплаты:

- **карта РФ** — основной Lava flow;
- **СБП** — основной Lava flow;
- **FreeKassa / KASSA** — третий пункт в списке, `РФ — KASSA (резерв)`, с отдельными вариантами карта РФ и СБП;
- зарубежная / СНГ — Tribute, затем резервные зарубежные методы Lava.

FreeKassa не подменяет Lava: пользователь явно выбирает резервный раздел KASSA, после чего выбирает карту РФ (`i=36`) или СБП (`i=44`).

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

### Резервный раздел KASSA

1. Пользователь выбирает пакет.
2. В списке способов оплаты после `💳 Картой` и `⚡ СБП` показывается третий пункт `🇷🇺 РФ — KASSA (резерв)`.
3. Внутри KASSA пользователь выбирает карту РФ (`i=36`) или СБП (`i=44`).
4. Бот формирует локальный `order_id`, сохраняет `pending`-транзакцию с `provider=freekassa` и выдаёт подписанную ссылку `/freekassa/checkout`.
5. Промежуточная страница запрашивает реальный email, а сервер получает IP клиента из reverse proxy.
6. Сервер создаёт заказ через `POST https://api.fk.life/v1/orders/create` с `shopId`, строго возрастающим `nonce`, HMAC-SHA256 `signature`, `paymentId`, выбранным `i`, `email`, `ip`, `amount` и `currency`.
7. Пользователь перенаправляется только на `location` из успешного ответа FreeKassa.
8. FreeKassa отправляет form-data на Result URL.
9. Бот проверяет IP отправителя (если включено), `MERCHANT_ID`, MD5-подпись по секретному слову 2, существование заказа, provider транзакции и точное совпадение суммы.
10. `complete_payment_atomic()` начисляет бананы атомарно. Повторный webhook получает `YES`, но повторного начисления не происходит.

Методы `36` и `44` создаются через API `orders/create`, а не через SCI-ссылку `pay.fk.money`.

### Основные рублёвые способы

`💳 Картой` и `⚡ СБП` остаются на Lava. FreeKassa — независимый резерв и не перехватывает callbacks Lava.

## 4. Совместимость старых кнопок

- `buy_freekassa_<package>` открывает выбор FreeKassa карта/СБП.
- `freekassa_card_<package>` и `freekassa_sbp_<package>` создают FreeKassa-транзакцию.
- legacy `buy_yookassa_<package>` сохраняется только как совместимый вход в FreeKassa card flow.
- `buy_lava_sbp_<package>` и остальные Lava callbacks остаются на Lava и не перенаправляются в FreeKassa.

## 5. Nginx

Прокси должен передавать реальный IP:

```nginx
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
```

Если перед приложением есть дополнительный доверенный proxy/CDN, настройте получение реального IP на его уровне. Не отключайте IP-проверку без необходимости.

## 6. Проверка после развёртывания

1. Запустить бота с заполненными переменными FreeKassa, включая `FREEKASSA_API_KEY`.
2. Убедиться, что в логе FreeKassa routes зарегистрированы один раз и `enabled=True`, `api_enabled=True`.
3. Открыть пополнение и проверить порядок: `💳 Картой` → `⚡ СБП` → `🇷🇺 РФ — KASSA (резерв)` → `🌍 Зарубежная / СНГ` → зарубежный резерв Lava.
4. Проверить тот же порядок в Mini App: KASSA должна быть доступна как отдельный резерв до зарубежных способов.
5. В KASSA проверить оба варианта: карта РФ (`i=36`) и СБП (`i=44`).
6. Убедиться, что новая транзакция сохраняется с `provider=freekassa`, `status=pending`, а `/freekassa/checkout` запрашивает email перед созданием provider order.
7. После оплаты убедиться, что status стал `completed`, бананы начислены один раз, а повтор того же webhook отвечает `YES` без повторного изменения баланса.
8. В логах не должно быть серии ошибок FreeKassa про неупорядоченный/повторный `nonce` при фоновой сверке.

## 7. Совместимость

Внутренний символ `yookassa_service` временно оставлен как адаптер для старых импортов. Он не содержит YooKassa SDK и выполняет операции через `freekassa_service` только для legacy-вызовов.

Production routing для RUB:

```text
Карта РФ              -> Lava
СБП                    -> Lava
РФ — KASSA (резерв)   -> FreeKassa (карта i=36 / СБП i=44)
```
