# Документация NEUROMIX — актуальная карта

**Текущий выпуск:** branch `tanyapi` → отдельная task-ветка → PR в `tanyapi` → обязательные CI → squash auto-merge → production CI/CD → exact-SHA smoke. **`dev` и `main` не участвуют в обычной работе агента без прямой просьбы владельца.** Старый маршрут `dev → tanyapi` в документах разработки — историческая/отдельно включаемая схема, не обязательный шаг.

## С чего начать

| Область | Документы |
| --- | --- |
| Проект и правила агента | [README](../README.md), [AGENTS](../AGENTS.md) |
| Архитектура, API и backend | [architecture.md](architecture.md), [internal-admin-api.md](internal-admin-api.md) |
| **Повтор любой опубликованной генерации** | [PUBLISHED_REPEAT_CONTRACT.md](PUBLISHED_REPEAT_CONTRACT.md) |
| Закрытые reference-файлы | [PRIVATE_REPEAT_REFERENCES.md](PRIVATE_REPEAT_REFERENCES.md), [VIDEO_REPEAT_PROMPT_CONTRACT.md](VIDEO_REPEAT_PROMPT_CONTRACT.md) |
| Wan/Prime все режимы | [wan3-prime-integration.md](wan3-prime-integration.md), [providers/wan3-prime-kie.md](providers/wan3-prime-kie.md) |
| Тренды, папки, успешные повторы | [TREND_SHOWCASE_CATEGORIES.md](TREND_SHOWCASE_CATEGORIES.md) |
| Тарифы и админка | [CREATOR_TARIFF.md](CREATOR_TARIFF.md), [internal-admin-payments-tariffs.md](internal-admin-payments-tariffs.md) |
| Продакшен и CI | [production_auto_deploy.md](production_auto_deploy.md), [production-deployment.md](production-deployment.md) |
| Операции и диагностика | [runbook.md](runbook.md), [troubleshooting.md](troubleshooting.md) |
| Frontend | [frontend README](../frontend/miniapp-v0/README.md) |
| Реферальные начисления | [PARTNER_POLICY.md](PARTNER_POLICY.md), [FEED_SHARE_ATTRIBUTION.md](FEED_SHARE_ATTRIBUTION.md) |
| Media и environment | [media operations](../ops/media/README.md), [environment.md](environment.md) |
| QA и контроль релизов | [QA checklist](../QA_AUDIT_CHECKLIST.md), [repeat-result-regression.md](repeat-result-regression.md), [POST_RELEASE_AUDIT_2026-10-16.md](POST_RELEASE_AUDIT_2026-10-16.md) |

## Production runtime (сверять перед каждым вмешательством)

- Frontend/Mini App: `https://tanyapp.xn--e1aikcel5c5a.online/mini-app/`, статический Next.js на том же Nginx что и media.
- Backend/API/webhooks: `https://tanyapi.chillcreative.ru`.
- Основной checkout: `/root/tanya/banano_kling`; production branch `tanyapi`.
- Runtime: Docker `banano-kling-bot`, локальный `127.0.0.1:1888`. Исторический systemd unit `banano-kling.service` не является текущим backend.
- Текущий деплой: `.github/workflows/deploy-production-reliable.yml` и `deploy-production.yml` вызывают `scripts/deploy_backend_docker.sh` + `scripts/deploy_miniapp_local.sh` на том же хосте.
- Проверка релиза: Git HEAD, Docker `org.opencontainers.image.revision` и публичный `/mini-app/revision.txt` равны точному SHA; контейнер `healthy`.
- `data/price.json` — изменяемые админом тарифы. При deploy **не** заменять его версией из Git.

## Какие документы нормативные

В начале списка — текущий код, схемы БД, реальные GitHub workflows, regression-тесты и запущенная конфигурация. Далее этот индекс и связанные актуальные контракты.

`docs/agents/*`, `docs/research/*`, `docs/*-2026-*.md`, старые примеры provider API — архив исследований и промежуточных решений. Они могут описывать отклонённые идеи (например, запрет remixes или обязательный DEV promotion). **Не использовать их как инструкцию для production без сверки с текущим контрактом.**

[development-deployment.md](development-deployment.md) оставлен как руководство по отдельному DEV-контуру; для обычных изменений действуют `AGENTS.md` и PR прямо в `tanyapi`.

## Изменение документации

В одном PR с изменением API/UI обновлять контракт, модельные ограничения, инструкции и тесты. После выката записывать реальный exact SHA, health, CI, состояние веб-сборки, логи, отрицательные security smoke и отсутствие изменения runtime-цен. Нельзя выдавать mock E2E за подтверждение реальной платной генерации.
