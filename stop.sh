#!/bin/bash

# Скрипт остановки бота

cd "$(dirname "$0")"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== Остановка Telegram Bot ===${NC}"

# Сначала пробуем найти процессы бота через pkill (более надёжно)
pkill -f "python.*bot.main" 2>/dev/null

# Также останавливаем по PID файлу если есть
if [ -f "bot.pid" ]; then
    BOT_PID=$(cat bot.pid)
    
    # Проверяем и убиваем основной процесс
    if [ -n "$BOT_PID" ] && ps -p $BOT_PID > /dev/null 2>&1; then
        echo -e "${YELLOW}Остановка бота (PID: $BOT_PID)...${NC}"
        kill $BOT_PID 2>/dev/null
        sleep 2
        
        # Принудительно если не остановился
        if ps -p $BOT_PID > /dev/null 2>&1; then
            kill -9 $BOT_PID 2>/dev/null
            sleep 1
        fi
    fi
    
    rm -f bot.pid
fi

# Дополнительная проверка - убиваем все процессы python с bot.main
pkill -9 -f "python.*bot.main" 2>/dev/null

# Ждём завершения всех процессов
sleep 1

# Проверяем, что бот остановлен
if pgrep -f "python.*bot.main" > /dev/null 2>&1; then
    echo -e "${RED}✗ Не удалось полностью остановить бота!${NC}"
    echo "Запущенные процессы bot:"
    ps aux | grep "python.*bot.main" | grep -v grep
    exit 1
else
    echo -e "${GREEN}✓ Бот успешно остановлен${NC}"
fi
