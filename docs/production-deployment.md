# Production deployment NEUROMIX

Документ описывает production-схему ветки `tanyapi`, сверенную 2026-10-22. Mini App открывается и выкладывается на общем production host по `neuromixbot.com`.

## 1. Целевая инфраструктура

| Роль | Домен | IP | Путь/сервис |
| --- | --- | --- | --- |
| Backend/webhooks | `tanyapi.chillcreative.ru` | `144.76.188.75` | Docker `banano-kling-bot`, compose service `bot`, `/root/tanya/banano_kling` |
| Frontend | `neuromixbot.com` | `144.76.188.75` | `/var/www/neuromixbot.com/mini-app` |
| Media | `neuromixbot.com` | `144.76.188.75` | Nginx `/uploads/` -> backend `static/uploads` |

Production release branch:

```text
tanyapi
```

## 2. Предварительные требования

### Backend host

- Ubuntu/Debian с root-доступом;
- Python runtime и virtualenv проекта;
- Nginx;
- systemd;
- Git-доступ к репозиторию;
- публичный DNS `tanyapi.chillcreative.ru`;
- сертификат для backend-домена;
- локальный aiohttp runtime на `127.0.0.1:1888` либо другом значении из config.

### Mini App frontend

The Mini App uses the production host listed above and is released by
`deploy-production.yml`; no separate frontend host/profile is required.

### Legacy Cloudflare media automation

Текущий shared-origin media path не требует этого legacy workflow. Следующие настройки относятся только к отдельному `media.chillcreative.ru` installer; не создавать токен и не менять DNS для обычного production release. Для отдельно согласованного legacy workflow используются права:

- Zone Read;
- DNS Edit;
- Zone Settings Edit;
- Cache Rules Edit.

Токен хранится только на backend host:

```text
/root/.secrets/cloudflare-media.token
```

Права:

```bash
chmod 600 /root/.secrets/cloudflare-media.token
```

## 3. DNS

### Backend

```text
A  tanyapi  -> 144.76.188.75
```

Режим proxy определяется текущей схемой backend и должен быть согласован с webhook/Nginx. Не менять его во время deploy без отдельной проверки.

### Текущий frontend и media

Проверенное публичное разрешение DNS 2026-10-22:

```text
neuromixbot.com -> 144.76.188.75
```

Один TLS vhost обслуживает `/mini-app/`, проксирует `/mini-app/api/*`, `/uploads/*` и подписанные `/genjutsu/*` на backend. Старые media URL могут встречаться в сохранённых ссылках для обратной совместимости; они не являются адресом запуска Mini App. Proxy status и TTL нового домена здесь не предполагаются.

Read-only проверка:

```bash
getent ahostsv4 tanyapi.chillcreative.ru
getent ahostsv4 neuromixbot.com
curl -fsSI https://neuromixbot.com/mini-app/
```

### Domain migration verified 2026-10-22

`neuromixbot.com` uses Reg.ru DNS and an A record to `144.76.188.75`.
`/var/www/neuromixbot.com` is a symlink to the existing shared static root;
`tanyapp.xn--e1aikcel5c5a.online` redirects launch pages to the new domain while retaining API, hashed assets, uploads
and signed Genjutsu routes for old clients. Redirects preserve the query string.
The active vhost is `/etc/nginx/sites-available/neuromixbot.com.conf`, with its
reviewable copy in `ops/nginx/neuromixbot.com.conf`.

TLS uses the existing Let's Encrypt account, HTTP webroot `/var/www/html`,
certificate `/etc/letsencrypt/live/neuromixbot.com/fullchain.pem` and a private key
stored only on the server. Initial certificate expiry: 2027-01-20. `certbot.timer`
is active; the certificate deploy hook validates and reloads Nginx after renewal.
Verify renewal with:

```bash
certbot renew --cert-name neuromixbot.com --dry-run --run-deploy-hooks --no-random-sleep-on-renew
```

`MINI_APP_URL` remains an environment setting; bot/env.py respects an explicit
value. Production deploy selects `PRODUCTION_MINI_APP_URL` (defaulting to the new
origin) and verifies it before and after cutover. `STATIC_BASE_URL` and
`GENJUTSU_PUBLIC_BASE_URL` must use `https://neuromixbot.com`. Telegram and payment webhook origin remains `https://tanyapi.chillcreative.ru`.
New Genjutsu signed media URLs and provider callbacks use the new shared origin;
existing signed URLs on the previous origin remain supported.

## 4. Backend checkout и административные цены

Обычный release выполняет `.github/workflows/deploy-production-reliable.yml`.
Стандартный fallback `.github/workflows/deploy-production.yml` соблюдает тот же
контракт в обоих путях (SSH и local). Checkout уже должен находиться на `tanyapi`:
другая ветка блокирует deploy вместо автоматического `git switch`.

`data/price.json` на сервере — изменяемые административные данные. Deploy проверяет
JSON-объект и сохраняет резервную копию существующего файла, но никогда не пишет
обратно в этот runtime-путь. `git restore --worktree` обновляет остальные исходники
с исключением `data/price.json`, включая удалённые и переименованные файлы;
`git reset --mixed --no-refresh` затем обновляет только HEAD/index до точного SHA.
Изменение versioned defaults и старый `force_apply_runtime_price` не разрешают
заменять административные тарифы. Сохранение администратором во время Git update
остаётся на месте; содержимое, inode и права существующего файла не меняются
checkout-этапом deploy. Exit trap тоже не восстанавливает устаревший snapshot.

Только для отсутствующего runtime-файла deploy подготавливает и проверяет default
из точного commit, затем атомарно создаёт имя через hard link без замены существующего
пути. Если администратор создал файл между проверкой и этим действием, его файл
сохраняется. Публикация тарифов — отдельное явное действие через существующий
административный механизм.

Некорректный существующий JSON, JSON не-объект, symlink или конфликт структуры
`data`/`data/price.json` в целевом дереве блокирует deploy без замены runtime-данных.
При ошибке source/index update или более позднего этапа резервная копия остаётся
по пути, указанному в логе; автоматически копировать её поверх актуального файла
нельзя. Неудачное обновление исходников может оставить частично обновлённый checkout:
перед повторным release потребуется проверить и согласовать его состояние.

Не выполнять вручную `git reset --hard` на рабочем production checkout: он может
заменить административные цены. Для просмотра текущего состояния достаточно:

```bash
cd /root/tanya/banano_kling
git status --short
git log -1 --oneline
```

## 5. Backend configuration

Рекомендуемые production-значения:

```dotenv
WEBHOOK_HOST=https://tanyapi.chillcreative.ru
WEBHOOK_BIND_HOST=127.0.0.1
WEBHOOK_PORT=1888
MINI_APP_PATH=/mini-app
MINI_APP_URL=https://neuromixbot.com/mini-app/
STATIC_BASE_URL=https://neuromixbot.com
```

Точные обязательные provider/payment значения перечислены в [environment.md](environment.md).

Перед изменением `.env`:

```bash
install -d -m 700 /root/backups/neuromix
cp -a .env "/root/backups/neuromix/env-$(date +%Y%m%d-%H%M%S)"
chmod 600 /root/backups/neuromix/env-*
```

## 6. Backend dependencies и tests

```bash
cd /root/tanya/banano_kling
. venv/bin/activate

pip install -r requirements.txt
python -m pytest
python -m py_compile $(find bot tests scripts -name '*.py')
```

Не перезапускать production service после неуспешных тестов или syntax check.

## 7. Backend restart

```bash
sudo systemctl restart banano-kling.service
sudo systemctl is-active banano-kling.service
sudo systemctl status banano-kling.service --no-pager
```

Локальный health:

```bash
curl -fsS http://127.0.0.1:1888/health
```

Публичный health:

```bash
curl -fsS https://tanyapi.chillcreative.ru/health
```

Логи:

```bash
journalctl -u banano-kling.service -n 200 --no-pager
journalctl -u banano-kling.service -f
```

## 8. Media origin deploy

Production media uses the same public origin as the Mini App:

```text
https://neuromixbot.com/uploads/...
```

Required runtime values:

```dotenv
STATIC_BASE_URL=https://neuromixbot.com
GENJUTSU_PUBLIC_BASE_URL=https://neuromixbot.com
```

`WEBHOOK_HOST` remains the backend/webhook origin `https://tanyapi.chillcreative.ru`; payment and Telegram webhook URLs stay unchanged. New signed Genjutsu provider callback URLs follow GENJUTSU_PUBLIC_BASE_URL; both old and new vhosts retain the signed /genjutsu/ routes.

The active Nginx vhost `/etc/nginx/sites-available/neuromixbot.com.conf` proxies `/uploads/` and signed `/genjutsu/` routes to backend port `1888`. Validate config before reload:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Smoke a real stored media path, including Range support used by video clients:

```bash
curl -sSI https://neuromixbot.com/uploads/feed/<real-file.webp>
curl -sS -o /dev/null -H 'Range: bytes=0-1023' \
  -w '%{http_code}\n' \
  https://neuromixbot.com/uploads/<real-video.mp4>
```

Expected: ordinary media returns `200`; a valid ranged video request returns `206`. Old `tanyapi.chillcreative.ru/uploads/...` links stay readable only for backward compatibility and must not be generated for new media.

The standalone `media.chillcreative.ru` installer under `ops/media/` is legacy infrastructure and is not the current production deploy path.

## 9. Mini App frontend deploy

The Mini App is served from `https://neuromixbot.com/mini-app/` on the production
backend host. The `deploy-production.yml` workflow runs
`scripts/deploy_miniapp_local.sh` for the exact release SHA and verifies
`/mini-app/revision.txt`. Do not deploy the Mini App through a separate frontend host.

Read-only status checks:

```bash
curl -fsSI https://neuromixbot.com/mini-app/
curl -fsS https://neuromixbot.com/mini-app/revision.txt
```

## 10. Mini App publisher behavior

`scripts/deploy_miniapp_local.sh` verifies the requested commit, runs frontend
install/lint/build on the production host, backs up the active static root,
publishes the export without deleting older hashed assets, writes
`revision.txt`, and checks the public HTML/assets against the exact release
SHA. The production workflow also verifies backend health and the Mini App
revision. Telegram WebView smoke remains a separate client-level check.

## 11. Post-deploy smoke tests

### Frontend HTML

```bash
curl -fsSI https://neuromixbot.com/mini-app/
```

### Brand metadata

```bash
curl -fsS https://neuromixbot.com/mini-app/ \
  | grep -o '<title>[^<]*</title>'
```

Ожидается:

```html
<title>NEUROMIX</title>
```

### Asset

```bash
ASSET=$(curl -fsS https://neuromixbot.com/mini-app/ \
  | grep -oE '/mini-app/_next/static/[^" ]+\.(js|css)' \
  | head -n1)

echo "$ASSET"
curl -fsSI "https://neuromixbot.com${ASSET}"
```

### API proxy

```bash
curl -i -X POST \
  https://neuromixbot.com/mini-app/api/bootstrap \
  -H 'Content-Type: application/json' \
  --data '{}'
```

Ожидаемый ответ без Telegram auth: `400`, `401` или `403` с JSON. `502`, `504` или HTML-ошибка означают проблему proxy/backend.

### Telegram smoke

Полностью закрыть Mini App, открыть заново и проверить:

- сначала отображается NEUROMIX loader;
- ложный Telegram gate не мигает;
- bootstrap проходит;
- история загружается;
- upload работает;
- создаётся тестовая задача;
- готовый результат появляется в карточке;
- публикация и profile/feed работают;
- новые media-превью используют `neuromixbot.com`; legacy `/uploads/` ссылки нормализуются без массовой перезаписи истории.

## 12. Rollback frontend

Frontend backups are retained under
`/var/backups/banano-miniapp/neuromixbot.com/`. Any restore must be an
operator-approved recovery against the matching `neuromixbot.com` static root;
never restore a separate-host backup or remove old assets as part of a normal
release. Verify `/mini-app/revision.txt`, HTML, and assets after recovery.

## 13. Rollback backend

```bash
cd /root/tanya/banano_kling

git log --oneline -n 10
git checkout <verified-commit>

sudo systemctl restart banano-kling.service
curl -fsS http://127.0.0.1:1888/health
```

Лучше откатывать ветку через revert/исправляющий commit, а detached checkout использовать только как краткосрочный аварийный шаг.

## 14. Rollback media

Для текущего shared origin сначала определить, что сломано: release кода, выбранная public-base configuration или Nginx routing. Сохранить `/uploads/` и подписанные `/genjutsu/` маршруты; не откатывать их вместе с legacy vhost без отдельного плана. Любое изменение live Nginx или DNS выполняется только после проверки и согласования; затем нужны syntax check и smoke нового origin.

Старый standalone media installer создавал backup server block и использовал bind mount/Cloudflare. Его rollback относится только к legacy `media.chillcreative.ru`; нельзя автоматически применять его к текущему vhost или отключать proxy во время обычного release.

## 15. Release checklist

Перед deploy:

- [ ] ветка `tanyapi`;
- [ ] clean working tree;
- [ ] актуальный `origin/tanyapi`;
- [ ] backup `.env`;
- [ ] backend tests/syntax check;
- [ ] frontend lint/test/build либо installer gate;
- [ ] достаточно RAM и disk на frontend host;
- [ ] SSH работает без интерактивного пароля.

После deploy:

- [ ] backend local health;
- [ ] backend public health;
- [ ] frontend health;
- [ ] Mini App HTML 200;
- [ ] `<title>NEUROMIX</title>`;
- [ ] current JS/CSS assets 200;
- [ ] bootstrap без auth возвращает auth error, не proxy error;
- [ ] media real file 200;
- [ ] повторный media request даёт ожидаемый cache status;
- [ ] Telegram smoke пройден;
- [ ] старые chunks не удалены преждевременно.
