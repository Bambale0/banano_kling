# NEUROMIX: рабочий runbook production

**Источник:** `AGENTS.md`, текущие `.github/workflows/deploy-production-reliable.yml` и `deploy-production.yml`. Никаких штатных действий с `dev`/`main`, устаревшим systemd `banano-kling.service` или отдельным `cdn.chillcreative.ru` при обычном выпуске.

## Инвентарь

| Компонент | Адрес/место |
| --- | --- |
| Backend | `https://tanyapi.chillcreative.ru`, Docker `banano-kling-bot`, локально `127.0.0.1:1888` |
| Mini App и uploads | `https://tanyapp.xn--e1aikcel5c5a.online/mini-app/`, `/uploads/` через Nginx |
| Checkout | `/root/tanya/banano_kling`, ветка `tanyapi` |
| Frontend deploy | `scripts/deploy_miniapp_local.sh`, статические файлы в `/var/www/tanyapp.xn--e1aikcel5c5a.online/mini-app` |
| Admin prices | `data/price.json` в runtime — **нельзя** перезаписывать git-версией |
| Logs | `docker logs banano-kling-bot`, `logs/bot.log*` (если file logging включён) |

## Проверить сервис и релиз (без изменений)

```bash
cd /root/tanya/banano_kling
git rev-parse HEAD
git status --short --branch
docker ps --filter name=banano-kling-bot
docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}} {{.State.Health.Status}}' banano-kling-bot
curl -fsS --max-time 15 https://tanyapi.chillcreative.ru/health
curl -fsSI --max-time 15 https://tanyapp.xn--e1aikcel5c5a.online/mini-app/
curl -fsS --max-time 15 https://tanyapp.xn--e1aikcel5c5a.online/mini-app/revision.txt
sha256sum data/price.json
```

`git HEAD`, Docker revision и Mini App revision должны равняться **одному ожидаемому squash merge SHA**. `healthy` и HTTP 200 обязательны, но сами по себе не доказывают корректность пользовательского сценария.

## Логи и диагностика (не публиковать пользовательские данные)

```bash
docker logs --since 30m --tail 500 banano-kling-bot
docker inspect --format '{{.State.Health.Status}}' banano-kling-bot
tail -n 200 logs/bot.log
```

Искать по безопасным task/correlation IDs, модели, статусу/кодам ошибок, времени, попыткам delivery и refund. Не выводить полные prompt, приватные URLs, Telegram initData, подписанные media ссылки или платежные токены. `WARNING` с HTTP 200 сам по себе не означает сбой; сопоставить контекст и частоту.

## Стандартный релиз

1. От актуального `origin/tanyapi` создать отдельную рабочую ветку/worktree.
2. Изменить код и документацию, запустить целевые regression/TS/Jest/browser проверки.
3. PR **в `tanyapi`**, обязательные CI и review, включить squash auto-merge. Не прямой push и не `dev`.
4. После merge ждать успешный exact-SHA production workflow; он последовательно обновляет Docker и Mini App через SSH с deploy lock.
5. Повторить проверки выше, сверить конфигурацию и публичную Mini App, затем тесты **без платного создания задач**.
6. Проверить логи за период deploy и последние пользовательские ошибки. Если нужна платная реальная генерация, отдельно согласовать.

**Никогда не применять `git reset --hard` к рабочему production checkout для обычного deploy:** `data/price.json` обновляется администратором, workflow специально сохраняет его. Не удалять вручную `data/diagnostics/` или media/uploads как «мусор».

## Smoke опубликованных генераций

- Открыть тренд/публикацию: preview, счётчик успешных повторов, ссылка и разрешённые параметры.
- Открыть «Повторить» у обычной работы и у опубликованного результата тренда/ремикса/повтора **для фото и видео**. Источник должен быть **выбранной работой**, не её предком.
- Скрытые fixed URLs/prompt не должны выходить в public response. Слоты upload требуют свои media. Отозванная публикация должна возвращать безопасную ошибку до оплаты.
- Видеореференсы: цена считает действительные входные + выходные секунды; отсутствие измерения не превращается в ×2.
- Wan: read-only repeat-plan для публикации должен вернуть `source_feed_gen_id` текущего post и правильные roles/slots; при недостающем файле UI показывает действие, а не безусловный «запрет автора».
- Telegram: если бот не запущен, «Пропустить» остаётся добровольным, Mini App/Studio работают независимо; результат в чат отправлять только при его доступности.

## Результаты, оплата, сбои

- Уточнить терминальный статус `completed/failed` в БД и число попыток delivery; отказ Telegram чата не должен скрывать результат в Studio.
- Провайдер 5xx / upload error и `repeat_permission_changed` — разные проблемы. Временный сбой не отнимает право повтора, а настоящий отзыв/удаление блокирует server-side использование.
- Проверить, что оплата берётся единожды по текущему quote, двойной callback не повторяет debit, неуспешный terminal job делает правильный refund.
- Любой HTTP/API/smoke без подписи ожидаемо может возвращать `401/403`. **Не** отправлять платные задачи для проверки доступа.

## Incident / rollback

При несовпадении SHA, красном health, неверной цене или массовых ошибках **остановить выпуск**, собрать только очищенные логи и точный PR/commit. При необходимости откатить **через revert PR в `tanyapi`**, затем ждать штатного deploy; `scripts/deploy_backend_docker.sh rollback` — только для согласованной аварийной операции с резервной копией и подтверждением состояния. Не отменять одновременно несколько релизов без проверки их зависимостей.

[Архив прежнего systemd/CDN runbook](legacy/runbook-legacy-systemd-cdn.md) оставлен только для истории.
