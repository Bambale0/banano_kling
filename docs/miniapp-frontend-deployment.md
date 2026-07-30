# Mini App frontend deployment runbook

## 1. Текущая production-схема

Mini App развёрнут отдельно от Python runtime:

| Компонент | Адрес / размещение |
| --- | --- |
| Публичный frontend | `https://tanyapp.chillcreative.ru/mini-app/` |
| Frontend host | `2.27.160.11`, static files в `/srv/banano-miniapp` |
| Static container | `banano-miniapp`, образ `nginx:alpine`, сеть `artflow_default` |
| Shared ingress | контейнер `artflow-nginx-1` |
| Ingress config source | `/root/mkdir/lena_bot/artflow/nginx.conf` |
| Публичный backend | `https://tanyapi.chillcreative.ru` |
| Backend runtime | `banano-kling.service`, aiohttp на `127.0.0.1:1888` |

Frontend host отдаёт static export и проксирует API/upload-запросы на backend host. `WEBHOOK_HOST` при frontend-деплое не меняется.

Не сохраняйте SSH-пароли, токены и содержимое `.env` в репозитории или shell history. Для регулярного деплоя используйте отдельный SSH-ключ и ограниченный доступ.

## 2. Маршрутизация и cache policy

Ingress на frontend host должен обеспечивать:

- `/` → redirect на `/mini-app/`
- `/mini-app/` → static container `banano-miniapp`
- `/mini-app/api/` → `https://tanyapi.chillcreative.ru`
- `/api/v1/` → `https://tanyapi.chillcreative.ru`
- `/uploads/` → `https://tanyapi.chillcreative.ru`
- `client_max_body_size 60M`
- SNI и `Host` upstream-запроса равны `tanyapi.chillcreative.ru`
- `X-Forwarded-Host` сохраняет frontend domain

Cache policy:

- `/_next/static/`: `public, max-age=31536000, immutable`
- `telegram-web-app.js`: cache до одного часа
- HTML: `no-cache, no-store, must-revalidate`
- gzip включён для CSS, JavaScript, JSON и SVG

### Media gateway результатов

Карточки не зависят напрямую от временных URL AI-провайдера. API-клиент заменяет такие адреса на same-origin маршрут `/mini-app/api/media/{task_id}/{index}`. Backend проверяет Telegram-пользователя и принадлежность задачи, разрешает только известные provider hosts, ограничивает скачивание по времени/размеру и кеширует результат в `static/uploads/miniapp-media-cache`. Это защищает ленту от чёрных карточек в сетях, где CDN провайдера недоступен.

## 3. Сборка и pre-deploy gate

Из корня репозитория:

```bash
cd frontend/miniapp-v0
npm ci
npm audit --omit=dev --audit-level=moderate
npm run lint
npm run build
test -f out/index.html
```

`npm run build` должен завершиться успешно и создать `frontend/miniapp-v0/out`. Не переключайте production URL при ошибке любого шага.

## 4. Копирование frontend

Сначала убедитесь, что целевой каталог именно `/srv/banano-miniapp`. Параметр `--delete` удаляет на сервере файлы, которых нет в новой сборке, поэтому его нельзя применять к непроверенному пути.

```bash
rsync -az --delete \
  frontend/miniapp-v0/out/ \
  root@2.27.160.11:/srv/banano-miniapp/
```

Static container использует read-only bind mount, поэтому при обычном обновлении файлов перезапуск контейнера не требуется.

Первичное создание контейнера:

```bash
docker run -d \
  --name banano-miniapp \
  --restart unless-stopped \
  --network artflow_default \
  -v /srv/banano-miniapp:/usr/share/nginx/html/mini-app:ro \
  nginx:alpine
```

Перед изменением shared ingress создайте копию его config, затем обязательно выполните:

```bash
docker exec artflow-nginx-1 nginx -t
docker exec artflow-nginx-1 nginx -s reload
```

## 5. TLS

Сертификат хранится на frontend host:

```text
/etc/letsencrypt/live/tanyapp.chillcreative.ru/fullchain.pem
/etc/letsencrypt/live/tanyapp.chillcreative.ru/privkey.pem
```

После выпуска или обновления сертификата hook
`/etc/letsencrypt/renewal-hooks/deploy/reload-banano-nginx.sh` проверяет config и reload-ит `artflow-nginx-1`.

Проверка автоматического renewal:

```bash
certbot renew --dry-run \
  --cert-name tanyapp.chillcreative.ru \
  --no-random-sleep-on-renew
```

## 6. Проверки до переключения production

До изменения `MINI_APP_URL` должны пройти все проверки:

```bash
curl -fsSI http://tanyapp.chillcreative.ru/mini-app/
curl -fsSI https://tanyapp.chillcreative.ru/mini-app/
curl --http2 -fsSI https://tanyapp.chillcreative.ru/mini-app/
openssl s_client -connect tanyapp.chillcreative.ru:443 \
  -servername tanyapp.chillcreative.ru -verify_return_error </dev/null
```

Для asset-проверки используйте реальный hashed URL из `out/index.html`, а не только каталог `/_next/static/`.
Например, найдите первый `/_next/static/` URL в HTML и проверьте, что он отвечает `200` и содержит `Cache-Control: public, max-age=31536000, immutable`.

API smoke без Telegram `initData`:

```bash
curl -i -X POST \
  https://tanyapp.chillcreative.ru/mini-app/api/bootstrap \
  -H 'Content-Type: application/json' \
  --data '{}'
```

Ожидаемый результат — `401` с JSON-ошибкой авторизации. Это подтверждает proxy и auth boundary, но не заменяет проверку внутри Telegram.

## 7. Production cutover

Только после успешного pre-deploy gate на backend host:

1. Сделать резервную копию `.env` с правами только для root.
2. Установить:

   ```dotenv
   MINI_APP_URL=https://tanyapp.chillcreative.ru/mini-app/
   ```

3. Перезапустить runtime и проверить его:

   ```bash
   systemctl restart banano-kling.service
   systemctl is-active banano-kling.service
   curl -fsS http://127.0.0.1:1888/health
   journalctl -u banano-kling.service -n 100 --no-pager
   ```

4. Открыть Mini App из Telegram и проверить bootstrap, upload, feed, trends, generation и task detail.

## 8. Post-deploy verification

```bash
curl -fsSI https://tanyapp.chillcreative.ru/mini-app/
curl -fsSI https://tanyapi.chillcreative.ru/health
ssh root@2.27.160.11 \
  'docker ps --filter name=banano-miniapp --filter name=artflow-nginx-1 && docker exec artflow-nginx-1 nginx -t'
```

Проверить в браузере:

- document загружается по HTTP/2 и без redirect loop
- hashed assets имеют `immutable`
- HTML не кешируется надолго
- CSS/JS отдаются с gzip
- API идёт через `tanyapp.chillcreative.ru`, без mixed content и CORS-ошибок
- готовый результат появляется в открытой карточке не позднее следующего 5-секундного sync tick
- публикация открывает один выбор `Лента и профиль` / `Только профиль`, без второго окна
- повторное сохранение обновляет ту же публикацию, а не создаёт дубль
- после публикации работают открытие и копирование ссылки

### Синхронизация и публикация

При возврате приложения в foreground и каждые 5 секунд видимая Mini App повторяет bootstrap. Свежая задача одновременно обновляет историю, выбранную задачу и открытую детальную карточку. Поэтому результат, уже отправленный ботом в чат, не должен оставаться в интерфейсе в статусе `В обработке`.

Публикация соответствует сценарию бота: одна кнопка открывает выбор scope, затем настройки prompt/референсов/blur. Scope `feed` означает общую ленту и профиль, `profile` — только профиль. Backend делает idempotent update исходной генерации и возвращает `feed_item.publication_link`. У опубликованной работы доступно отдельное удаление, чтобы настройка не снимала публикацию случайно.

## 9. Быстрый rollback

Backend всё ещё умеет отдавать локальный static export. Для отката:

1. На backend host вернуть:

   ```dotenv
   MINI_APP_URL=https://tanyapi.chillcreative.ru/mini-app/
   ```

2. Перезапустить и проверить сервис:

   ```bash
   systemctl restart banano-kling.service
   systemctl is-active banano-kling.service
   curl -fsS http://127.0.0.1:1888/health
   ```

3. Проверить Mini App из Telegram.

Если проблема именно в ingress frontend host, восстановить последнюю проверенную копию вида `nginx.conf.before-banano-*`, выполнить `nginx -t` внутри `artflow-nginx-1` и только затем reload. Не выбирайте backup только по имени: сначала сравните его с текущим config.

## 10. Если Mini App долго грузится

1. Сравнить DNS и адрес сервера:

   ```bash
   getent ahostsv4 tanyapp.chillcreative.ru
   ```

2. Замерить DNS/connect/TLS/TTFB/total:

   ```bash
   curl -o /dev/null -sS \
     -w 'dns=%{time_namelookup} connect=%{time_connect} tls=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total}\n' \
     https://tanyapp.chillcreative.ru/mini-app/
   ```

3. Проверить HTTP/2, gzip и cache headers реального JS asset.
4. Разделить проблему document/static и API: медленный `bootstrap` исследовать на backend, медленный JS/CSS — на frontend ingress.
5. Проверить CPU/memory, restart count и логи обоих контейнеров; на backend — `journalctl` и `NRestarts` сервиса.

Первый cold load зависит от сети и географии пользователя. Это не повод отключать cache: HTML должен оставаться no-cache, а hashed assets — immutable.
