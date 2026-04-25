#!/usr/bin/env bash

# Универсальный скрипт перезапуска только этого бота.
# Работает из любого каталога, использует существующие start.sh и stop.sh.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
START_SCRIPT="$PROJECT_DIR/start.sh"
STOP_SCRIPT="$PROJECT_DIR/stop.sh"
PID_FILE="$PROJECT_DIR/bot.pid"
LOG_FILE="$PROJECT_DIR/logs/bot_output.log"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== Перезапуск Telegram Bot ===${NC}"

if [ ! -f "$START_SCRIPT" ]; then
    echo -e "${RED}✗ Не найден start.sh: $START_SCRIPT${NC}"
    exit 1
fi

if [ ! -f "$STOP_SCRIPT" ]; then
    echo -e "${RED}✗ Не найден stop.sh: $STOP_SCRIPT${NC}"
    exit 1
fi

# Делаем скрипты исполняемыми на случай, если после git pull права не сохранились.
chmod +x "$START_SCRIPT" "$STOP_SCRIPT" 2>/dev/null || true

cd "$PROJECT_DIR"

echo -e "${YELLOW}1/2 Останавливаю текущий процесс...${NC}"
"$STOP_SCRIPT"

echo -e "${YELLOW}2/2 Запускаю бота заново...${NC}"
"$START_SCRIPT"

if [ ! -f "$PID_FILE" ]; then
    echo -e "${RED}✗ После запуска не появился PID-файл: $PID_FILE${NC}"
    [ -f "$LOG_FILE" ] && tail -100 "$LOG_FILE"
    exit 1
fi

BOT_PID="$(cat "$PID_FILE" 2>/dev/null | tr -d '[:space:]')"

if [ -z "$BOT_PID" ]; then
    echo -e "${RED}✗ PID-файл пустой: $PID_FILE${NC}"
    [ -f "$LOG_FILE" ] && tail -100 "$LOG_FILE"
    exit 1
fi

if kill -0 "$BOT_PID" 2>/dev/null; then
    echo -e "${GREEN}✓ Бот успешно перезапущен. PID=$BOT_PID${NC}"
    exit 0
fi

echo -e "${RED}✗ Бот не запустился или сразу завершился.${NC}"
[ -f "$LOG_FILE" ] && tail -100 "$LOG_FILE"
exit 1
