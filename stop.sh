#!/bin/bash

# Скрипт остановки бота

cd "$(dirname "$0")"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== Остановка Telegram Bot ===${NC}"

PROJECT_DIR="$(pwd -P)"
PID_FILE="$PROJECT_DIR/bot.pid"

is_our_process() {
    local pid="$1"
    [ -n "$pid" ] || return 1
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    ps -p "$pid" > /dev/null 2>&1 || return 1

    local cwd
    cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
    [ "$cwd" = "$PROJECT_DIR" ] || return 1

    local cmd
    cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
    [[ "$cmd" == *"python"* && "$cmd" == *"-m bot.main"* ]]
}

stop_pid() {
    local pid="$1"
    if ! is_our_process "$pid"; then
        echo -e "${YELLOW}PID $pid не относится к этому боту, пропускаю.${NC}"
        return 1
    fi

    echo -e "${YELLOW}Остановка бота (PID: $pid)...${NC}"
    kill "$pid" 2>/dev/null || true
    sleep 2

    if ps -p "$pid" > /dev/null 2>&1; then
        echo -e "${YELLOW}Процесс не завершился, принудительная остановка PID $pid...${NC}"
        kill -9 "$pid" 2>/dev/null || true
        sleep 1
    fi
}

STOPPED=0

if [ -f "$PID_FILE" ]; then
    BOT_PID="$(cat "$PID_FILE")"
    if stop_pid "$BOT_PID"; then
        STOPPED=1
    fi
    rm -f "$PID_FILE"
fi

# Fallback: ищем только процессы, запущенные из текущей директории проекта.
for pid in $(pgrep -f "python.*-m bot.main" 2>/dev/null || true); do
    if is_our_process "$pid"; then
        stop_pid "$pid"
        STOPPED=1
    fi
done

REMAINING=()
for pid in $(pgrep -f "python.*-m bot.main" 2>/dev/null || true); do
    if is_our_process "$pid"; then
        REMAINING+=("$pid")
    fi
done

if [ "${#REMAINING[@]}" -gt 0 ]; then
    echo -e "${RED}✗ Не удалось полностью остановить этого бота!${NC}"
    echo "Оставшиеся PID: ${REMAINING[*]}"
    exit 1
fi

if [ "$STOPPED" -eq 1 ]; then
    echo -e "${GREEN}✓ Этот бот успешно остановлен${NC}"
else
    echo -e "${GREEN}✓ Запущенных процессов этого бота не найдено${NC}"
fi
