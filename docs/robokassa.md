# Robokassa — основной RUB checkout

## Переменные окружения

```env
PAYMENT_PROVIDER=robokassa
ROBOKASSA_MERCHANT_LOGIN=<идентификатор магазина>
ROBOKASSA_PASSWORD1=<боевой пароль #1>
ROBOKASSA_PASSWORD2=<боевой пароль #2>
ROBOKASSA_HASH_ALGORITHM=md5
ROBOKASSA_TEST_MODE=false
ROBOKASSA_WEBHOOK_PATH=/robokassa/result
```

Для тестового режима дополнительно задаются отдельные `ROBOKASSA_TEST_PASSWORD1` и
`ROBOKASSA_TEST_PASSWORD2`, после чего `ROBOKASSA_TEST_MODE=true`. Боевые пароли не
используются как fallback для тестового режима.

Секреты хранятся только в runtime environment и не коммитятся.

## Настройки магазина Robokassa

- Result URL: `https://tanyapi.chillcreative.ru/robokassa/result`
- Result URL method: `POST`
- Success URL: `https://t.me/Neuromixx_bot`
- Success URL method: `GET`
- Fail URL: `https://t.me/Neuromixx_bot`
- Fail URL method: `GET`
- Hash algorithm: тот же, что в `ROBOKASSA_HASH_ALGORITHM` (сейчас `MD5`)

Result URL — единственный источник подтверждения оплаты для начисления бананов.
Success URL используется только как возврат пользователя после оплаты.

## Контракт

Checkout подписывается Password #1. Result URL проверяется Password #2. Перед
начислением дополнительно сверяются `InvId`, провайдер транзакции и `OutSum`.
Завершение платежа проходит через существующий атомарный payment completion flow,
поэтому повторная доставка callback возвращает `OK{InvId}` без повторного начисления.

FreeKassa и Lava остаются резервными способами оплаты.
