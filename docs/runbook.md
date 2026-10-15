# Runbook NEUROMIX

## 1. Production inventory — актуальный контур

| Компонент | Значение |
| --- | --- |
| Backend/frontend host | `144.76.188.75` |
| Backend origin | `https://tanyapi.chillcreative.ru` |
| Mini App / media | `https://tanyapp.xn--e1aikcel5c5a.online/mini-app/` и `/uploads/*` |
| Production checkout | `/root/tanya/banano_kling`, ветка `tanyapi` |
| Backend runtime | Docker `banano-kling-bot` (Compose service `bot`) |
| Backend local HTTP | `127.0.0.1:1888` за Nginx, не открывать наружу |
| Frontend root | `/var/www/tanyapp.xn--e1aikcel5c5a.online/mini-app` |
| Source of truth | `AGENTS.md`, [production_auto_deploy.md](production_auto_deploy.md) |

Предыдущие `banano-kling.service`, отдельный сервер `91.200.84.187` и `cdn.chillcreative.ru` относятся к legacy. Не применять их инструкции для обычного релиза.

## 2. Ежедневная read-only проверка

```bash
cd /root/tanya/banano_kling
git status --short --branch
git rev-parse HEAD
docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' banano-kling-bot
docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' banano-kling-bot
curl -fsS https://tanyapi.chillcreative.ru/health
curl -fsSI https://tanyapp.xn--e1aikcel5c5a.online/mini-app/
curl -fsS https://tanyapp.xn--e1aikcel5c5a.online/mini-app/revision.txt
```

Для успешного релиза SHA из `git rev-parse`, OCI revision и `revision.txt` совпадают с точным merge SHA в GitHub. Проверить, что администраторские изменения `data/price.json` не затёрты автодеплоем.

## 3. Логи и корреляция

```bash
docker logs --since 1h --tail 400 banano-kling-bot
tail -n 150 /root/tanya/banano_kling/logs/bot.log
```

File log может отсутствовать. При проблеме с повтором/доставкой собрать только task ID, модель, endpoint, status, error code, timestamp, commit SHA, баланс до/после и результат quote/повтора; не раскрывать ссылки скрытых референсов, содержимое prompt, приватные media, Telegram initData или токены.

## 4. Burst-autoban anti-fraud

Партнёрский антифрод теперь автоматически банит владельца рефкода, если по нему за короткое окно приходит аномально плотная пачка новых рефералов.

Текущие runtime-пороги задаются env-переменными:

```text
REFERRAL_ANTIFRAUD_BURST_WINDOW_SECONDS
REFERRAL_ANTIFRAUD_BURST_MAX
```

По умолчанию production считает suspicious burst как `6` привязок за `10` секунд.

Что проверять оператору:

1. открыть админку `Партнёры -> Burst autobans`;
2. открыть карточку партнёра по кнопке из списка;
3. сверить `referral_code`, `visitor_telegram_id`, `source`, `start_param`;
4. при необходимости выгрузить deeper evidence через SQL по `referral_events`.

Быстрый SQL:

```sql
SELECT created_at, visitor_telegram_id, clicked_code, source, start_param
FROM referral_events
WHERE reason = 'burst_autoban'
ORDER BY created_at DESC
LIMIT 50;
```

## 5. Штатный выпуск backend + frontend

```text
origin/tanyapi -> отдельная task-ветка -> PR в tanyapi
 -> protected checks -> squash auto-merge -> production CI/CD
 -> exact-SHA backend+frontend + health/telemetry
```

Штатное обновление **не** выполняют через `git reset --hard` в работающем checkout, `systemctl restart banano-kling.service` или `cdn.sh --remote-deploy tanyafrontend`. Runtime `data/price.json` содержит управляемые администратором тарифы, которые не должны быть переписаны Git defaults. Рабочие локальные изменения, диагностика и серверные файлы не удаляются ради «чистого статуса».

Проверить релиз:

```bash
gh pr view PR_NUMBER --repo Bambale0/banano_kling --json state,mergeCommit
gh run list --repo Bambale0/banano_kling --branch tanyapi --limit 8
git -C /root/tanya/banano_kling rev-parse HEAD
docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' banano-kling-bot
curl -fsS https://tanyapp.xn--e1aikcel5c5a.online/mini-app/revision.txt
```

При ошибке deploy — читать [production-deployment.md](production-deployment.md) и workflow logs, использовать revert PR либо явно согласованное восстановление; не применять ручной reset без проверки tracked/runtime данных.

## 6. Frontend smoke

```bash
curl -fsSI https://tanyapp.xn--e1aikcel5c5a.online/mini-app/
curl -fsS https://tanyapp.xn--e1aikcel5c5a.online/mini-app/revision.txt
curl -sS -i -X POST https://tanyapp.xn--e1aikcel5c5a.online/mini-app/api/bootstrap   -H 'Content-Type: application/json' --data '{}'
```

`401/403` без Telegram `init_data` — ожидаемо и не является сбоем. `502/503/504` — инфраструктурная неисправность. В Telegram WebView полностью закрыть/открыть Mini App, проверить актуальную версию, историю и Feed/Profile; не удалять старые hashed assets, которые может запрашивать открытая WebView-сессия.

## 7. Исторический отдельный CDN: troubleshooting логов

> Этот раздел ниже относится к legacy separate-host `91.200.84.187` и `cdn.sh`. Для текущего production Mini App используйте `/mini-app/revision.txt` и GitHub workflow logs; ручной remote deploy здесь не требуется.

## 7a. Legacy frontend deploy logs

На операторском/backend host:

```bash
tail -n 200 /var/log/banano-miniapp-cdn.log
```

На frontend host:

```bash
ssh root@91.200.84.187 '
  tail -n 200 /var/log/banano-miniapp-cdn.log 2>/dev/null || true
  LAST=$(ls -t /root/.npm/_logs/*.log 2>/dev/null | head -n1)
  [ -n "$LAST" ] && tail -n 200 "$LAST" || true
'
```

## 8. Media checks

Найти реальный публичный файл в `static/uploads` и проверить новый canonical origin:

```bash
curl -sSI https://tanyapp.xn--e1aikcel5c5a.online/uploads/feed/<real-file.webp>
curl -sS -o /dev/null -H 'Range: bytes=0-1023' \
  -w '%{http_code}\n' \
  https://tanyapp.xn--e1aikcel5c5a.online/uploads/<real-video.mp4>
```

Проверить:

- обычный файл возвращает `200`;
- валидный Range-запрос видео возвращает `206`;
- `content-type` соответствует файлу;
- новые API/Telegram/Mini App ссылки используют `tanyapp.xn--e1aikcel5c5a.online`;
- старый `tanyapi.chillcreative.ru/uploads/...` остаётся только backward-compatible входом.

## 9. Проверка media routing

Текущий production не требует отдельного bind mount для media: vhost `tanyapp.xn--e1aikcel5c5a.online` проксирует `/uploads/` и `/genjutsu/` на backend `127.0.0.1:1888`.

```bash
test -d /root/tanya/banano_kling/static/uploads
sudo nginx -t
sudo grep -nE 'location .*(/uploads/|/genjutsu/)' \
  /etc/nginx/sites-available/tanyapp.xn--e1aikcel5c5a.online.conf
```

## 10. Nginx checks

### Backend/media host

```bash
sudo nginx -t
sudo systemctl status nginx --no-pager
sudo journalctl -u nginx -n 100 --no-pager
```

> Исторический отдельный `91.200.84.187` Nginx не является текущим хостом Mini App; не использовать его для production-инцидентов.

## 10a. TLS checks (production + historical origin)

```bash
openssl s_client \
  -connect cdn.chillcreative.ru:443 \
  -servername cdn.chillcreative.ru \
  -verify_return_error </dev/null

openssl s_client \
  -connect tanyapp.xn--e1aikcel5c5a.online:443 \
  -servername tanyapp.xn--e1aikcel5c5a.online \
  -verify_return_error </dev/null
```

Certbot renewal dry-run на нужном host:

```bash
sudo certbot renew --dry-run --no-random-sleep-on-renew
```

## 11. Telegram smoke checklist

После frontend/backend deploy полностью закрыть Mini App и открыть заново.

Проверить:

- loader NEUROMIX отображается сразу;
- Telegram gate не мигает при нормальном входе;
- приложение открывается без пустого экрана;
- bootstrap загружает пользователя и баланс;
- история задач видна;
- фото/видео/референс загружаются;
- тестовая генерация создаёт task;
- pending обновляется до completed/failed;
- публикация предлагает корректный scope;
- feed/profile открывают media;
- превью загружается быстро, оригинал открывается отдельно.

## 12. Backup routines

### `.env`

```bash
install -d -m 700 /root/backups/neuromix
cp -a /root/tanya/banano_kling/.env \
  "/root/backups/neuromix/env-$(date +%Y%m%d-%H%M%S)"
chmod 600 /root/backups/neuromix/env-*
```

### Database

Использовать проектные backup scripts после чтения `docs/migration.md`. Проверить, что backup не пустой и может быть прочитан.

### Frontend

Штатный shared-origin static export обновляется production workflow. Исторический `cdn.sh` backup относится к старому CDN-хосту. Сохранять старые hashed JS/CSS на время WebView-совместимости; откат только по согласованной процедуре.

### Nginx media

`deploy_media_origin.sh` сохраняет предыдущую конфигурацию в root-only backup directory.

## 13. Restart / восстановление

**Обычный релиз — только CI/CD.** Рестарт/rollback — отдельное контролируемое действие после диагностики, без бесконечных циклов. Read-only осмотр:

```bash
docker ps --filter name=banano-kling-bot
docker logs --since 30m --tail 300 banano-kling-bot
docker inspect --format '{{.State.Status}}' banano-kling-bot
sudo nginx -t
```

При согласованном rollback следовать [production-deployment.md](production-deployment.md), не терять DB/медиа и `data/price.json`. Старый `banano-kling.service` не является production runtime, его `systemctl restart` не оживляет текущий Docker bot. Для Nginx reload — сначала `nginx -t`.

## 14. Incident priorities

### P1

- бот и backend полностью недоступны;
- платежи подтверждаются провайдером, но не зачисляются массово;
- data corruption;
- публичный секрет раскрыт;
- Mini App недоступен всем пользователям.

### P2

- отдельный provider не работает;
- media недоступны части сетей;
- frontend deploy не проходит, но старая версия работает;
- отдельный пользовательский flow сломан.

### P3

- некритичная UI-ошибка;
- неверный текст;
- отдельный preview не создан;
- deprecated dependency warning без runtime impact.

## 15. Что не делать во время инцидента

- не удалять `static/uploads`;
- не запускать `rsync --delete` на frontend без rollback plan;
- не открывать `1888/tcp` всему интернету;
- не отключать TLS verification между frontend и backend;
- не публиковать `.env`;
- не очищать npm cache и все backups одновременно;
- не перезапускать сервис бесконечно без чтения логов;
- не считать `401` bootstrap без initData поломкой.

## 16. Связанные документы

- [production-deployment.md](production-deployment.md);
- [miniapp-frontend-deployment.md](miniapp-frontend-deployment.md);
- [troubleshooting.md](troubleshooting.md);
- [environment.md](environment.md);
- [../ops/media/README.md](../ops/media/README.md).
