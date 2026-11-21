# NEUROMIX — независимые публичные веб-ссылки

Дата: 2026-11-21. Исходная база tanyapi@c806d7f3. Релиз зависит от PR #675: для связанных Telegram/Yandex аккаунтов параметр web=1 обязан открывать браузерную, а не Telegram-студию.

## Причина
Старый Mini App bootstrap и партнерский API возвращают платформенные deep links t.me; профиль и партнёрская карточка отображали их как ссылки для публикации. Независимые браузерные аккаунты не имели стабильного публичного кода и безопасного публичного профиля. После входа по web ref код не закреплялся в базе.

## Контракт
Профиль: https://neuromixbot.com/mini-app/?web=1&profile=SEL4DQAP&ref=SEL4DQAP
Реферал: https://neuromixbot.com/login?web=1&ref=SEL4DQAP

Сервер использует только WEB_AUTH_PUBLIC_ORIGIN, не доверяет заголовку Host. Внутри UI ссылка строится относительно window.location.origin. Telegram bot links и VK-native flows остаются неизменными.

## Реализация
- GET /mini-app/api/web-auth/public-links возвращает web URLs для действующей HttpOnly сессии. Код хранится в web_public_profile_codes: случайный W-префикс для самостоятельного веб-аккаунта или существующий старый реферальный код для проверенного Telegram-linked аккаунта.
- GET /mini-app/api/web-auth/public-profile?code=... публичен; показывает только публичное имя автора. Никаких приватных промптов, балансов, почты, токенов или неопубликованных результатов. Веб-публикации пока не выводятся на этот экран.
- POST /mini-app/api/web-auth/referral/attach фиксирует источник после проверенной веб-сессии, однократно, с проверкой Origin, self-referral, дублей, поздних платежных заказов и генераций. Учитываются алиасы уже слитых аккаунтов.
- Таблицы web_public_profile_codes и web_referral_attributions создаются идемпотентно под транзакционной блокировкой. Изменений в users.credits, существующих кошельках или платёжных заказах нет.
- BrowserAccountWorkspace отображает обе ссылки и поддерживает копирование; гостевой вход сохраняет ref; анонимный профиль доступен без TG авторизации. ProfileTab и партнерские экраны показывают сайт вместо старого t.me.

## Финансовое ограничение
Запись приглашения НЕ равна денежному партнерскому начислению. Выплаты ROX/RUB для веб-only рефералов пока не включены: необходима подтвержденная оплата, антифрод и reconciliation с общим ledger. Не считать этот PR полной коммерческой миграцией партнерских комиссий.

## Проверки
Backend pytest: idempotent links/referral, linked legacy code, anonymous profile, hostile origin, invalid code, concurrency и поздние инвойсы.
Frontend Jest: безопасный URL builder, native profile, partner copy, браузерная сессия, сохранение ref, отсутствие приватного контента на публичной странице.
Chromium E2E: public profile без cookie и private APIs, authenticated website referral, OAuth continuation, сохранённые старые сценарии.
CI, exact-SHA production deploy и smoke обязательны до статуса released.
