#!/bin/bash

# Скрипт остановки только этого бота

set -u

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$PROJECT_DIR/bot.pid"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== Остановка Telegram Bot ===${NC}"

is_our_bot_pid() {
    local pid="$1"
    local cmdline=""
    local proc_cwd=""

    if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
        return 1
    fi

    if [ -r "/proc/$pid/cmdline" ]; then
        cmdline="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)"
    fi

    if [ -L "/proc/$pid/cwd" ]; then
        proc_cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null)"
    fi

    case "$cmdline" in
        *"python"*"-m bot.main"*)
            ;;
        *)
            return 1
            ;;
    esac

    [ "$proc_cwd" = "$PROJECT_DIR" ]
}

stop_pid() {
    local pid="$1"

    if ! is_our_bot_pid "$pid"; then
        return 1
    fi

    echo -e "${YELLOW}Остановка бота (PID: $pid)...${NC}"
    kill "$pid" 2>/dev/null || true

    for _ in 1 2 3 4 5; do
        if ! kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
        sleep 1
    done

    echo -e "${YELLOW}Процесс не завершился, отправляю SIGKILL (PID: $pid)...${NC}"
    kill -9 "$pid" 2>/dev/null || true
    sleep 1

    ! kill -0 "$pid" 2>/dev/null
}

stopped_any=0

# Сначала пробуем остановить процесс из PID-файла
if [ -f "$PID_FILE" ]; then
    BOT_PID="$(cat "$PID_FILE" 2>/dev/null | tr -d '[:space:]')"

    if [ -n "$BOT_PID" ] && stop_pid "$BOT_PID"; then
        stopped_any=1
    elif [ -n "$BOT_PID" ]; then
        echo -e "${YELLOW}PID-файл найден, но PID $BOT_PID не относится к этому боту.${NC}"
    fi

    rm -f "$PID_FILE"
fi

# Резервный поиск: только python -m bot.main из текущего каталога проекта
for proc_dir in /proc/[0-9]*; do
    pid="${proc_dir##*/}"
    if stop_pid "$pid"; then
        stopped_any=1
    fi
done

# Финальная проверка: в каталоге проекта не должно остаться наших bot.main
remaining_pids=()
for proc_dir in /proc/[0-9]*; do
    pid="${proc_dir##*/}"
    if is_our_bot_pid "$pid"; then
        remaining_pids+=("$pid")
    fi
done

if [ ${#remaining_pids[@]} -gt 0 ]; then
    echo -e "${RED}✗ Не удалось полностью остановить этого бота!${NC}"
    printf '%s\n' "${remaining_pids[@]}" | while read -r pid; do
        [ -n "$pid" ] || continue
        ps -p "$pid" -o pid=,cmd=
    done
    exit 1
fi

if [ "$stopped_any" -eq 1 ]; then
    echo -e "${GREEN}✓ Бот успешно остановлен${NC}"
else
    echo -e "${GREEN}✓ Этот бот уже был остановлен${NC}"
fi
