# Документация NEUROMIX

Этот каталог содержит документацию production-ветки `tanyapi` репозитория `Bambale0/banano_kling`.

## Как пользоваться документацией

Для обычной эксплуатации начинайте с документов в таком порядке:

1. [../README.md](../README.md) — что это за система и где она размещена;
2. [production-deployment.md](production-deployment.md) — первичное развёртывание и полный deploy;
3. [runbook.md](runbook.md) — ежедневные команды оператора;
4. [troubleshooting.md](troubleshooting.md) — диагностика ошибок;
5. [architecture.md](architecture.md) — устройство системы и потоки данных.

Для изменения frontend:

1. [../frontend/miniapp-v0/README.md](../frontend/miniapp-v0/README.md);
2. [miniapp-frontend-deployment.md](miniapp-frontend-deployment.md);
3. [branding.md](branding.md).

Для media-домена:

1. [../ops/media/README.md](../ops/media/README.md);
2. `scripts/deploy_media_origin.sh`;
3. `scripts/check_media_delivery.sh`.

## Основные документы

| Документ | Для кого | Что содержит |
| --- | --- | --- |
| [architecture.md](architecture.md) | разработчик, интегратор | компоненты, topology, auth, storage, API и media flows |
| [production-deployment.md](production-deployment.md) | DevOps, владелец проекта | DNS, backend, frontend, media, SSL, Cloudflare, smoke tests и rollback |
| [miniapp-frontend-deployment.md](miniapp-frontend-deployment.md) | frontend/DevOps | `cdn.sh`, remote profile, build, release, cache overlap и npm troubleshooting |
| [environment.md](environment.md) | разработчик, DevOps | env-переменные, обязательность, значения и правила хранения секретов |
| [runbook.md](runbook.md) | оператор | restart, status, logs, health, backup и routine checks |
| [troubleshooting.md](troubleshooting.md) | оператор, разработчик | симптомы, причины, команды диагностики и безопасные действия |
| [branding.md](branding.md) | frontend, контент, QA | пользовательский бренд NEUROMIX и допустимые технические имена |
| [roadmap.md](roadmap.md) | продукт, разработчик | задачи и приоритеты, если документ актуализирован под текущий код |
| [tracemap.md](tracemap.md) | разработчик | индекс пользовательских и технических потоков |
| [migration.md](migration.md) | DevOps, backend | backfill, repair и data migration scripts |
| [postgres-migration.md](postgres-migration.md) | backend, DevOps | перенос и проверка PostgreSQL runtime |
| [zero-downtime-migration.md](zero-downtime-migration.md) | DevOps | перенос backend runtime без длительной остановки |

## Production topology

```text
cdn.chillcreative.ru (91.200.84.187)
  ├── /mini-app/             -> статический Next.js export
  └── /mini-app/api/*        -> HTTPS proxy на tanyapi.chillcreative.ru

tanyapi.chillcreative.ru (144.76.188.75)
  ├── Telegram webhook
  ├── Mini App API
  ├── provider/payment webhooks
  └── aiohttp runtime за локальным Nginx

media.chillcreative.ru (Cloudflare -> 144.76.188.75)
  └── /uploads/*             -> Nginx -> bind mount -> static/uploads
```

## Владение документами

### Операционные документы

Должны обновляться при изменении:

- production-доменов или IP;
- systemd service;
- путей проекта;
- Nginx topology;
- Cloudflare rules;
- deploy scripts;
- env-переменных;
- frontend build process.

К этой группе относятся:

- `README.md`;
- `docs/architecture.md`;
- `docs/production-deployment.md`;
- `docs/miniapp-frontend-deployment.md`;
- `docs/environment.md`;
- `docs/runbook.md`;
- `docs/troubleshooting.md`;
- `ops/media/README.md`;
- `frontend/miniapp-v0/README.md`.

### Provider reference docs

Файлы про отдельные внешние API могут быть снимками документации провайдера и не всегда отражают текущую реализацию. Например:

- `kling_api*.md`;
- `kie_ai_integration.md`;
- `veo_api.md`;
- `motion_control_api.md`;
- `tbank_api.md`;
- `yookassa.md`;
- `crypto_api.md`.

Если reference-документ конфликтует с runtime, приоритет имеют:

1. `bot/services/*`;
2. `bot/main.py` и `bot/miniapp.py`;
3. `bot/config.py`;
4. `tests/*`;
5. фактический ответ провайдера в безопасно очищенных логах.

## Legacy-материалы

В репозитории могут оставаться:

- старые домены;
- старые IP;
- backup-файлы;
- historical tracemap;
- старое название Banano/Banana;
- старые схемы прямого доступа к backend port.

Они не должны использоваться для production-действий без сверки с документами из раздела «Операционные документы».

## Правила обновления документации

При изменении production-инфраструктуры в одном pull request или серии связанных коммитов обновить:

- topology в `README.md` и `architecture.md`;
- команды deploy в соответствующем runbook;
- env-reference, если добавлена или изменена переменная;
- troubleshooting, если появился новый класс ошибки;
- rollback-процедуру;
- дату и фактический результат проверки в описании изменения, но не хранить временные логи и секреты в документах.

## Минимальный documentation review перед релизом

- все пользовательские заголовки используют NEUROMIX;
- указана ветка `tanyapi`;
- frontend указан как `cdn.chillcreative.ru`;
- backend указан как `tanyapi.chillcreative.ru`;
- media указан как `media.chillcreative.ru`;
- нет рекомендаций открывать `:1888` в интернет;
- нет реальных токенов, паролей и содержимого `.env`;
- deploy и rollback команды проверены на синтаксические ошибки;
- различаются ожидаемый `401` без Telegram `initData` и настоящий отказ backend.
