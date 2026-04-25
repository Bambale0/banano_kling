#!/usr/bin/env bash

# Исправляет ошибку:
# NameError: name 'InlineKeyboardBuilder' is not defined
# в bot/handlers/generation.py
#
# Скрипт безопасно добавляет импорт:
# from aiogram.utils.keyboard import InlineKeyboardBuilder
# затем проверяет синтаксис файла и, если есть restart.sh, перезапускает бота.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_FILE="$PROJECT_DIR/bot/handlers/generation.py"
IMPORT_LINE="from aiogram.utils.keyboard import InlineKeyboardBuilder"
RESTART_SCRIPT="$PROJECT_DIR/restart.sh"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== Fix InlineKeyboardBuilder import ===${NC}"

if [ ! -f "$TARGET_FILE" ]; then
    echo -e "${RED}✗ Не найден файл: $TARGET_FILE${NC}"
    exit 1
fi

cd "$PROJECT_DIR"

if grep -Fxq "$IMPORT_LINE" "$TARGET_FILE"; then
    echo -e "${GREEN}✓ Импорт уже есть, файл менять не нужно.${NC}"
else
    BACKUP_FILE="$TARGET_FILE.bak.$(date +%Y%m%d_%H%M%S)"
    cp "$TARGET_FILE" "$BACKUP_FILE"
    echo -e "${YELLOW}Создан backup: $BACKUP_FILE${NC}"

    python3 - "$TARGET_FILE" "$IMPORT_LINE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
import_line = sys.argv[2]
text = path.read_text(encoding="utf-8")

if import_line in text:
    sys.exit(0)

anchor = "from aiogram.fsm.context import FSMContext\n"
if anchor in text:
    text = text.replace(anchor, anchor + import_line + "\n", 1)
else:
    # Фоллбек: вставляем после последнего импорта из aiogram.* в верхнем блоке импортов.
    lines = text.splitlines()
    insert_at = None
    for index, line in enumerate(lines[:80]):
        if line.startswith("from aiogram") or line.startswith("import aiogram"):
            insert_at = index + 1
    if insert_at is None:
        raise SystemExit("Не удалось найти место для вставки импорта")
    lines.insert(insert_at, import_line)
    text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")

path.write_text(text, encoding="utf-8")
PY

    echo -e "${GREEN}✓ Импорт добавлен в bot/handlers/generation.py${NC}"
fi

echo -e "${YELLOW}Проверяю синтаксис...${NC}"
python3 -m py_compile "$TARGET_FILE"
echo -e "${GREEN}✓ Синтаксис OK${NC}"

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
