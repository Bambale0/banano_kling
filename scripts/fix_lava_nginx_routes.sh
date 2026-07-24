#!/usr/bin/env bash
set -Eeuo pipefail

CANONICAL_CONF="/etc/nginx/sites-enabled/banano-kling.conf"
SITES_ENABLED="/etc/nginx/sites-enabled"
TG_PORT="1888"
VK_PORT="1777"
TG_LOG="/root/tanya/banano_kling/logs/bot.log"

if [[ $EUID -ne 0 ]]; then
  echo "Запусти от root: sudo bash $0"
  exit 1
fi

if [[ ! -e "$CANONICAL_CONF" ]]; then
  echo "Не найден канонический конфиг: $CANONICAL_CONF"
  exit 1
fi

for command in python3 nginx systemctl curl grep find; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Не найдена команда: $command"
    exit 1
  fi
done

TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="/root/nginx-backups/lava-routes-$TS"
DISABLED_DIR="$BACKUP_DIR/disabled-from-sites-enabled"
mkdir -p "$DISABLED_DIR"

# Сохраняем содержимое канонического файла с разыменованием симлинка.
cp -L "$CANONICAL_CONF" "$BACKUP_DIR/banano-kling.conf.contents"

restore() {
  local rc=$?
  trap - ERR
  echo "Откатываю nginx-конфигурацию из $BACKUP_DIR"

  if [[ -f "$BACKUP_DIR/banano-kling.conf.contents" ]]; then
    cat "$BACKUP_DIR/banano-kling.conf.contents" > "$CANONICAL_CONF"
  fi

  shopt -s nullglob
  for disabled in "$DISABLED_DIR"/*; do
    mv -f "$disabled" "$SITES_ENABLED/$(basename "$disabled")"
  done
  shopt -u nullglob

  nginx -t || true
  systemctl reload nginx || true
  exit "$rc"
}

trap restore ERR

python3 - "$CANONICAL_CONF" "$TG_PORT" "$VK_PORT" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
tg_port = sys.argv[2]
vk_port = sys.argv[3]
text = path.read_text(encoding="utf-8")

SERVER_START_RE = re.compile(r"(?m)^[ \t]*server[ \t]*\{")
SERVER_NAME_RE = re.compile(r"(?m)^[ \t]*server_name[ \t]+([^;]+);")
LOCATION_START_RE = re.compile(
    r"(?m)^[ \t]*location[ \t]+(?:=[ \t]+)?/lava/webhook(?:[ \t]+|\{)"
)
PROXY_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)proxy_pass[ \t]+http://127\.0\.0\.1:\d+(?:/[^;]*)?;(?P<tail>[ \t]*(?:#.*)?)$"
)


def matching_brace(source: str, opening_index: int) -> int:
    depth = 0
    quote: str | None = None
    escaped = False
    in_comment = False

    for index in range(opening_index, len(source)):
        char = source[index]

        if in_comment:
            if char == "\n":
                in_comment = False
            continue

        if escaped:
            escaped = False
            continue

        if char == "\\":
            escaped = True
            continue

        if quote:
            if char == quote:
                quote = None
            continue

        if char in {"'", '"'}:
            quote = char
            continue

        if char == "#":
            in_comment = True
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index

    raise RuntimeError("Не удалось найти закрывающую фигурную скобку")


def patch_lava_location(block: str, port: str, domain: str) -> tuple[str, int]:
    patched = 0
    search_from = 0

    while True:
        location_match = LOCATION_START_RE.search(block, search_from)
        if not location_match:
            break

        opening = block.find("{", location_match.start(), location_match.end() + 2)
        if opening == -1:
            raise RuntimeError(f"{domain}: у location /lava/webhook нет открывающей скобки")

        closing = matching_brace(block, opening)
        location = block[location_match.start(): closing + 1]

        replacement_count = 0

        def replace_proxy(match: re.Match[str]) -> str:
            nonlocal replacement_count
            replacement_count += 1
            return (
                f"{match.group('indent')}proxy_pass "
                f"http://127.0.0.1:{port};{match.group('tail')}"
            )

        new_location = PROXY_RE.sub(replace_proxy, location, count=1)
        if replacement_count != 1:
            raise RuntimeError(
                f"{domain}: внутри location /lava/webhook не найден однозначный proxy_pass"
            )

        block = block[: location_match.start()] + new_location + block[closing + 1 :]
        patched += 1
        search_from = location_match.start() + len(new_location)

    return block, patched


parts: list[str] = []
cursor = 0
patched_by_domain = {
    "tanyapi.chillcreative.ru": 0,
    "tanyavk.chillcreative.ru": 0,
    "devtanyapi.chillcreative.ru": 0,
}

for server_match in SERVER_START_RE.finditer(text):
    if server_match.start() < cursor:
        continue

    opening = text.find("{", server_match.start(), server_match.end())
    closing = matching_brace(text, opening)
    block = text[server_match.start(): closing + 1]

    parts.append(text[cursor: server_match.start()])

    names: set[str] = set()
    for name_match in SERVER_NAME_RE.finditer(block):
        names.update(name_match.group(1).split())

    domain: str | None = None
    port: str | None = None
    if "tanyapi.chillcreative.ru" in names:
        domain, port = "tanyapi.chillcreative.ru", tg_port
    elif "tanyavk.chillcreative.ru" in names:
        domain, port = "tanyavk.chillcreative.ru", vk_port
    elif "devtanyapi.chillcreative.ru" in names:
        domain, port = "devtanyapi.chillcreative.ru", tg_port

    if domain and port:
        block, count = patch_lava_location(block, port, domain)
        patched_by_domain[domain] += count

    parts.append(block)
    cursor = closing + 1

parts.append(text[cursor:])

for required in ("tanyapi.chillcreative.ru", "tanyavk.chillcreative.ru"):
    if patched_by_domain[required] != 1:
        raise RuntimeError(
            f"Ожидался ровно один HTTPS location /lava/webhook для {required}, "
            f"найдено: {patched_by_domain[required]}"
        )

path.write_text("".join(parts), encoding="utf-8")

print("Маршруты в каноническом конфиге:")
print(f"  tanyapi.chillcreative.ru/lava/webhook -> 127.0.0.1:{tg_port}")
print(f"  tanyavk.chillcreative.ru/lava/webhook -> 127.0.0.1:{vk_port}")
if patched_by_domain["devtanyapi.chillcreative.ru"]:
    print(f"  devtanyapi.chillcreative.ru/lava/webhook -> 127.0.0.1:{tg_port}")
PY

# banano-kling.conf уже содержит полноценные server-блоки tanyapi, tanyavk и devtanyapi.
# Убираем из sites-enabled все остальные файлы, которые повторно объявляют эти домены.
mapfile -d '' DUPLICATE_CONFIGS < <(
  find "$SITES_ENABLED" -maxdepth 1 \( -type f -o -type l \) -print0 |
    while IFS= read -r -d '' file; do
      [[ "$file" == "$CANONICAL_CONF" ]] && continue
      if grep -Eq 'server_name[^;]*(tanyapi\.chillcreative\.ru|devtanyapi\.chillcreative\.ru|tanyavk\.chillcreative\.ru)' "$file" 2>/dev/null; then
        printf '%s\0' "$file"
      fi
    done
)

for duplicate in "${DUPLICATE_CONFIGS[@]:-}"; do
  [[ -n "$duplicate" ]] || continue
  echo "Отключаю дублирующий nginx-конфиг: $duplicate"
  mv "$duplicate" "$DISABLED_DIR/$(basename "$duplicate")"
done

echo
echo "Проверяю nginx..."
NGINX_TEST_OUTPUT="$(nginx -t 2>&1)" || {
  printf '%s\n' "$NGINX_TEST_OUTPUT"
  false
}
printf '%s\n' "$NGINX_TEST_OUTPUT"

if nginx -T 2>&1 | grep -Eq 'conflicting server name "(tanyapi|devtanyapi|tanyavk)\.chillcreative\.ru"'; then
  echo "Остались конфликтующие server_name для Tanya-доменов:"
  nginx -T 2>&1 | grep -E 'conflicting server name "(tanyapi|devtanyapi|tanyavk)\.chillcreative\.ru"' || true
  false
fi

systemctl reload nginx

echo
echo "nginx перезагружен без конфликтов Tanya-доменов."

TG_MARKER="tg-route-$TS"
VK_MARKER="vk-route-$TS"

echo
echo "Проверяю Telegram-маршрут:"
TG_HTTP="$(curl -sS -o /dev/null -w '%{http_code}' \
  -X POST 'https://tanyapi.chillcreative.ru/lava/webhook' \
  -H 'Content-Type: application/json' \
  --data "{\"test\":\"$TG_MARKER\"}")"
echo "HTTP $TG_HTTP"

echo "Проверяю VK-маршрут:"
VK_HTTP="$(curl -sS -o /dev/null -w '%{http_code}' \
  -X POST 'https://tanyavk.chillcreative.ru/lava/webhook' \
  -H 'Content-Type: application/json' \
  --data "{\"test\":\"$VK_MARKER\"}")"
echo "HTTP $VK_HTTP"

[[ "$TG_HTTP" == "200" ]]
[[ "$VK_HTTP" == "200" ]]

sleep 1

if [[ ! -f "$TG_LOG" ]]; then
  echo "Не найден лог Telegram-бота: $TG_LOG"
  false
fi

if ! grep -Fq "$TG_MARKER" "$TG_LOG"; then
  echo "Маркер tanyapi не найден в Telegram-логе"
  false
fi

if grep -Fq "$VK_MARKER" "$TG_LOG"; then
  echo "Запрос tanyavk всё ещё попал в Telegram-бот"
  false
fi

trap - ERR

echo
echo "OK: tanyapi /lava/webhook работает через 1888."
echo "OK: tanyavk /lava/webhook работает через 1777 и не попадает в Telegram-бот."
echo "Отключённые дубли сохранены в: $DISABLED_DIR"
echo "Полная резервная копия: $BACKUP_DIR"
