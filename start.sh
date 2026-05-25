#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && export $(grep -v '^#' .env | xargs) || true
mkdir -p logs
[ -f venv/bin/activate ] && source venv/bin/activate

PROJECT_DIR="$(pwd)"
BOT_PORT="${WEBHOOK_PORT:-1888}"

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

find_our_bot_pid() {
    for proc_dir in /proc/[0-9]*; do
        local pid="${proc_dir##*/}"
        if is_our_bot_pid "$pid"; then
            echo "$pid"
            return 0
        fi
    done
    return 1
}

find_listening_pid_on_port() {
    local line=""
    local pid=""

    while IFS= read -r line; do
        pid="$(printf '%s\n' "$line" | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | head -1)"
        if [ -n "$pid" ]; then
            echo "$pid"
            return 0
        fi
    done < <(ss -ltnp 2>/dev/null | grep -E "[:.]${BOT_PORT}[[:space:]]" || true)

    return 1
}

find_listening_bot_pid() {
    local pid=""

    pid="$(find_listening_pid_on_port || true)"
    if [ -n "$pid" ] && is_our_bot_pid "$pid"; then
        echo "$pid"
        return 0
    fi

    return 1
}

EXISTING_PID="$(find_listening_bot_pid || true)"
if [ -z "$EXISTING_PID" ]; then
    EXISTING_PID="$(find_our_bot_pid || true)"
fi

if [ -n "$EXISTING_PID" ]; then
    echo "$EXISTING_PID" > bot.pid
    echo "Bot already running PID=$EXISTING_PID"
    exit 0
fi

PORT_OWNER_PID="$(find_listening_pid_on_port || true)"
if [ -n "$PORT_OWNER_PID" ]; then
    echo "Port $BOT_PORT is already in use by another process:"
    ps -p "$PORT_OWNER_PID" -o pid=,cmd= || true
    exit 1
fi

rm -f bot.pid
nohup python -m bot.main >/dev/null 2>&1 &
LAUNCH_PID="$!"
BOT_PID=""

for _ in 1 2 3 4 5 6 7 8 9 10; do
    LISTENER_PID="$(find_listening_bot_pid || true)"
    if [ -n "$LISTENER_PID" ]; then
        BOT_PID="$LISTENER_PID"
    fi
    sleep 1
done

if [ -z "$BOT_PID" ]; then
    BOT_PID="$(find_our_bot_pid || true)"
fi
if [ -z "$BOT_PID" ]; then
    BOT_PID="$LAUNCH_PID"
fi

if [ -n "$BOT_PID" ] && is_our_bot_pid "$BOT_PID"; then
    echo "$BOT_PID" > bot.pid
    echo "Bot started PID=$BOT_PID"
else
    tail -100 logs/bot.log
    exit 1
fi
