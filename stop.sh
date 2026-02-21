    #!/bin/bash

# Скрипт остановки бота

cd "$(dirname "$0")"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== Остановка Telegram Bot ===${NC}"

# Проверяем наличие PID файла
if [ ! -f "bot.pid" ]; then
    echo -e "${YELLOW}Бот не запущен (файл bot.pid не найден)${NC}"
    exit 0
fi

BOT_PID=$(cat bot.pid)

# Проверяем, что процесс существует
if ! ps -p $BOT_PID > /dev/null 2>&1; then
    echo -e "${YELLOW}Бот уже остановлен (процесс $BOT_PID не найден)${NC}"
    rm -f bot.pid
    exit 0
fi

# Останавливаем процесс
echo -e "${YELLOW}Остановка бота (PID: $BOT_PID)...${NC}"
kill $BOT_PID 2>/dev/null

# Ждём завершения
sleep 2

# Проверяем, остановился ли процесс
if ps -p $BOT_PID > /dev/null 2>&1; then
    echo -e "${YELLOW}Принудительная остановка...${NC}"
    kill -9 $BOT_PID 2>/dev/null
    sleep 1
fi

# Финальная проверка
if ps -p $BOT_PID > /dev/null 2>&1; then
    echo -e "${RED}✗ Не удалось остановить бота!${NC}"
    exit 1
else
    echo -e "${GREEN}✓ Бот успешно остановлен${NC}"
    rm -f bot.pid
fi

# Опционально: деактивируем виртуальное окружение
if [ -n "$VIRTUAL_ENV" ]; then
    deactivate 2>/dev/null
fi