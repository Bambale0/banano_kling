# Media delivery через Cloudflare Free + существующий `static/uploads`

Backend уже сохраняет результаты в `static/uploads` и формирует URL `/uploads/...`. Отдельное хранилище не требуется. Production-схема:

```text
/root/tanya/banano_kling/static/uploads
        ↓ bind mount без копирования файлов
/var/www/media.chillcreative.ru/uploads
        ↓ Nginx static files
media.chillcreative.ru
        ↓ Cloudflare Free
Mini App на cdn.chillcreative.ru
```

- backend/origin: `144.76.188.75`;
- frontend Mini App: `cdn.chillcreative.ru` на `91.200.84.187`;
- media domain: `media.chillcreative.ru` → backend `144.76.188.75`.

## Рекомендуемый запуск

Скрипт работает только из ветки `tanyapi` и прекращает выполнение на другой ветке.

```bash
cd /root/tanya/banano_kling
git switch tanyapi
git pull --ff-only origin tanyapi
chmod +x scripts/deploy_media_origin.sh
```

### Вариант A: полный автоматический запуск с Cloudflare API

Создать ограниченный Cloudflare API Token для зоны `chillcreative.ru`:

- Zone → Zone → Read;
- Zone → DNS → Edit;
- Zone → Zone Settings → Edit;
- Zone → Cache Rules → Edit.

Сохранить токен без перевода строки:

```bash
install -d -m 700 /root/.secrets
install -m 600 /dev/null /root/.secrets/cloudflare-media.token
nano /root/.secrets/cloudflare-media.token
```

Запустить:

```bash
LETSENCRYPT_EMAIL='your-email@example.com' \
ORIGIN_IPV4='144.76.188.75' \
bash scripts/deploy_media_origin.sh
```

При наличии токена скрипт:

1. создаёт или обновляет `A media.chillcreative.ru → 144.76.188.75`;
2. включает Cloudflare proxy (`proxied=true`, оранжевое облако);
3. выключает HTTP/3 на время VPN-диагностики;
4. создаёт или обновляет Cache Rule только для `/uploads/feed/*`;
5. выпускает сертификат Let’s Encrypt через DNS-01;
6. устанавливает Nginx-конфигурацию;
7. добавляет автопродление сертификата и reload Nginx;
8. устанавливает `STATIC_BASE_URL=https://media.chillcreative.ru` в `.env`;
9. перезапускает `banano-kling.service`;
10. создаёт WebP-превью для существующих изображений ленты;
11. проверяет Cloudflare proxy, отсутствие HTTP/3 и `CF-Cache-Status: HIT`.

### Вариант B: без Cloudflare API Token

До запуска вручную настроить Cloudflare:

```text
Type: A
Name: media
Content: 144.76.188.75
Proxy status: Proxied
TTL: Auto
```

Cache Rule expression:

```text
(http.host eq "media.chillcreative.ru" and
 starts_with(http.request.uri.path, "/uploads/feed/"))
```

Действия:

```text
Cache eligibility: Eligible for cache
Edge TTL: Respect origin
Browser TTL: Respect origin
```

Также:

```text
SSL/TLS mode: Full (strict)
HTTP/3: Off на время диагностики VPN
```

После этого:

```bash
LETSENCRYPT_EMAIL='your-email@example.com' \
bash scripts/deploy_media_origin.sh
```

Без токена Certbot использует HTTP-01. До первого выпуска сертификата Cloudflare `Always Use HTTPS` не должен перенаправлять ACME challenge на HTTPS. После выпуска его можно включить обратно.

## Почему используется bind mount

Проект находится внутри `/root`, а Nginx worker обычно не может проходить через каталог `/root`. Скрипт не ослабляет права `/root` и не копирует медиа. Он монтирует ту же папку:

```text
/root/tanya/banano_kling/static/uploads
→ /var/www/media.chillcreative.ru/uploads
```

Bind mount добавляется в `/etc/fstab` и сохраняется после перезагрузки.

## Политика кеша

### Публичная лента

Для `/uploads/feed/*`:

```text
Cache-Control: public, max-age=31536000, s-maxage=31536000, immutable
```

В эту папку попадают долговременные файлы ленты и `feed/thumbs/*.webp`.

### Остальные uploads

Для `/uploads/*`, кроме `feed`:

```text
Cache-Control: no-store
```

Это важно для пользовательских reference-файлов и временных загрузок. Cloudflare не должен хранить их год.

## Проверки скрипта

Скрипт завершается ошибкой, если:

- запущен не из ветки `tanyapi`;
- не найден проект или `static/uploads`;
- Nginx config не проходит `nginx -t`;
- сертификат не выпущен;
- домен не проксируется Cloudflare;
- HTTP/3 всё ещё рекламируется через `Alt-Svc`;
- повторные запросы не дают `CF-Cache-Status: HIT`;
- backend не поднялся после изменения `.env`.

Дополнительная диагностика на реальном файле:

```bash
bash scripts/check_media_delivery.sh \
  https://media.chillcreative.ru/uploads/feed/<real-file.webp>
```

## Повторный запуск

Скрипт идемпотентный:

- существующий сертификат не перевыпускается, если действителен больше 30 дней;
- DNS record обновляется вместо создания дубля;
- Cache Rule обновляется по фиксированному description;
- bind mount и `/etc/fstab` не дублируются;
- Nginx config проверяется перед reload.

Перед изменением Nginx создаётся резервная копия:

```text
/root/nginx-backups/media.chillcreative.ru-YYYYMMDD-HHMMSS/
```

При ошибке до активации HTTPS предыдущий Nginx server block восстанавливается автоматически.

## Переменные запуска

```text
DOMAIN                 media.chillcreative.ru
ZONE_NAME              chillcreative.ru
ORIGIN_IPV4             144.76.188.75
PROJECT_DIR             /root/tanya/banano_kling
UPLOADS_DIR             <PROJECT_DIR>/static/uploads
APP_SERVICE             banano-kling.service
CF_API_TOKEN_FILE       /root/.secrets/cloudflare-media.token
BACKFILL_WEBP           1
RUN_RENEWAL_DRY_RUN     1
```

Для пропуска долгого backfill или renewal dry-run:

```bash
BACKFILL_WEBP=0 RUN_RENEWAL_DRY_RUN=0 \
bash scripts/deploy_media_origin.sh
```
