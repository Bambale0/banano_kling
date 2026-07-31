# Вход в Mini App через обычный браузер

Когда Telegram Mini App передаёт `initData`, приложение использует штатную Mini App-авторизацию. Когда страница открыта в обычном браузере и `initData` отсутствует, пользователь может войти через Telegram Web Login.

## Схема

```text
browser frontend
  -> /mini-app/api/browser-auth/start
  -> Telegram OIDC (Authorization Code + PKCE)
  -> /mini-app/api/browser-auth/callback
  -> backend проверяет id_token через Telegram JWKS
  -> backend выпускает краткоживущий Mini App-compatible init_data
  -> redirect обратно в /mini-app/#tgWebAppData=...
```

Telegram-пользователь определяется по подтверждённому `id` из `id_token`, поэтому браузер и Mini App используют одну запись пользователя, баланс, историю и профиль.

## Настройка BotFather

1. Откройте `@BotFather`.
2. Выберите бота.
3. Перейдите: **Bot Settings → Web Login**.
4. Оставьте алгоритм подписи `RS256` по умолчанию или выберите `ES256`.
5. Добавьте Allowed URLs для каждого frontend-домена:
   - `https://cdn.chillcreative.ru`
   - `https://cdn.chillcreative.ru/mini-app/api/browser-auth/callback`
6. При зеркале или переезде добавьте новый origin и callback до переключения трафика.
7. Скопируйте Client ID и Client Secret.

## Backend `.env`

```dotenv
TELEGRAM_LOGIN_CLIENT_ID=123456789
TELEGRAM_LOGIN_CLIENT_SECRET=secret-from-botfather
TELEGRAM_LOGIN_ALLOWED_ORIGINS=https://cdn.chillcreative.ru
```

Несколько доменов задаются через запятую:

```dotenv
TELEGRAM_LOGIN_ALLOWED_ORIGINS=https://cdn.chillcreative.ru,https://app2.example.ru
```

Активный origin из `MINI_APP_URL` также автоматически считается разрешённым.

После изменения:

```bash
cd /root/tanya/banano_kling
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart banano-kling
```

На frontend-сервере повторно запустите `cdn.sh` и выберите обновление существующего frontend. Дополнительный Nginx location не нужен: маршрут использует уже существующий proxy `/mini-app/api/` на backend Nginx по 443.

## Безопасность

- Client Secret хранится только на backend.
- Используется Authorization Code Flow с PKCE, `state` и `nonce`.
- `id_token` проверяется по Telegram JWKS, issuer, audience, expiry и nonce.
- Авторизационный код и токены не пишутся в логи.
- Возвращаемый `init_data` помещается в URL fragment и не попадает в access-log.
- Время жизни browser `init_data` соответствует текущему серверному лимиту Mini App — 24 часа.
