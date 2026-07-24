#!/usr/bin/env bash
set -Eeuo pipefail

TG_CONF="/etc/nginx/sites-enabled/banano-kling.conf"
VK_CONF="/etc/nginx/sites-enabled/tanyavk.chillcreative.ru.conf"
TG_PORT="1888"
VK_PORT="1777"
TG_LOG="/root/tanya/banano_kling/logs/bot.log"

if [[ $EUID -ne 0 ]]; then
  echo "Запусти от root: sudo bash $0"
  exit 1
fi

for file in "$TG_CONF" "$VK_CONF"; do
  if [[ ! -f "$file" ]]; then
    echo "Не найден конфиг: $file"
    exit 1
  fi
done

TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="/root/nginx-backups/lava-routes-$TS"
mkdir -p "$BACKUP_DIR"

cp -a "$TG_CONF" "$BACKUP_DIR/banano-kling.conf"
cp -a "$VK_CONF" "$BACKUP_DIR/tanyavk.chillcreative.ru.conf"

restore() {
  echo "Откатываю nginx-конфиги из $BACKUP_DIR"
  cp -a "$BACKUP_DIR/banano-kling.conf" "$TG_CONF"
  cp -a "$BACKUP_DIR/tanyavk.chillcreative.ru.conf" "$VK_CONF"
}

trap 'echo "Ошибка на строке $LINENO"; restore' ERR

python3 - "$TG_CONF" "$VK_CONF" "$TG_PORT" "$VK_PORT" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

tg_path = Path(sys.argv[1])
vk_path = Path(sys.argv[2])
tg_port = sys.argv[3]
vk_port = sys.argv[4]


def rewrite(
    path: Path,
    *,
    port: str,
    remove_server_names: set[str],
    required_server_name: str,
) -> None:
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)

    output: list[str] = []
    in_lava = False
    lava_found = False
    proxy_found = False
    required_name_found = False

    location_re = re.compile(r"^\s*location\s+(?:=\s*)?/lava/webhook(?:\s|\{)")
    proxy_re = re.compile(
        r"^(\s*proxy_pass\s+)http://127\.0\.0\.1:\d+(?:/[^;]*)?;(\s*(?:#.*)?(?:\r?\n)?)$"
    )
    server_name_re = re.compile(r"^(\s*server_name\s+)([^;]+)(;.*(?:\r?\n)?)$")

    for line in lines:
        server_match = server_name_re.match(line)
        if server_match:
            original_names = server_match.group(2).split()

            # Меняем только тот server-блок, который действительно относится
            # к целевому домену текущего конфига. Остальные server_name в этом
            # же файле оставляем без изменений.
            if required_server_name in original_names:
                required_name_found = True
                names = [
                    name
                    for name in original_names
                    if name not in remove_server_names
                ]
                if required_server_name not in names:
                    raise RuntimeError(
                        f"{path}: потерян обязательный server_name "
                        f"{required_server_name}"
                    )
                line = (
                    server_match.group(1)
                    + " ".join(names)
                    + server_match.group(3)
                )

        if location_re.match(line):
            in_lava = True
            lava_found = True

        if in_lava:
            proxy_match = proxy_re.match(line)
            if proxy_match:
                line = (
                    proxy_match.group(1)
                    + f"http://127.0.0.1:{port};"
                    + proxy_match.group(2)
                )
                proxy_found = True

            if line.strip().startswith("}"):
                in_lava = False

        output.append(line)

    if not lava_found:
        raise RuntimeError(f"{path}: не найден location /lava/webhook")
    if not proxy_found:
        raise RuntimeError(
            f"{path}: внутри location /lava/webhook не найден proxy_pass на 127.0.0.1"
        )
    if not required_name_found:
        raise RuntimeError(
            f"{path}: не найден обязательный server_name {required_server_name}"
        )

    path.write_text("".join(output), encoding="utf-8")


rewrite(
    tg_path,
    port=tg_port,
    remove_server_names={"tanyavk.chillcreative.ru"},
    required_server_name="tanyapi.chillcreative.ru",
)

rewrite(
    vk_path,
    port=vk_port,
    remove_server_names={
        "tanyapi.chillcreative.ru",
        "devtanyapi.chillcreative.ru",
    },
    required_server_name="tanyavk.chillcreative.ru",
)
PY

echo
echo "Итоговые маршруты:"
grep -n -A7 -B2 -E 'server_name|location .*lava/webhook|proxy_pass http://127\.0\.0\.1:(1777|1888)' \
  "$TG_CONF" "$VK_CONF" || true

echo
echo "Проверяю nginx..."
if ! nginx -t; then
  restore
  nginx -t
  echo "Новый конфиг не прошёл проверку. Выполнен откат."
  exit 1
fi

systemctl reload nginx
trap - ERR

echo
echo "nginx перезагружен."

TG_MARKER="tg-route-$TS"
VK_MARKER="vk-route-$TS"

echo
echo "Проверяю Telegram-маршрут:"
curl -sS -o /dev/null -w "HTTP %{http_code}\n" \
  -X POST "https://tanyapi.chillcreative.ru/lava/webhook" \
  -H "Content-Type: application/json" \
  --data "{\"test\":\"$TG_MARKER\"}"

echo "Проверяю VK-маршрут:"
curl -sS -o /dev/null -w "HTTP %{http_code}\n" \
  -X POST "https://tanyavk.chillcreative.ru/lava/webhook" \
  -H "Content-Type: application/json" \
  --data "{\"test\":\"$VK_MARKER\"}"

sleep 1

echo
if [[ -f "$TG_LOG" ]]; then
  if grep -Fq "$TG_MARKER" "$TG_LOG"; then
    echo "OK: запрос tanyapi дошёл до Telegram-бота на 1888."
  else
    echo "ВНИМАНИЕ: маркер tanyapi не найден в $TG_LOG."
  fi

  if grep -Fq "$VK_MARKER" "$TG_LOG"; then
    echo "ОШИБКА: запрос tanyavk всё ещё попал в Telegram-бот."
    exit 2
  else
    echo "OK: запрос tanyavk не попал в Telegram-бот."
  fi
else
  echo "Лог Telegram-бота не найден: $TG_LOG"
fi

echo
echo "Готово."
echo "Резервные копии: $BACKUP_DIR"
echo "Схема:"
echo "  tanyapi.chillcreative.ru/lava/webhook -> 127.0.0.1:1888"
echo "  tanyavk.chillcreative.ru/lava/webhook -> 127.0.0.1:1777"
