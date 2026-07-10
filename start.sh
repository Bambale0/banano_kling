#!/bin/bash

# Скрипт запуска VK бота

cd "$(dirname "$0")"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Запуск VK Bot ===${NC}"

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
mkdir -p logs static/uploads

# Очищаем логи при старте
> logs/vk_bot.log

# Проверяем, не запущен ли уже бот
if [ -f "vk.pid" ]; then
    OLD_PID=$(cat vk.pid)
    if ps -p $OLD_PID > /dev/null 2>&1; then
        echo -e "${YELLOW}VK бот уже запущен (PID: $OLD_PID)${NC}"
        echo "Используйте ./stop.sh для остановки"
        exit 1
    else
        rm -f vk.pid
    fi
fi

# Загружаем переменные окружения из .env безопасно
set -a
source .env
set +a

# Проверяем VK_GROUP_TOKEN
if [ -z "$VK_GROUP_TOKEN" ] || [ "$VK_GROUP_TOKEN" = "your_vk_group_token_here" ]; then
    echo -e "${RED}Ошибка: VK_GROUP_TOKEN не установлен в .env!${NC}"
    exit 1
fi

# Запускаем бота в фоне
echo -e "${GREEN}Запуск VK бота...${NC}"
nohup python bot/main_vk.py > logs/vk_bot.log 2>&1 &
BOT_PID=$!

# Сохраняем PID
echo $BOT_PID > vk.pid

# Ждём немного и проверяем, что процесс запустился
sleep 3
if ps -p $BOT_PID > /dev/null 2>&1; then
    echo -e "${GREEN}✓ VK бот успешно запущен!${NC}"
    echo -e "  PID: ${YELLOW}$BOT_PID${NC}"
    echo -e "  Логи: ${YELLOW}logs/vk_bot.log${NC}"
    echo ""
    echo "Для просмотра логов в реальном времени:"
    echo "  tail -f logs/vk_bot.log"
    echo ""
    echo "Для остановки:"
    echo "  ./stop.sh"
else
    echo -e "${RED}✗ Ошибка запуска VK бота!${NC}"
    echo "Проверьте логи: logs/vk_bot.log"
    rm -f vk.pid
    exit 1
fi