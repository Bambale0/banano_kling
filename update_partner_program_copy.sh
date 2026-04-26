#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import re

TEXT = '''💼 <b>Партнёрам</b>

Это практическое руководство по участию в партнёрской программе.

Ваша партнёрская ссылка:
🔗 {referral_link}

<b>1 уровень</b> — {level1_percent}% от всех покупок ваших рефералов.
<b>2 уровень</b> — {level2_percent}% от покупок рефералов ваших рефералов.

<b>Как это работает:</b>
• Пользователь переходит по вашей ссылке
• Регистрируется и закрепляется за вами навсегда
• После оплат рефералов вам начисляется денежное вознаграждение

<b>2 уровень:</b>
Если ваш реферал привёл ещё людей, за их покупки вам также начисляется денежное вознаграждение — {level2_percent}%.

• Вывод доступен после достижения минимальной суммы {min_withdraw}₽
• Каждый, кто перейдёт по вашей реферальной ссылке, получает 🍌 {new_user_bonus} бананов для тестирования бота
• За каждого приглашённого вами реферала вам начисляется 🍌 {inviter_bonus} бананов'''

# 1) Add canonical copy helper.
Path("bot/partner_copy.py").write_text(
    "PARTNER_PROGRAM_TEXT = " + repr(TEXT) + "\n"
    "PARTNER_LEVEL1_PERCENT = 30\n"
    "PARTNER_LEVEL2_PERCENT = 7\n"
    "PARTNER_MIN_WITHDRAW_RUB = 1000\n"
    "PARTNER_NEW_USER_BONUS = 25\n"
    "PARTNER_INVITER_BONUS = 5\n",
    encoding="utf-8",
)

# 2) Patch visible partner texts in handlers.
for rel in [
    "bot/handlers/common.py",
    "bot/handlers/generation.py",
    "bot/main.py",
    "bot/miniapp.py",
]:
    p = Path(rel)
    if not p.exists():
        continue
    s = p.read_text(encoding="utf-8")
    original = s

    # Replace old partner guide blocks if they start with partner title.
    s = re.sub(
        r'💼\s*<b>Партн[её]рам</b>[\s\S]{0,2500}?(?=(?:await|return|builder|@router|def |class |\n\n#|$))',
        TEXT.replace('{referral_link}', '{referral_link}')
            .replace('{level1_percent}', '30')
            .replace('{level2_percent}', '7')
            .replace('{min_withdraw}', '1000')
            .replace('{new_user_bonus}', '25')
            .replace('{inviter_bonus}', '5'),
        s,
        flags=re.S,
    )

    # Soft constants replacement if old percentages/bonuses exist.
    s = s.replace('20%', '30%')
    s = s.replace('10%', '7%')
    s = s.replace('500₽', '1000₽')

    if s != original:
        p.write_text(s, encoding="utf-8")

# 3) Patch database/service constants if obvious names exist.
for rel in [
    "bot/services/partner_service.py",
    "bot/services/referral_service.py",
    "bot/database.py",
    "bot/config.py",
    "bot/handlers/payment.py",
    "bot/handlers/payments.py",
]:
    p = Path(rel)
    if not p.exists():
        continue
    s = p.read_text(encoding="utf-8")
    original = s

    replacements = {
        r'(LEVEL_?1[^\n=]*=\s*)\d+': r'\g<1>30',
        r'(FIRST_?LEVEL[^\n=]*=\s*)\d+': r'\g<1>30',
        r'(REFERRAL[^\n=]*PERCENT[^\n=]*=\s*)\d+': r'\g<1>30',
        r'(LEVEL_?2[^\n=]*=\s*)\d+': r'\g<1>7',
        r'(SECOND_?LEVEL[^\n=]*=\s*)\d+': r'\g<1>7',
        r'(MIN_?WITHDRAW[^\n=]*=\s*)\d+': r'\g<1>1000',
        r'(NEW_?USER_?BONUS[^\n=]*=\s*)\d+': r'\g<1>25',
        r'(INVITER_?BONUS[^\n=]*=\s*)\d+': r'\g<1>5',
        r'(REFERRAL_?BONUS[^\n=]*=\s*)\d+': r'\g<1>5',
    }
    for pat, repl in replacements.items():
        s = re.sub(pat, repl, s, flags=re.I)

    if s != original:
        p.write_text(s, encoding="utf-8")

PY

python3 - <<'PY'
from pathlib import Path
import py_compile
for rel in [
    "bot/partner_copy.py",
    "bot/handlers/common.py",
    "bot/handlers/generation.py",
    "bot/main.py",
    "bot/miniapp.py",
]:
    p = Path(rel)
    if p.exists():
        py_compile.compile(str(p), doraise=True)
print("Partner program copy/constants patch applied.")
PY

echo "Check partner mentions: grep -R 'Партнёрам\|Партнерам\|реферал\|referral\|30%\|7%' -n bot | head -120"
