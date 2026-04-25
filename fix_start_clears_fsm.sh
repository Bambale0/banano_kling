#!/usr/bin/env bash

# Исправляет поведение /start:
# /start должен срабатывать в любом FSM-состоянии, очищать state
# и возвращать пользователя в главное меню.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_FILE="$PROJECT_DIR/bot/handlers/common.py"
RESTART_SCRIPT="$PROJECT_DIR/restart.sh"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== Fix /start clears FSM ===${NC}"

if [ ! -f "$TARGET_FILE" ]; then
    echo -e "${RED}✗ Не найден файл: $TARGET_FILE${NC}"
    exit 1
fi

cd "$PROJECT_DIR"

BACKUP_FILE="$TARGET_FILE.bak.$(date +%Y%m%d_%H%M%S)"
cp "$TARGET_FILE" "$BACKUP_FILE"
echo -e "${YELLOW}Создан backup: $BACKUP_FILE${NC}"

python3 - "$TARGET_FILE" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
original = text

# 1. /start не должен быть ограничен StateFilter(None), иначе в FSM он не перехватывается.
text = text.replace(
    '@router.message(CommandStart(), StateFilter(None))\nasync def cmd_start(message: types.Message):',
    '@router.message(CommandStart())\nasync def cmd_start(message: types.Message, state: FSMContext):',
)

# Если сигнатура уже была изменена, но декоратор ещё старый.
text = text.replace(
    '@router.message(CommandStart(), StateFilter(None))\nasync def cmd_start(message: types.Message, state: FSMContext):',
    '@router.message(CommandStart())\nasync def cmd_start(message: types.Message, state: FSMContext):',
)

# Если декоратор уже новый, но state ещё не добавлен.
text = text.replace(
    '@router.message(CommandStart())\nasync def cmd_start(message: types.Message):',
    '@router.message(CommandStart())\nasync def cmd_start(message: types.Message, state: FSMContext):',
)

needle = 'async def cmd_start(message: types.Message, state: FSMContext):\n    """Обработчик команды /start"""\n'
insert = needle + '    # /start всегда прерывает текущий сценарий/FSM и возвращает в главное меню\n    await state.clear()\n\n'
if needle in text and 'await state.clear()' not in text[text.index(needle):text.index(needle) + 300]:
    text = text.replace(needle, insert, 1)

if text == original:
    print('Файл уже выглядит исправленным или шаблон не найден.')
else:
    path.write_text(text, encoding="utf-8")
    print('common.py обновлён.')
PY

echo -e "${YELLOW}Проверяю синтаксис...${NC}"
python3 -m py_compile "$TARGET_FILE"
echo -e "${GREEN}✓ Синтаксис OK${NC}"

if grep -q '@router.message(CommandStart())' "$TARGET_FILE" && grep -q 'async def cmd_start(message: types.Message, state: FSMContext)' "$TARGET_FILE" && grep -q 'await state.clear()' "$TARGET_FILE"; then
    echo -e "${GREEN}✓ /start теперь должен очищать FSM.${NC}"
else
    echo -e "${RED}✗ Проверка патча не прошла. Смотри backup и common.py.${NC}"
    exit 1
fi

if [ -x "$RESTART_SCRIPT" ]; then
    echo -e "${YELLOW}Перезапускаю бота через restart.sh...${NC}"
    "$RESTART_SCRIPT"
elif [ -f "$RESTART_SCRIPT" ]; then
    echo -e "${YELLOW}Делаю restart.sh исполняемым и перезапускаю...${NC}"
    chmod +x "$RESTART_SCRIPT"
    "$RESTART_SCRIPT"
else
    echo -e "${YELLOW}restart.sh не найден. Перезапусти бота вручную.${NC}"
fi

echo -e "${GREEN}✓ Fix завершён.${NC}"
