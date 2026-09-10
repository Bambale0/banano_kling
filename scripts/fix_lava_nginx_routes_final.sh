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

for command in python3 nginx systemctl curl grep find awk mktemp cp mv rm cat; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Не найдена команда: $command"
    exit 1
  }
done

if [[ ! -e "$CANONICAL_CONF" ]]; then
  echo "Не найден канонический конфиг: $CANONICAL_CONF"
  exit 1
fi

TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="/root/nginx-backups/lava-routes-final-$TS"
DISABLED_DIR="$BACKUP_DIR/disabled-from-sites-enabled"
mkdir -p "$DISABLED_DIR"
cp -L "$CANONICAL_CONF" "$BACKUP_DIR/banano-kling.conf.contents"

TG_HEADERS="$(mktemp)"
VK_HEADERS="$(mktemp)"

cleanup_temp() {
  rm -f "$TG_HEADERS" "$VK_HEADERS"
}

rollback() {
  local rc=$?
  trap - ERR
  cleanup_temp
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

trap rollback ERR
trap cleanup_temp EXIT

python3 - "$CANONICAL_CONF" "$TG_PORT" "$VK_PORT" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
tg_port = sys.argv[2]
vk_port = sys.argv[3]
text = path.read_text(encoding="utf-8")

TARGETS = {
    "tanyapi.chillcreative.ru": (tg_port, f"telegram-{tg_port}"),
    "devtanyapi.chillcreative.ru": (tg_port, f"telegram-{tg_port}"),
    "tanyavk.chillcreative.ru": (vk_port, f"vk-{vk_port}"),
}

SERVER_START_RE = re.compile(r"(?m)^[ \t]*server[ \t]*\{")
SERVER_NAME_RE = re.compile(r"(?m)^[ \t]*server_name[ \t]+([^;]+);")
HTTPS_LISTEN_RE = re.compile(r"(?m)^[ \t]*listen[ \t]+(?:\[[^\]]+\]:)?443(?:[ \t;]|$)")
LOCATION_START_RE = re.compile(
    r"(?m)^[ \t]*location[ \t]+(?:=[ \t]+)?/lava/webhook(?:[ \t]+|\{)"
)
PROXY_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)proxy_pass[ \t]+http://127\.0\.0\.1:\d+(?:/[^;]*)?;(?P<tail>[ \t]*(?:#.*)?)$"
)
ROUTE_HEADER_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)add_header[ \t]+X-Lava-Route[ \t]+(?:\"[^\"]*\"|'[^']*'|[^;]+)[ \t]+always;(?P<tail>[ \t]*(?:#.*)?)$"
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


def ensure_route_header(location: str, route_label: str) -> str:
    def replace_header(match: re.Match[str]) -> str:
        return (
            f'{match.group("indent")}add_header X-Lava-Route '
            f'"{route_label}" always;{match.group("tail")}'
        )

    updated, count = ROUTE_HEADER_RE.subn(replace_header, location, count=1)
    if count:
        return updated

    proxy_match = PROXY_RE.search(location)
    if not proxy_match:
        raise RuntimeError("Нельзя добавить X-Lava-Route: proxy_pass не найден")

    indent = proxy_match.group("indent")
    insert_at = proxy_match.end()
    header = f'\n{indent}add_header X-Lava-Route "{route_label}" always;'
    return location[:insert_at] + header + location[insert_at:]


def ensure_lava_location(
    block: str,
    *,
    port: str,
    route_label: str,
    domains: list[str],
) -> tuple[str, bool]:
    matches = list(LOCATION_START_RE.finditer(block))
    if len(matches) > 1:
        raise RuntimeError(
            f"{', '.join(domains)}: найдено несколько location /lava/webhook"
        )

    if matches:
        match = matches[0]
        opening = block.find("{", match.start(), match.end() + 2)
        if opening == -1:
            raise RuntimeError("У location /lava/webhook нет открывающей скобки")
        closing = matching_brace(block, opening)
        location = block[match.start(): closing + 1]

        def replace_proxy(proxy_match: re.Match[str]) -> str:
            return (
                f"{proxy_match.group('indent')}proxy_pass "
                f"http://127.0.0.1:{port};{proxy_match.group('tail')}"
            )

        new_location, count = PROXY_RE.subn(replace_proxy, location, count=1)
        if count != 1:
            raise RuntimeError(
                f"{', '.join(domains)}: внутри location /lava/webhook "
                "не найден однозначный proxy_pass"
            )
        new_location = ensure_route_header(new_location, route_label)
        block = block[:match.start()] + new_location + block[closing + 1:]
        return block, False

    closing = block.rfind("}")
    if closing == -1:
        raise RuntimeError("Не найдена закрывающая скобка server-блока")

    location = (
        "\n    # Lava payment webhook — managed by fix_lava_nginx_routes_final.sh\n"
        "    location = /lava/webhook {\n"
        f"        proxy_pass http://127.0.0.1:{port};\n"
        f"        add_header X-Lava-Route \"{route_label}\" always;\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto $scheme;\n"
        "    }\n"
    )
    block = block[:closing].rstrip() + "\n" + location + block[closing:]
    return block, True


parts: list[str] = []
cursor = 0
seen = {domain: 0 for domain in TARGETS}
inserted = {domain: False for domain in TARGETS}

for server_match in SERVER_START_RE.finditer(text):
    if server_match.start() < cursor:
        continue

    opening = text.find("{", server_match.start(), server_match.end())
    closing = matching_brace(text, opening)
    block = text[server_match.start(): closing + 1]
    parts.append(text[cursor:server_match.start()])

    if HTTPS_LISTEN_RE.search(block):
        names: set[str] = set()
        for name_match in SERVER_NAME_RE.finditer(block):
            names.update(name_match.group(1).split())

        target_domains = sorted(names.intersection(TARGETS))
        if target_domains:
            routes = {TARGETS[domain] for domain in target_domains}
            if len(routes) != 1:
                raise RuntimeError(
                    "В одном HTTPS server-блоке смешаны Telegram и VK домены: "
                    + ", ".join(target_domains)
                )
            port, route_label = next(iter(routes))
            block, was_inserted = ensure_lava_location(
                block,
                port=port,
                route_label=route_label,
                domains=target_domains,
            )
            for domain in target_domains:
                seen[domain] += 1
                inserted[domain] = inserted[domain] or was_inserted

    parts.append(block)
    cursor = closing + 1

parts.append(text[cursor:])

for required in ("tanyapi.chillcreative.ru", "tanyavk.chillcreative.ru"):
    if seen[required] != 1:
        raise RuntimeError(
            f"Ожидался ровно один HTTPS server-блок для {required}, найдено: {seen[required]}"
        )

path.write_text("".join(parts), encoding="utf-8")

print("Маршруты в каноническом конфиге:")
for domain, (port, route_label) in TARGETS.items():
    if seen[domain]:
        action = "добавлен" if inserted[domain] else "обновлён"
        print(
            f"  {domain}/lava/webhook -> 127.0.0.1:{port} "
            f"({action}, X-Lava-Route={route_label})"
        )
PY

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

NGINX_DUMP="$(nginx -T 2>&1)"
if grep -Eq 'conflicting server name "(tanyapi|devtanyapi|tanyavk)\.chillcreative\.ru"' <<<"$NGINX_DUMP"; then
  echo "Остались конфликтующие server_name для Tanya-доменов:"
  grep -E 'conflicting server name "(tanyapi|devtanyapi|tanyavk)\.chillcreative\.ru"' <<<"$NGINX_DUMP" || true
  false
fi

systemctl reload nginx

echo
echo "nginx перезагружен без конфликтов Tanya-доменов."

probe_route() {
  local domain="$1"
  local expected_route="$2"
  local headers_file="$3"
  local body="$4"
  local http_code curl_rc route

  : > "$headers_file"

  set +e
  http_code="$(curl --silent --show-error --insecure \
    --connect-timeout 5 --max-time 15 \
    --resolve "${domain}:443:127.0.0.1" \
    -D "$headers_file" -o /dev/null -w '%{http_code}' \
    -X POST "https://${domain}/lava/webhook" \
    -H 'Content-Type: application/json' \
    --data "$body")"
  curl_rc=$?
  set -e

  route="$(awk '
    BEGIN { IGNORECASE=1 }
    tolower($1) == "x-lava-route:" {
      gsub(/\r/, "", $2)
      value=$2
    }
    END { print value }
  ' "$headers_file")"

  echo "${domain}: HTTP ${http_code:-000}, X-Lava-Route=${route:-missing}"

  if [[ $curl_rc -ne 0 ]]; then
    echo "curl завершился с кодом $curl_rc"
    cat "$headers_file" || true
    return 1
  fi
  if [[ "$http_code" != "200" ]]; then
    echo "Ожидался HTTP 200"
    cat "$headers_file" || true
    return 1
  fi
  if [[ "$route" != "$expected_route" ]]; then
    echo "Ожидался X-Lava-Route=$expected_route"
    cat "$headers_file" || true
    return 1
  fi
}

echo
echo "Проверяю локальный Telegram-маршрут:"
probe_route \
  "tanyapi.chillcreative.ru" \
  "telegram-$TG_PORT" \
  "$TG_HEADERS" \
  '{"test":"tg-route-probe"}'

echo "Проверяю локальный VK-маршрут:"
probe_route \
  "tanyavk.chillcreative.ru" \
  "vk-$VK_PORT" \
  "$VK_HEADERS" \
  '{"test":"vk-route-probe"}'

trap - ERR
cleanup_temp
trap - EXIT

echo
echo "OK: tanyapi /lava/webhook подтверждён через telegram-$TG_PORT."
echo "OK: tanyavk /lava/webhook подтверждён через vk-$VK_PORT."
echo "Отключённые дубли сохранены в: $DISABLED_DIR"
echo "Полная резервная копия: $BACKUP_DIR"
