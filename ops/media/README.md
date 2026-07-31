# Media delivery через Cloudflare Free + Nginx

Цель: не покупать отдельный CDN/объектное хранилище, а отдавать публичные изображения через отдельный домен `media.chillcreative.ru`, Cloudflare Free и Nginx.

## Архитектура

```text
AI provider / backend upload
        ↓
/srv/banano-media/public/originals
        ↓ build_media_previews.py
/srv/banano-media/public/previews/*.webp
        ↓
Nginx на origin
        ↓
Cloudflare Free (orange cloud)
        ↓
Mini App / Telegram WebView
```

Для ленты используется `previews/*.webp` размером примерно 50–200 КБ. Оригинал загружается только при открытии карточки.

## 1. DNS и Cloudflare Proxy

В Cloudflare DNS создать запись:

```text
Type: A
Name: media
Content: <IPv4 origin-сервера>
Proxy status: Proxied
TTL: Auto
```

AAAA добавлять только если origin действительно принимает HTTPS по IPv6. Полурабочий AAAA хуже полного отсутствия IPv6.

Проверка:

```bash
dig +short A media.chillcreative.ru
dig +short AAAA media.chillcreative.ru
```

При включённом proxy публичные A/AAAA должны указывать на адреса Cloudflare, а не напрямую на origin.

## 2. Каталоги и права

```bash
install -d -m 0755 /srv/banano-media/public/originals
install -d -m 0755 /srv/banano-media/public/previews
chown -R www-data:www-data /srv/banano-media
```

Backend должен записывать оригиналы атомарно: сначала временный файл, затем `rename` в итоговое имя. URL должен быть immutable, например:

```text
https://media.chillcreative.ru/previews/ab/cd/<sha256>.webp
https://media.chillcreative.ru/originals/ab/cd/<sha256>.jpg
```

При изменении содержимого меняется имя файла. Нельзя заменять байты по старому immutable URL.

## 3. Nginx

Установить `ops/media/nginx-media.conf` как отдельный server block, проверить и перезагрузить:

```bash
cp ops/media/nginx-media.conf /etc/nginx/sites-available/media.chillcreative.ru.conf
ln -sfn /etc/nginx/sites-available/media.chillcreative.ru.conf /etc/nginx/sites-enabled/media.chillcreative.ru.conf
nginx -t
systemctl reload nginx
```

Конфиг отдаёт файлы непосредственно через Nginx, включает `sendfile`, range requests и долгий immutable cache. Python не участвует в передаче тела файла.

## 4. Генерация WebP-превью

Пример ручного запуска:

```bash
python scripts/build_media_previews.py \
  --input /srv/banano-media/public/originals \
  --output /srv/banano-media/public/previews \
  --max-edge 768 \
  --min-kb 50 \
  --max-kb 200
```

Скрипт:

- сохраняет структуру каталогов;
- применяет EXIF rotation;
- уменьшает изображение до `max-edge` без апскейла;
- подбирает WebP quality бинарным поиском;
- пропускает актуальные превью;
- пишет файл атомарно.

Для регулярной обработки можно запускать после сохранения результата backend-ом либо через systemd timer. Предпочтителен вызов из backend job сразу после скачивания оригинала.

## 5. Cache-Control на origin

Nginx отвечает для медиа:

```text
Cache-Control: public, max-age=31536000, s-maxage=31536000, immutable
Vary: Accept-Encoding
```

Не добавлять `Set-Cookie`, `private`, `no-store` или `no-cache` на публичные файлы.

## 6. Cloudflare Cache Rule

Cloudflare Dashboard → Caching → Cache Rules → Create rule.

Expression:

```text
(http.host eq "media.chillcreative.ru" and
 (starts_with(http.request.uri.path, "/previews/") or
  starts_with(http.request.uri.path, "/originals/")))
```

Actions:

```text
Cache eligibility: Eligible for cache
Edge TTL: Respect origin TTL
Browser TTL: Respect origin TTL
```

На Free-плане этого достаточно. Не включать `Cache Everything` для API, webhook и HTML-доменов.

Первый запрос обычно `MISS`, второй из той же edge-локации должен стать `HIT` и получить `Age`.

## 7. Временно отключить HTTP/3

На время проверки проблемных VPN:

```text
Cloudflare Dashboard
→ Speed
→ Optimization
→ Protocol Optimization
→ HTTP/3 (with QUIC)
→ Off
```

После изменения проверить через проблемные VPN-локации. HTTP/2 остаётся включённым. Если зависания исчезли, HTTP/3 оставить выключенным до отдельного разбора QUIC/UDP-маршрута.

## 8. Диагностика IPv4, IPv6 и Cloudflare cache

```bash
bash scripts/check_media_delivery.sh \
  https://media.chillcreative.ru/previews/example.webp
```

Скрипт выполняет:

- DNS A/AAAA;
- два последовательных HEAD-запроса;
- IPv4 и IPv6 замеры;
- HTTP/2 проверку;
- вывод `CF-Cache-Status`, `Age`, `CF-Ray`, `Content-Type`, `Content-Length`, `Cache-Control`, `Alt-Svc`.

Ожидаемо после прогрева:

```text
HTTP/2 200
server: cloudflare
cf-cache-status: HIT
age: > 0
content-type: image/webp
cache-control: public, max-age=31536000, s-maxage=31536000, immutable
```

Интерпретация:

- `curl -4` работает, `curl -6` зависает: проверить AAAA/origin IPv6; временно убрать AAAA.
- HTTP/2 работает, а проблема была только при HTTP/3: конфликт QUIC/UDP с VPN.
- постоянный `MISS`: проверить уникальность query string, Cache Rule и origin headers.
- `BYPASS`: убрать cookies/auth/private cache directives.
- `DYNAMIC`: правило не совпало либо тип ответа не кешируется.
- второй запрос `HIT`, но первый медленный: origin или маршрут до origin; Cloudflare после прогрева проблему сглаживает.

## 9. Интеграция с Mini App

API ленты должен возвращать отдельные URL:

```json
{
  "thumbnail_url": "https://media.chillcreative.ru/previews/ab/cd/hash.webp",
  "original_url": "https://media.chillcreative.ru/originals/ab/cd/hash.jpg"
}
```

В карточке ленты:

```html
<img
  src="https://media.chillcreative.ru/previews/ab/cd/hash.webp"
  loading="lazy"
  decoding="async"
  width="768"
  height="768"
/>
```

Не загружать оригиналы в списке и не запускать десятки загрузок одновременно.

## 10. Проверка после деплоя

```bash
nginx -t
systemctl reload nginx
curl -fsSI --http2 https://media.chillcreative.ru/healthz
bash scripts/check_media_delivery.sh https://media.chillcreative.ru/previews/<real-file>.webp
```

Проверить минимум с обычного подключения и двух проблемных VPN-локаций. Для каждого теста сохранить `CF-Ray`: по нему видно edge-локацию Cloudflare.
