# Unified AccountActor: безопасный read-only релиз

Дата: 20 ноября 2026. База: tanyapi 0aac0576fe1f403b391957dd802d1c45af8ff327. Отдельный небольшой PR, НЕ Draft PR #646.

## Изменения

- bot/shared_accounts/store.py: единый транзакционный helper создания verified shared_accounts; тот же код переиспользуется действующим create_session. Повторное создание идемпотентно и не создаёт новый Telegram user ID.
- bot/shared_accounts/unified_actor.py: AccountActor с account_id, auth_channel, telegram_id (optional), wallet_authority, telegram_linked.
- GET /mini-app/api/web-auth/actor: подтверждённая действующая cookie nm_web_session -> shared account и отдельная web_live authority.
- POST /mini-app/api/web-auth/actor: настоящая подписанная Telegram Mini App initData -> account ID и telegram_legacy authority. Требуется допустимый Origin и валидная подпись.
- Подписанные сервером browser_* initData не считаются запуском Telegram WebView. Им требуется действующая веб-cookie и доказанный link того же Telegram ID; authority остаётся web_live. Logout делает этот способ недействительным.
- Интеграция не меняет существующий Telegram Mini App bootstrap, VK preview, KIE, генерации, тарифы, webhook, платежи, историю, базу legacy money или frontend. Флаги платежей и генерации не включены.

## Проверяемые инварианты

- Веб-аккаунту не создаётся фальшивый Telegram ID.
- Чужая cookie не подменяет владельца signed Telegram initData.
- Отозванная cookie не может использовать backend-signed browser_* bridge.
- Telegram OIDC-link может существовать раньше legacy users row: telegram_linked не доказывает наличие legacy wallet.
- Нет суммирования, клонирования, перевода или округления балансов. Новый read-only endpoint не создаёт проводок.
- Source-scoped wallet_authority — контракт для будущих services, а не разрешение на денежную операцию.

## Тесты и production preflight

- tests/test_unified_actor_contract.py: восемь базовых проверок плюс concurrency и HTTP browser bridge. Отдельно проверены origin, 401/403, revoke, native signature, link/foreign cookie, отсутствие скрытых shared sessions.
- Сохранённые регрессионные наборы: tests/test_shared_accounts.py, test_web_auth_identity.py, test_web_auth_contract.py, test_browser_auth.py.
- В production ранее выполнен ТОЛЬКО read-only аудит scripts/audit_shared_account_migration.py: 94 490 legacy TG users, 392 126 generation_tasks, 35 997 transactions, 854 precision_review, invalid=0, users.credits имеет double precision.
- Перед релизом обязательны полный GitHub CI и exact deployed SHA. После релиза smoke: GET без cookie должен быть 401; POST с чужим Origin — 403; /health — 200; native Telegram UI без регрессий.

## Жёсткие блокеры следующих этапов

Пока не завершены общие задачи, MiniAppShell для веб-only, сохранение legacy payment/refund и миграция финансовой authority, PR #646 нельзя выпускать как 100%-ную кроссплатформенность. Не включать WEB_NATIVE_GENERATION_ENABLED или WEB_NATIVE_PAYMENTS_ENABLED до выполнения P0/P1 ворот из docs/agents/EXECUTION/cross-platform-audit-20261120.md.

## Откат

Revert этого read-only PR при регрессии. Он не изменяет платные задачи, платежи, пользователей Telegram или остатки, сохраняет обратную совместимость существующих маршрутов.
