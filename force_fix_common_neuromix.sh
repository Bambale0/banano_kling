#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import re

p = Path("bot/handlers/common.py")
s = p.read_text(encoding="utf-8")

# Remove broken helper block if previous failed patch left a raw multiline f-string.
start = s.find('def _build_main_menu_text(')
end = s.find('\ndef _build_balance_text', start)
if start != -1 and end != -1:
    s = s[:start] + s[end + 1:]

helper = '''def _build_main_menu_text(user_credits: int, referral_bonus_text: str = "") -> str:
    bonus_block = f"\\n{referral_bonus_text.strip()}\\n" if referral_bonus_text else "\\n"
    return (
        "Привет 👋\\n\\n"
        "Я <b>NEUROMIX</b> — самый выгодный и очень удобный бот для генерации изображений и видео.\\n\\n"
        "👇 Пользуйся текстовым вариантом генераций или открой приложение, чтобы начать творить 🚀\\n\\n"
        f"🍌 <b>Баланс:</b> <code>{user_credits}</code> бананов"
        f"{bonus_block}"
    )


'''

insert = s.find('def _build_balance_text')
if insert == -1:
    insert_after = '''def _get_user_menu(user_id: int) -> str:
    """Получает последнее посещённое меню пользователя"""
    return _user_last_menu.get(user_id)


'''
    balance = '''def _build_balance_text(stats: dict) -> str:
    return (
        "💎 <b>Баланс и статистика</b>\\n\\n"
        f"• Сейчас на балансе: <code>{stats['credits']}</code> бананов\\n"
        f"• Всего запусков: <code>{stats['generations']}</code>\\n"
        f"• Всего потрачено: <code>{stats['total_spent']}</code> бананов\\n"
        f"• Вы с нами с: <code>{stats['member_since']}</code>\\n"
        f"• Приглашено друзей: <code>{stats.get('referrals_count', 0)}</code>\\n"
        f"• Заработано по приглашениям: <code>{stats.get('referral_earned', 0)}</code>"
    )


'''
    s = s.replace(insert_after, insert_after + helper + balance, 1)
else:
    s = s[:insert] + helper + s[insert:]

# Replace old explicit welcome_text blocks that do not use helper.
neuromix_welcome = '''welcome_text = (
        "Привет 👋\\n\\n"
        "Я <b>NEUROMIX</b> — самый выгодный и очень удобный бот для генерации изображений и видео.\\n\\n"
        "👇 Пользуйся текстовым вариантом генераций или открой приложение, чтобы начать творить 🚀\\n\\n"
        f"🍌 <b>Ваш баланс:</b> <code>{user.credits}</code> бананов"
    )'''

s = re.sub(
    r'welcome_text\s*=\s*f?"""[\s\S]*?"""',
    neuromix_welcome,
    s,
    count=1,
)

s = re.sub(
    r'welcome_text\s*=\s*\([\s\S]*?f?"<i>Попробуй прямо сейчас! 👇</i>"\s*\)',
    neuromix_welcome,
    s,
    count=1,
)

# Remove any channel line left in common.py.
s = re.sub(r'\n\s*f?[\"\']?📢 <b>Наш канал:</b>[\s\S]*?\\n\\n[\"\']?', '\n', s)
s = s.replace('Banano AI Studio', 'NEUROMIX')

p.write_text(s, encoding="utf-8")
PY

python3 -m py_compile bot/handlers/common.py bot/miniapp.py bot/database.py

echo "common.py fixed. Restart bot: ./stop.sh && ./start.sh"
