#!/usr/bin/env bash
set -Eeuo pipefail

CANONICAL_CONF="/etc/nginx/sites-enabled/banano-kling.conf"
SITES_ENABLED="/etc/nginx/sites-enabled"
TG_PORT="1888"
VK_PORT="1777"

if [[ $EUID -ne 0 ]]; then
  echo "Запусти от root: sudo bash $0"
  exit 1
fi

for command in python3 nginx systemctl curl grep find cp mv cat; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Не найдена команда: $command"
    exit 1
  }
done

if [[ ! -f "$CANONICAL_CONF" ]]; then
  echo "Не найден конфиг: $CANONICAL_CONF"
  exit 1
fi

TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="/root/nginx-backups/lava-routes-exact-$TS"
DISABLED_DIR="$BACKUP_DIR/disabled-from-sites-enabled"
mkdir -p "$DISABLED_DIR"
cp -L "$CANONICAL_CONF" "$BACKUP_DIR/banano-kling.conf.contents"

rollback() {
  local rc=$?
  trap - ERR
  echo "Откатываю изменения из $BACKUP_DIR"
  cat "$BACKUP_DIR/banano-kling.conf.contents" > "$CANONICAL_CONF"

  shopt -s nullglob
  for file in "$DISABLED_DIR"/*; do
    mv -f "$file" "$SITES_ENABLED/$(basename "$file")"
  done
  shopt -u nullglob

  nginx -t || true
  systemctl restart nginx || true
  exit "$rc"
}
trap rollback ERR

python3 - "$CANONICAL_CONF" "$TG_PORT" "$VK_PORT" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
tg_port = sys.argv[2]
vk_port = sys.argv[3]
text = path.read_text(encoding="utf-8")

SERVER_RE = re.compile(r"(?m)^[ \t]*server[ \t]*\{")
SERVER_NAME_RE = re.compile(r"(?m)^[ \t]*server_name[ \t]+([^;]+);")
HTTPS_RE = re.compile(r"(?m)^[ \t]*listen[ \t]+(?:\[[^\]]+\]:)?443(?:[ \t;]|$)")
LOCATION_RE = re.compile(
    r"(?m)^[ \t]*location[ \t]+(?P<modifier>=|\^~|~\*|~)?[ \t]*(?P<path>[^ \t\{]+)[ \t]*\{"
)
PROXY_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)proxy_pass[ \t]+http://127\.0\.0\.1:(?P<port>\d+)(?P<tail>[^;]*;[ \t]*(?:#.*)?)$"
)


def closing_brace(source: str, opening: int) -> int:
    depth = 0
    quote = None
    escaped = False
    comment = False
    for index in range(opening, len(source)):
        char = source[index]
        if comment:
            if char == "\n":
                comment = False
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
            comment = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    raise RuntimeError("Несбалансированные скобки nginx")


def locations(block: str):
    cursor = 0
    while True:
        match = LOCATION_RE.search(block, cursor)
        if not match:
            return
        opening = block.find("{", match.start(), match.end())
        closing = closing_brace(block, opening)
        yield match.group("modifier") or "", match.group("path"), match.start(), closing + 1
        cursor = closing + 1


def proxy_port(block: str) -> str | None:
    match = PROXY_RE.search(block)
    return match.group("port") if match else None


def replace_first_proxy_port(block: str, expected_port: str) -> str:
    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return (
            f"{match.group('indent')}proxy_pass "
            f"http://127.0.0.1:{expected_port}{match.group('tail')}"
        )

    result = PROXY_RE.sub(repl, block, count=1)
    if count != 1:
        raise RuntimeError("В location /lava/webhook не найден proxy_pass")
    return result


parts: list[str] = []
cursor = 0
found_tg = 0
found_vk = 0

for server_match in SERVER_RE.finditer(text):
    if server_match.start() < cursor:
        continue
    opening = text.find("{", server_match.start(), server_match.end())
    closing = closing_brace(text, opening)
    block = text[server_match.start():closing + 1]
    parts.append(text[cursor:server_match.start()])

    names: set[str] = set()
    for name_match in SERVER_NAME_RE.finditer(block):
        names.update(name_match.group(1).split())

    if HTTPS_RE.search(block) and "tanyapi.chillcreative.ru" in names:
        found_tg += 1
        route_port = None
        for modifier, route, start, end in locations(block):
            if route == "/lava/webhook":
                route_port = proxy_port(block[start:end])
                break
            if route == "/":
                route_port = proxy_port(block[start:end])
        if route_port != tg_port:
            raise RuntimeError(
                f"tanyapi: /lava/webhook не наследует proxy_pass 127.0.0.1:{tg_port}; найден порт {route_port}"
            )

    if HTTPS_RE.search(block) and "tanyavk.chillcreative.ru" in names:
        found_vk += 1
        matches = [item for item in locations(block) if item[1] == "/lava/webhook"]
        if len(matches) != 1:
            raise RuntimeError(
                f"tanyavk: ожидался один location /lava/webhook, найдено {len(matches)}"
            )
        _, _, start, end = matches[0]
        location = block[start:end]
        location = replace_first_proxy_port(location, vk_port)
        block = block[:start] + location + block[end:]

    parts.append(block)
    cursor = closing + 1

parts.append(text[cursor:])

if found_tg != 1:
    raise RuntimeError(f"Ожидался один HTTPS server tanyapi, найдено {found_tg}")
if found_vk != 1:
    raise RuntimeError(f"Ожидался один HTTPS server tanyavk, найдено {found_vk}")

path.write_text("".join(parts), encoding="utf-8")
print(f"Проверено: tanyapi /lava/webhook -> 127.0.0.1:{tg_port} через location /")
print(f"Исправлено: tanyavk /lava/webhook -> 127.0.0.1:{vk_port}")
PY

mapfile -d '' DUPLICATES < <(
  find "$SITES_ENABLED" -maxdepth 1 \( -type f -o -type l \) -print0 |
    while IFS= read -r -d '' file; do
      [[ "$file" == "$CANONICAL_CONF" ]] && continue
      if grep -Eq 'server_name[^;]*(tanyapi\.chillcreative\.ru|devtanyapi\.chillcreative\.ru|tanyavk\.chillcreative\.ru)' "$file" 2>/dev/null; then
        printf '%s\0' "$file"
      fi
    done
)

for file in "${DUPLICATES[@]:-}"; do
  [[ -n "$file" ]] || continue
  echo "Отключаю дубль: $file"
  mv "$file" "$DISABLED_DIR/$(basename "$file")"
done

echo
echo "Проверяю синтаксис nginx..."
nginx -t

DUMP="$(nginx -T 2>&1)"
if grep -Eq 'conflicting server name "(tanyapi|devtanyapi|tanyavk)\.chillcreative\.ru"' <<<"$DUMP"; then
  echo "Остались конфликты Tanya-доменов:"
  grep -E 'conflicting server name "(tanyapi|devtanyapi|tanyavk)\.chillcreative\.ru"' <<<"$DUMP" || true
  false
fi

# Полный restart нужен, чтобы старые worker-процессы не успели обслужить проверочный запрос.
systemctl restart nginx

echo
echo "Проверяю доступность webhook после полного restart..."
TG_HTTP="$(curl --silent --show-error --insecure --http1.1 --noproxy '*' \
  --resolve 'tanyapi.chillcreative.ru:443:127.0.0.1' \
  --connect-timeout 5 --max-time 15 \
  -o /dev/null -w '%{http_code}' \
  -X POST 'https://tanyapi.chillcreative.ru/lava/webhook' \
  -H 'Content-Type: application/json' \
  --data '{"test":"tg-route-check"}')"
VK_HTTP="$(curl --silent --show-error --insecure --http1.1 --noproxy '*' \
  --resolve 'tanyavk.chillcreative.ru:443:127.0.0.1' \
  --connect-timeout 5 --max-time 15 \
  -o /dev/null -w '%{http_code}' \
  -X POST 'https://tanyavk.chillcreative.ru/lava/webhook' \
  -H 'Content-Type: application/json' \
  --data '{"test":"vk-route-check"}')"

echo "tanyapi: HTTP $TG_HTTP"
echo "tanyavk:  HTTP $VK_HTTP"
[[ "$TG_HTTP" == "200" ]]
[[ "$VK_HTTP" == "200" ]]

# После restart повторно убеждаемся, что активен только канонический набор блоков.
POST_DUMP="$(nginx -T 2>&1)"
if grep -Eq 'conflicting server name "(tanyapi|devtanyapi|tanyavk)\.chillcreative\.ru"' <<<"$POST_DUMP"; then
  echo "После restart снова появились конфликты Tanya-доменов"
  false
fi

trap - ERR

echo
echo "OK: маршруты разделены."
echo "  tanyapi /lava/webhook -> 127.0.0.1:$TG_PORT"
echo "  tanyavk  /lava/webhook -> 127.0.0.1:$VK_PORT"
echo "Отключённые дубли: $DISABLED_DIR"
echo "Резервная копия: $BACKUP_DIR"
