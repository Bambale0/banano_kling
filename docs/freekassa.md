# FreeKassa — настройка резервной оплаты

В ветке `tanyapi` основной рублёвый checkout — Robokassa (`СБП / карта`). FreeKassa / KASSA используется вторым, резервным рублёвым способом:

- **основной RUB** — Robokassa;
- **резервная карта РФ** — KASSA (`i=36`);
- **резервный СБП** — KASSA (`i=44`);
- **Lava** — дополнительный рублёвый и зарубежный способ ниже основных вариантов;
- зарубежная / СНГ — Tribute.

В интерфейсе KASSA явно подписана как резерв. Её callbacks и платёжная логика не меняются: меняются только пользовательский приоритет и подписи.

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

### Резервный рублёвый flow KASSA

1. Пользователь выбирает пакет.
2. Резервные кнопки KASSA сразу выбирают карту РФ (`i=36`) или СБП (`i=44`).
3. Бот формирует локальный `order_id`, сохраняет `pending`-транзакцию с `provider=freekassa` и выдаёт подписанную ссылку `/freekassa/checkout`.
4. Промежуточная страница запрашивает реальный email, а сервер получает IP клиента из reverse proxy.
5. Сервер создаёт заказ через `POST https://api.fk.life/v1/orders/create` с `shopId`, строго возрастающим `nonce`, HMAC-SHA256 `signature`, `paymentId`, выбранным `i`, `email`, `ip`, `amount` и `currency`.
6. Пользователь перенаправляется только на `location` из успешного ответа FreeKassa.
7. FreeKassa отправляет form-data на Result URL.
8. Бот проверяет IP отправителя (если включено), `MERCHANT_ID`, MD5-подпись по секретному слову 2, существование заказа, provider транзакции и точное совпадение суммы.
9. `complete_payment_atomic()` начисляет бананы атомарно. Повторный webhook получает `YES`, но повторного начисления не происходит.

Методы `36` и `44` создаются через API `orders/create`, а не через SCI-ссылку `pay.fk.money`.

### Дополнительный Lava

Lava не удаляется: её рублёвые карта/СБП и зарубежные карта/PayPal остаются независимыми callbacks Lava, но в пользовательском списке располагаются ниже Robokassa, KASSA и основных альтернатив.

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
3. Открыть пополнение и проверить порядок: `💳 СБП / карта · Robokassa` → резерв KASSA (карта/СБП) → `🌍 Зарубежная / СНГ` → остальные альтернативы → Lava ниже.
4. Проверить Mini App: блок `Robokassa · основной способ` должен идти первым, `Резерв · KASSA` — вторым, а `Lava · дополнительный способ` — ниже.
5. В KASSA проверить оба основных варианта: карта РФ (`i=36`) и СБП (`i=44`).
6. Убедиться, что новая транзакция сохраняется с `provider=freekassa`, `status=pending`, а `/freekassa/checkout` запрашивает email перед созданием provider order.
7. После оплаты убедиться, что status стал `completed`, бананы начислены один раз, а повтор того же webhook отвечает `YES` без повторного изменения баланса.
8. В логах не должно быть серии ошибок FreeKassa про неупорядоченный/повторный `nonce` при фоновой сверке.

## 7. Совместимость

Внутренний символ `yookassa_service` временно оставлен как адаптер для старых импортов. Он не содержит YooKassa SDK и выполняет операции через `freekassa_service` только для legacy-вызовов.

Production routing для RUB:

```text
СБП / карта               -> Robokassa (основной)
Резерв · карта            -> KASSA / FreeKassa (i=36)
Резерв · СБП              -> KASSA / FreeKassa (i=44)
Доп. карта / СБП          -> Lava
```
