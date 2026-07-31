# Media delivery через Cloudflare Free + существующий `static/uploads`

Цель: не покупать отдельный CDN или объектное хранилище. Backend уже сохраняет публичные результаты в `static/uploads`, формирует URL `/uploads/...` и создаёт thumbnails для ленты. Нужно оставить файлы на месте, отдать их напрямую через Nginx и поставить перед Nginx Cloudflare Free.

## Фактическая схема

```text
Backend / AI provider
        ↓
/root/tanya/banano_kling/static/uploads
        ├── feed/<original>
        └── feed/thumbs/<preview>.webp
        ↓
Nginx на backend 144.76.188.75
        ↓
media.chillcreative.ru через Cloudflare Free
        ↓
Mini App на cdn.chillcreative.ru
```

`cdn.chillcreative.ru` остаётся frontend-доменом на сервере `91.200.84.187`. Медиа-домен направляется на backend `144.76.188.75`, потому что каталог `static/uploads` находится там.

## 1. DNS

В Cloudflare создать запись:

```text
Type: A
Name: media
IPv4: 144.76.188.75
Proxy status: Proxied (оранжевое облако)
TTL: Auto
```

AAAA добавлять только при полностью рабочем IPv6 на backend. Если IPv6 не настроен или не проверен, AAAA не создавать.

## 2. Файлы не переносить

Используется существующий каталог:

```text
/root/tanya/banano_kling/static/uploads
```

Если production checkout находится в другом месте, поменять только путь `alias` в `ops/media/nginx-media.conf`. Структуру URL и содержимое базы менять не требуется.

Проверка:

```bash
cd /root/tanya/banano_kling
find static/uploads -maxdepth 3 -type f | head
```

## 3. Nginx

Установить server block на backend:

```bash
cp ops/media/nginx-media.conf /etc/nginx/sites-available/media.chillcreative.ru.conf
ln -sfn /etc/nginx/sites-available/media.chillcreative.ru.conf \
  /etc/nginx/sites-enabled/media.chillcreative.ru.conf
nginx -t
systemctl reload nginx
```

Конфиг сопоставляет:

```text
https://media.chillcreative.ru/uploads/<path>
→ /root/tanya/banano_kling/static/uploads/<path>
```

Файл передаёт Nginx через `sendfile`; Python больше не участвует в передаче тела запроса на media-домене.

## 4. STATIC_BASE_URL

Для новых URL:

```dotenv
STATIC_BASE_URL=https://media.chillcreative.ru
```

После изменения:

```bash
systemctl restart banano-kling.service
systemctl is-active banano-kling.service
```

Backend уже строит ссылки через `STATIC_BASE_URL`, поэтому новые публикации будут иметь вид:

```text
https://media.chillcreative.ru/uploads/feed/<file>
https://media.chillcreative.ru/uploads/feed/thumbs/<file>.webp
```

Старые абсолютные URL в базе автоматически не меняются. Их можно оставить рабочими на `tanyapi` или отдельно переписать домен после проверки media-домена.

## 5. WebP-превью

При публикации изображения backend создаёт WebP-preview в:

```text
static/uploads/feed/thumbs/<source-stem>.webp
```

Параметры:

```text
максимальная сторона: 768 px
предпочтительный размер: 50–200 КБ
жёсткий верхний предел: 200 КБ
формат: WebP
```

API ленты уже предпочитает thumbnail оригиналу. Legacy `.jpg` thumbnails продолжают читаться как fallback, новые создаются в WebP.

Для backfill уже лежащих файлов можно использовать:

```bash
python scripts/build_media_previews.py \
  --input static/uploads/feed \
  --output static/uploads/feed/thumbs \
  --max-edge 768 \
  --min-kb 50 \
  --max-kb 200
```

## 6. Cache-Control

Nginx отвечает для `/uploads/*`:

```text
Cache-Control: public, max-age=31536000, s-maxage=31536000, immutable
Access-Control-Allow-Origin: *
Cross-Origin-Resource-Policy: cross-origin
```

Важно: immutable безопасен, потому что имена сохранённых feed-файлов уникальны. Нельзя заменять содержимое файла, сохраняя тот же URL.

## 7. Cloudflare Cache Rule

Cloudflare Dashboard → Caching → Cache Rules → Create rule.

Expression:

```text
(http.host eq "media.chillcreative.ru" and
 starts_with(http.request.uri.path, "/uploads/"))
```

Actions:

```text
Cache eligibility: Eligible for cache
Edge TTL: Respect origin TTL
Browser TTL: Respect origin TTL
```

Не применять `Cache Everything` к `tanyapi`, webhook, API или frontend HTML.

Первый запрос из edge-локации обычно даст `MISS`; повторный должен дать `HIT` и заголовок `Age`.

## 8. Временно отключить HTTP/3

На время проверки проблемных VPN:

```text
Cloudflare Dashboard
→ Speed
→ Optimization
→ Protocol Optimization
→ HTTP/3 (with QUIC)
→ Off
```

HTTP/2 останется включённым. Если зависания исчезнут, проблема находится в QUIC/UDP-маршруте конкретных VPN.

## 9. Проверка IPv4, IPv6 и кеша

Использовать реальный файл:

```bash
bash scripts/check_media_delivery.sh \
  https://media.chillcreative.ru/uploads/feed/thumbs/<real-file>.webp
```

Ожидаемо после второго запроса:

```text
HTTP/2 200
server: cloudflare
cf-cache-status: HIT
age: > 0
content-type: image/webp
cache-control: public, max-age=31536000, s-maxage=31536000, immutable
```

Интерпретация:

- IPv4 работает, IPv6 нет — убрать/исправить AAAA.
- HTTP/2 работает, после отключения HTTP/3 проблемный VPN ожил — конфликт QUIC/UDP.
- постоянный `MISS` — проверить Cache Rule, query string и origin headers.
- `BYPASS` — проверить cookies, auth и private/no-store.
- `DYNAMIC` — правило Cloudflare не совпало.
- есть `301/302` на другой домен — файл фактически выдаётся не через media origin.

## 10. Smoke-проверка после деплоя

```bash
nginx -t
systemctl reload nginx
curl -fsSI --http2 https://media.chillcreative.ru/healthz
curl -fsSI --http2 https://media.chillcreative.ru/uploads/feed/<real-file>
bash scripts/check_media_delivery.sh \
  https://media.chillcreative.ru/uploads/feed/thumbs/<real-file>.webp
```

Проверить обычное подключение и минимум две проблемные VPN-локации. Сохранять `CF-Ray`: он показывает, через какой edge Cloudflare прошёл запрос.
