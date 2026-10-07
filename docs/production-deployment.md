# Production deployment NEUROMIX

Документ описывает схему ветки `tanyapi`, сверенную 2026-10-07. Текущий frontend и media используют один домен; разделы про отдельный `cdn` host ниже обозначены как legacy и не являются текущим release path.

## 1. Целевая инфраструктура

| Роль | Домен | IP | Путь/сервис |
| --- | --- | --- | --- |
| Backend/webhooks | `tanyapi.chillcreative.ru` | `144.76.188.75` | Docker `banano-kling-bot`, compose service `bot`, `/root/tanya/banano_kling` |
| Frontend | `tanyapp.xn--e1aikcel5c5a.online` | `144.76.188.75` | `/var/www/tanyapp.xn--e1aikcel5c5a.online/mini-app` |
| Media | `tanyapp.xn--e1aikcel5c5a.online` | `144.76.188.75` | Nginx `/uploads/` -> backend `static/uploads` |

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

### Legacy separate frontend host (не текущий release path)

- root или sudo без пароля для deploy user;
- Node.js версии, ожидаемой installer script;
- npm;
- Nginx;
- Certbot;
- Git checkout `/opt/banano-kling-src`;
- профиль домена `/etc/banano-miniapp/profiles/cdn.chillcreative.ru.env`.

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

Проверенное публичное разрешение DNS 2026-10-07:

```text
tanyapp.xn--e1aikcel5c5a.online -> 144.76.188.75
```

Один TLS vhost обслуживает `/mini-app/`, проксирует `/mini-app/api/*`, `/uploads/*` и подписанные `/genjutsu/*` на backend. Старые `cdn.chillcreative.ru` и `media.chillcreative.ru` остаются legacy именами в сохранённых ссылках; это не указание менять их DNS или удалять инфраструктуру. Proxy status и TTL нового домена здесь не предполагаются.

Read-only проверка:

```bash
getent ahostsv4 tanyapi.chillcreative.ru
getent ahostsv4 tanyapp.xn--e1aikcel5c5a.online
curl -fsSI https://tanyapp.xn--e1aikcel5c5a.online/mini-app/
```

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
MINI_APP_URL=https://tanyapp.xn--e1aikcel5c5a.online/mini-app/
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

## 9. Legacy frontend remote profile (не текущий release path)

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

## 10. Legacy separate frontend deploy

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

## 11. Что происходит внутри legacy frontend deploy

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

Текущий production release выполняется через CI/CD для точного SHA ветки `tanyapi`. Проверяются контейнер backend и static frontend на новом shared origin. Команды legacy remote deploy выше не запускать для текущего релиза без отдельного плана.

## 12. Post-deploy smoke tests

### Frontend HTML

```bash
curl -fsSI https://tanyapp.xn--e1aikcel5c5a.online/mini-app/
```

### Brand metadata

```bash
curl -fsS https://tanyapp.xn--e1aikcel5c5a.online/mini-app/ \
  | grep -o '<title>[^<]*</title>'
```

Ожидается:

```html
<title>NEUROMIX</title>
```

### Asset

```bash
ASSET=$(curl -fsS https://tanyapp.xn--e1aikcel5c5a.online/mini-app/ \
  | grep -oE '/mini-app/_next/static/[^" ]+\.(js|css)' \
  | head -n1)

echo "$ASSET"
curl -fsSI "https://tanyapp.xn--e1aikcel5c5a.online${ASSET}"
```

### API proxy

```bash
curl -i -X POST \
  https://tanyapp.xn--e1aikcel5c5a.online/mini-app/api/bootstrap \
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
- новые media-превью используют `tanyapp.xn--e1aikcel5c5a.online`; legacy `/uploads/` ссылки нормализуются без массовой перезаписи истории.

## 13. Rollback frontend

### Legacy separate frontend через `cdn.sh`

На frontend host/interactive manager выбрать backup для домена и выполнить rollback. Скрипт восстанавливает backup через `rsync --delete`, затем проверяет Nginx и HTML.

### Ручной аварийный вариант

1. Найти последнюю подтверждённую backup-директорию.
2. Сравнить её содержимое с текущим deployment.
3. Для текущего frontend восстановить в `/var/www/tanyapp.xn--e1aikcel5c5a.online`; legacy backup нельзя автоматически применять к новому vhost.
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

Для текущего shared origin сначала определить, что сломано: release кода, выбранная public-base configuration или Nginx routing. Сохранить `/uploads/` и подписанные `/genjutsu/` маршруты; не откатывать их вместе с legacy vhost без отдельного плана. Любое изменение live Nginx или DNS выполняется только после проверки и согласования; затем нужны syntax check и smoke нового origin.

Старый standalone media installer создавал backup server block и использовал bind mount/Cloudflare. Его rollback относится только к legacy `media.chillcreative.ru`; нельзя автоматически применять его к текущему vhost или отключать proxy во время обычного release.

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
