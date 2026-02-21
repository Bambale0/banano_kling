#!/bin/bash

# Скрипт запуска бота в локальном режиме

cd "$(dirname "$0")"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Запуск Telegram Bot ===${NC}"

# Проверяем наличие .env файла
if [ ! -f ".env" ]; then
    echo -e "${RED}Ошибка: Файл .env не найден!${NC}"
    echo -e "${YELLOW}Скопируйте .env.example в .env и заполните переменные:${NC}"
    echo "  cp .env.example .env"
    exit 1
fi

# Создаём виртуальное окружение если нет
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Создание виртуального окружения...${NC}"
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo -e "${RED}Ошибка создания venv!${NC}"
        exit 1
    fi
fi

# Активируем виртуальное окружение
source venv/bin/activate

# Устанавливаем зависимости
echo -e "${YELLOW}Проверка зависимостей...${NC}"
pip install -q -r requirements.txt
if [ $? -ne 0 ]; then
    echo -e "${RED}Ошибка установки зависимостей!${NC}"
    exit 1
fi

# Создаём директорию для логов
mkdir -p logs

# Проверяем, не запущен ли уже бот
if [ -f "bot.pid" ]; then
    OLD_PID=$(cat bot.pid)
    if ps -p $OLD_PID > /dev/null 2>&1; then
        echo -e "${YELLOW}Бот уже запущен (PID: $OLD_PID)${NC}"
        echo "Используйте ./stop.sh для остановки"
        exit 1
    else
        rm -f bot.pid
    fi
fi

# Загружаем переменные окружения из .env
export $(grep -v '^#' .env | xargs)

# Проверяем BOT_TOKEN
if [ -z "$BOT_TOKEN" ] || [ "$BOT_TOKEN" = "your_telegram_bot_token_here" ]; then
    echo -e "${RED}Ошибка: BOT_TOKEN не установлен в .env!${NC}"
    exit 1
fi

# Запускаем бота в фоне
echo -e "${GREEN}Запуск бота...${NC}"
nohup python -m bot.main > logs/bot_output.log 2>&1 &
BOT_PID=$!

# Сохраняем PID
echo $BOT_PID > bot.pid

# Ждём немного и проверяем, что процесс запустился
sleep 2
if ps -p $BOT_PID > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Бот успешно запущен!${NC}"
    echo -e "  PID: ${YELLOW}$BOT_PID${NC}"
    echo -e "  Логи: ${YELLOW}logs/bot.log${NC}, ${YELLOW}logs/bot_output.log${NC}"
    echo ""
    echo "Для просмотра логов в реальном времени:"
    echo "  tail -f logs/bot.log"
    echo ""
    echo "Для остановки:"
    echo "  ./stop.sh"
else
    echo -e "${RED}✗ Ошибка запуска бота!${NC}"
    echo "Проверьте логи: logs/bot_output.log"
    rm -f bot.pid
    exit 1
fi