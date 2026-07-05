#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
load_env_file() {
    local env_file="$1"
    local line key value

    [ -f "$env_file" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line%"${line##*[![:space:]]}"}"
        [ -n "$line" ] || continue
        case "$line" in \#*) continue ;; esac
        case "$line" in *=*) ;; *) continue ;; esac
        key="${line%%=*}"
        value="${line#*=}"
        key="${key%"${key##*[![:space:]]}"}"
        value="${value#"${value%%[![:space:]]*}"}"
        value="${value%"${value##*[![:space:]]}"}"
        value="${value%\"}"
        value="${value#\"}"
        value="${value%\'}"
        value="${value#\'}"
        if [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
            export "$key=$value"
        fi
    done < "$env_file"
}

load_env_file .env
load_env_file .env.postgres
mkdir -p logs
[ -f venv/bin/activate ] && source venv/bin/activate

PROJECT_DIR="$(pwd)"
BOT_PORT="${WEBHOOK_PORT:-1888}"
SYSTEMD_SERVICE="${BANANO_SYSTEMD_SERVICE:-banano-kling.service}"

if command -v systemctl >/dev/null 2>&1; then
    SERVICE_STATE="$(systemctl show "$SYSTEMD_SERVICE" --property=LoadState --value 2>/dev/null || true)"
    if [ "$SERVICE_STATE" = "loaded" ]; then
        systemctl start "$SYSTEMD_SERVICE"
        sleep 2
        if systemctl is-active --quiet "$SYSTEMD_SERVICE"; then
            BOT_PID="$(systemctl show "$SYSTEMD_SERVICE" --property=MainPID --value 2>/dev/null || true)"
            if [ -n "$BOT_PID" ] && [ "$BOT_PID" != "0" ]; then
                echo "$BOT_PID" > bot.pid
                echo "Bot running via systemd PID=$BOT_PID"
            else
                echo "Bot running via systemd"
            fi
            exit 0
        fi
        systemctl status "$SYSTEMD_SERVICE" --no-pager || true
        exit 1
    fi
fi

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
