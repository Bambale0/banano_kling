# NEUROMIX: production CI/CD

**Единственная production-ветка:** `tanyapi`. Для обычной разработки создавать task branch от `origin/tanyapi`, затем PR обратно в `tanyapi`. `main` и `dev` не участвуют в обычном production выпуске без отдельного распоряжения владельца.

## Release graph

```text
origin/tanyapi
  └─ fix/* | feature/* | docs/* → PR в tanyapi
       → обязательные Python / PostgreSQL / Mini App / browser / Wan CI
       → protected squash auto-merge
       → production CI на merge SHA
       → reliable SSH deploy с lock
       → Docker bot build/restart/healthy
       → Next.js static export на этом же сервере
       → public /mini-app/revision.txt и health
       → smoke логов, Repeat/Trend/Media, проверка админских тарифов
```

Текущие workflow-файлы: `.github/workflows/deploy-production-reliable.yml` и `.github/workflows/deploy-production.yml`. Оба отслеживают `tanyapi` и требуют проверку **точного** SHA `.github/workflows/ci.yml`. Не рассчитывать на вымышленный `deploy-frontend-production.yml`: текущий frontend в production публикуется **локально на том же сервере** через `scripts/deploy_miniapp_local.sh`.

## Deployment contract

1. Exact-SHA CI завершён `success`.
2. SSH с pinned host key и ограниченными production secrets из GitHub; отказ при отсутствии конфигурации.
3. Production checkout `/root/tanya/banano_kling` в `tanyapi`, целевой SHA равен `origin/tanyapi`.
4. Deploy lock и проверка tracked local changes; **не** переключать ветки и не перезаписывать operator/runtime файлы.
5. `data/price.json` проверяется как валидный JSON и **сохраняется без замены** Git default даже при изменениях цены администратором. Проверить hash до/после.
6. `scripts/deploy_backend_docker.sh deploy` и `status`, Docker `banano-kling-bot` должен быть `healthy`, label `org.opencontainers.image.revision` равен ожидаемому SHA.
7. `scripts/deploy_miniapp_local.sh <expected-sha>` публикует статическую Mini App. Публичный `/mini-app/revision.txt` должен совпасть с SHA.
8. Health/API/webhook отрицательные probe, после — read-only пользовательские smoke и логи. Webhook `401` без подписи может быть ожидаемым.

Не копировать production secrets в development. Не публиковать BOT_TOKEN, signed URLs, приватные provider/media данные в логи и отчёты.

## Проверки после deploy

```bash
cd /root/tanya/banano_kling
git rev-parse HEAD
docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}} {{.State.Health.Status}}' banano-kling-bot
curl -fsS https://tanyapi.chillcreative.ru/health
curl -fsS https://tanyapp.xn--e1aikcel5c5a.online/mini-app/revision.txt
sha256sum data/price.json
docker logs --since 30m --tail 200 banano-kling-bot
```

Сверить одни и те же SHA, затем открыть опубликованное фото и видео, проверить **повтор выбранной работы**, скрытые и заменяемые референсы, стоимость и отсутствие двойного дебета. Уведомления Telegram могут отсутствовать, если чата у пользователя нет; Studio обязана получать терминальный результат.

## Rollback

Предпочтительный rollback — отдельный revert PR в `tanyapi` с полным CI/автодеплоем и повторной проверкой тарифов. Аварийное использование `scripts/deploy_backend_docker.sh rollback` допускается только с разрешением и пониманием состояния бэкапов. **Не выполнять `git reset --hard` над production checkout:** возможно уничтожение администраторских цен. Если CI/deploy не завершился, не писать пользователям «в проде».

## DEV — справочная схема

[development-deployment.md](development-deployment.md) описывает отдельного DEV-бота, историческую практику `dev → tanyapi`, тестовые токены и изоляцию БД. Она **не** предписывает такой маршрут для обычных задач в нынешнем проекте. Актуальные правила зафиксированы в `AGENTS.md`.
