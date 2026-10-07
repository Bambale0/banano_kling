# Production deployment NEUROMIX

Документ описывает актуальную схему ветки `tanyapi`.

## 1. Целевая инфраструктура

| Роль | Домен | IP | Путь/сервис |
| --- | --- | --- | --- |
| Backend | `tanyapi.chillcreative.ru` | `144.76.188.75` | `/root/tanya/banano_kling`, `banano-kling.service` |
| Frontend | `cdn.chillcreative.ru` | `91.200.84.187` | `/var/www/cdn.chillcreative.ru` |
| Media | `tanyapp.xn--e1aikcel5c5a.online` | `144.76.188.75` | Nginx `/uploads/` -> backend `static/uploads` |

Обязательная ветка на обоих checkout:

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

### Frontend host

- root или sudo без пароля для deploy user;
- Node.js версии, ожидаемой installer script;
- npm;
- Nginx;
- Certbot;
- Git checkout `/opt/banano-kling-src`;
- профиль домена `/etc/banano-miniapp/profiles/cdn.chillcreative.ru.env`.

### Cloudflare

Для автоматизации media рекомендуется ограниченный API token:

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

### Frontend

```text
A  cdn      -> 91.200.84.187
```

### Media

```text
A  media    -> 144.76.188.75
Proxy status: Proxied
TTL: Auto
```

Проверка:

```bash
getent ahostsv4 tanyapi.chillcreative.ru
getent ahostsv4 cdn.chillcreative.ru
getent ahostsv4 media.chillcreative.ru
```

## 4. Подготовка backend checkout

```bash
cd /root/tanya/banano_kling

git fetch --prune origin tanyapi
git switch tanyapi
git status --short
git reset --hard origin/tanyapi

git log -1 --oneline
```

Перед `reset --hard` убедиться, что локальные изменения не нужны.

## 5. Backend configuration

Рекомендуемые production-значения:

```dotenv
WEBHOOK_HOST=https://tanyapi.chillcreative.ru
WEBHOOK_BIND_HOST=127.0.0.1
WEBHOOK_PORT=1888
MINI_APP_PATH=/mini-app
MINI_APP_URL=https://cdn.chillcreative.ru/mini-app/
STATIC_BASE_URL=https://tanyapp.xn--e1aikcel5c5a.online
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
https://tanyapp.xn--e1aikcel5c5a.online/uploads/...
```

Required runtime values:

```dotenv
STATIC_BASE_URL=https://tanyapp.xn--e1aikcel5c5a.online
GENJUTSU_PUBLIC_BASE_URL=https://tanyapp.xn--e1aikcel5c5a.online
```

`WEBHOOK_HOST` remains the backend/webhook origin `https://tanyapi.chillcreative.ru`; do not replace payment/provider webhook URLs as part of the media-origin change.

The active Nginx vhost `/etc/nginx/sites-available/tanyapp.xn--e1aikcel5c5a.online.conf` proxies `/uploads/` and signed `/genjutsu/` routes to backend port `1888`. Validate config before reload:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Smoke a real stored media path, including Range support used by video clients:

```bash
curl -sSI https://tanyapp.xn--e1aikcel5c5a.online/uploads/feed/<real-file.webp>
curl -sS -o /dev/null -H 'Range: bytes=0-1023' \
  -w '%{http_code}\n' \
  https://tanyapp.xn--e1aikcel5c5a.online/uploads/<real-video.mp4>
```

Expected: ordinary media returns `200`; a valid ranged video request returns `206`. Old `tanyapi.chillcreative.ru/uploads/...` links stay readable only for backward compatibility and must not be generated for new media.

The standalone `media.chillcreative.ru` installer under `ops/media/` is legacy infrastructure and is not the current production deploy path.

## 9. Frontend remote profile

Профиль `tanyafrontend` хранится на операторском/backend host в root-only каталоге `cdn.sh`.

Создание/обновление профиля выполняется интерактивным режимом `cdn.sh`. Ожидаемые значения:

```text
REMOTE_SSH_HOST=root@91.200.84.187
REMOTE_SOURCE_DIR=/opt/banano-kling-src
REMOTE_DOMAIN=cdn.chillcreative.ru
REMOTE_BRANCH=tanyapi
REMOTE_USE_SUDO=0
```

Проверить SSH:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 root@91.200.84.187 'echo SSH_OK'
```

## 10. Frontend deploy

На backend/operator host:

```bash
cd /root/tanya/banano_kling

git fetch --prune origin tanyapi
git switch tanyapi
git reset --hard origin/tanyapi

git log -1 --oneline
sudo bash cdn.sh --remote-deploy tanyafrontend
```

Не запускать `--remote-status` в той же цепочке до завершения deploy.

После успешного deploy:

```bash
sudo bash cdn.sh --remote-status tanyafrontend
```

Ожидаемые status fields:

```text
branch=tanyapi
profile=ok
nginx=active
miniapp_http=200
health={..."ok":true...}
```

## 11. Что происходит внутри frontend deploy

1. SSH на `91.200.84.187`;
2. проверка чистого checkout;
3. `fetch/switch/reset` до `origin/tanyapi`;
4. запуск domain installer;
5. `npm ci`;
6. lint/build и проверка `out/index.html` согласно installer;
7. backup текущей версии;
8. публикация static export;
9. `nginx -t` и reload при необходимости;
10. frontend health и HTML smoke.

Frontend static assets предыдущей сборки не должны удаляться сразу. Telegram WebView может держать старый HTML и запрашивать старые hashed chunks.

## 12. Post-deploy smoke tests

### Frontend HTML

```bash
curl -fsSI https://cdn.chillcreative.ru/mini-app/
```

### Brand metadata

```bash
curl -fsS https://cdn.chillcreative.ru/mini-app/ \
  | grep -o '<title>[^<]*</title>'
```

Ожидается:

```html
<title>NEUROMIX</title>
```

### Asset

```bash
ASSET=$(curl -fsS https://cdn.chillcreative.ru/mini-app/ \
  | grep -oE '/mini-app/_next/static/[^" ]+\.(js|css)' \
  | head -n1)

echo "$ASSET"
curl -fsSI "https://cdn.chillcreative.ru${ASSET}"
```

### API proxy

```bash
curl -i -X POST \
  https://cdn.chillcreative.ru/mini-app/api/bootstrap \
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
- media-превью загружаются через `media.chillcreative.ru`.

## 13. Rollback frontend

### Через `cdn.sh`

На frontend host/interactive manager выбрать backup для домена и выполнить rollback. Скрипт восстанавливает backup через `rsync --delete`, затем проверяет Nginx и HTML.

### Ручной аварийный вариант

1. Найти последнюю подтверждённую backup-директорию.
2. Сравнить её содержимое с текущим deployment.
3. Восстановить в `/var/www/cdn.chillcreative.ru`.
4. Проверить права.
5. Выполнить `nginx -t`.
6. Проверить HTML и реальный asset.

Не удалять backup до успешного Telegram smoke.

## 14. Rollback backend

```bash
cd /root/tanya/banano_kling

git log --oneline -n 10
git checkout <verified-commit>

sudo systemctl restart banano-kling.service
curl -fsS http://127.0.0.1:1888/health
```

Лучше откатывать ветку через revert/исправляющий commit, а detached checkout использовать только как краткосрочный аварийный шаг.

## 15. Rollback media

Скрипт media создаёт backup Nginx-конфигурации. Для ручного отката:

- восстановить предыдущий server block;
- `nginx -t`;
- reload Nginx;
- проверить bind mount;
- при необходимости временно выключить Cloudflare proxy для origin-диагностики;
- после восстановления вернуть proxy и проверить cache headers.

## 16. Release checklist

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
