#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "1) Restore common.py/database.py from git to remove broken local regex edits"
git checkout -- bot/handlers/common.py bot/database.py || true

python3 - <<'PY'
from pathlib import Path
import re

# ---------------- common.py: safe exact partner render + welcome ----------------
p = Path("bot/handlers/common.py")
s = p.read_text(encoding="utf-8")

main_menu_func = '''def _build_main_menu_text(user_credits: int, referral_bonus_text: str = "") -> str:
    bonus_block = f"\\n{referral_bonus_text.strip()}\\n" if referral_bonus_text else "\\n"
    return (
        "Привет 👋\\n\\n"
        "Я <b>NEUROMIX</b> — самый выгодный и очень удобный бот для генерации изображений и видео.\\n\\n"
        "👇 Пользуйся текстовым вариантом генераций или открой приложение, чтобы начать творить 🚀\\n\\n"
        f"🍌 <b>Баланс:</b> <code>{user_credits}</code> бананов"
        f"{bonus_block}"
    )


def _build_balance_text'''

s = re.sub(
    r'def _build_main_menu_text\(user_credits: int, referral_bonus_text: str = ""\) -> str:\n[\s\S]*?\n\ndef _build_balance_text',
    main_menu_func,
    s,
    flags=re.S,
)

partner_func = '''async def render_partner_program(target, user_id: int):
    """Рендерит экран партнёрской программы."""
    user = await get_or_create_user(user_id)
    stats = await get_partner_overview(user_id)

    bot = target.bot
    me = await bot.get_me()
    referral_code = user.referral_code or ""
    referral_link = (
        f"https://t.me/{me.username}?start=ref_{referral_code}"
        if referral_code
        else "Ссылка появится после активации"
    )

    text = (
        "💼 <b>Партнёрам</b>\\n\\n"
        "Это практическое руководство по участию в партнёрской программе.\\n\\n"
        f"Ваша партнёрская ссылка:\\n🔗 <code>{referral_link}</code>\\n\\n"
        "<b>1 уровень</b> — <code>30%</code> от всех покупок ваших рефералов.\\n"
        "<b>2 уровень</b> — <code>7%</code> от покупок рефералов ваших рефералов.\\n\\n"
        "<b>Как это работает:</b>\\n"
        "• Пользователь переходит по вашей ссылке\\n"
        "• Регистрируется и закрепляется за вами навсегда\\n"
        "• После оплат рефералов начисляется денежное вознаграждение\\n\\n"
        "<b>2 уровень:</b>\\n"
        "Ваш реферал привёл ещё рефералов — за все их покупки вам также начисляется денежное вознаграждение <code>7%</code>.\\n\\n"
        "• Вывод доступен после достижения минимальной суммы <code>1000₽</code>\\n"
        "• Каждый, кто перейдёт по вашей реферальной ссылке, получает 🍌 <code>25</code> бананов для тестирования бота\\n"
        "• За каждого приглашённого вами реферала вам начисляется 🍌 <code>5</code> бананов\\n\\n"
        "<b>Ваша статистика:</b>\\n"
        f"👥 Рефералов 1 уровня: <code>{stats.get('level1_count', stats.get('referrals_count', 0))}</code>\\n"
        f"👥 Рефералов 2 уровня: <code>{stats.get('level2_count', 0)}</code>\\n"
        f"💰 Баланс к выводу: <code>{stats.get('balance_rub', 0)}</code> ₽\\n"
        f"💸 Выведено: <code>{stats.get('withdrawn_rub', 0)}</code> ₽"
    )

    markup = get_partner_program_keyboard(
        referral_link if referral_code else "",
        is_partner=stats.get("is_partner", False),
    )

    if isinstance(target, types.Message):
        await target.answer(text, reply_markup=markup, parse_mode="HTML")
    else:
        await target.edit_text(text, reply_markup=markup, parse_mode="HTML")
'''

s = re.sub(
    r'async def render_partner_program\(target, user_id: int\):\n[\s\S]*?\n\n@router.callback_query\(F.data == "partner_accept"\)',
    partner_func + '\n\n@router.callback_query(F.data == "partner_accept")',
    s,
    flags=re.S,
)

s = re.sub(
    r'await callback\.message\.edit_text\(\n\s*"✅ <b>Партнёрский статус активирован</b>"[\s\S]*?parse_mode="HTML",\n\s*\)',
    '''await callback.message.edit_text(
        "✅ <b>Партнёрская программа активирована</b>\\n\\n"
        "Теперь вы получаете 30% с покупок рефералов 1 уровня и 7% с покупок 2 уровня.",
        reply_markup=get_partner_program_keyboard(referral_link, is_partner=True),
        parse_mode="HTML",
    )''',
    s,
    flags=re.S,
)

p.write_text(s, encoding="utf-8")

# ---------------- database.py: actual 2-level partner logic ----------------
p = Path("bot/database.py")
s = p.read_text(encoding="utf-8")

process_func = '''async def process_referral(
    referred_telegram_id: int,
    referral_code: str,
    signup_bonus: int = 25,
    inviter_bonus: int = 5,
) -> bool:
    """Обрабатывает реферальный переход: новый пользователь +25🍌, пригласивший +5🍌."""
    referral_code = (referral_code or "").strip().upper()
    if not referral_code:
        return False

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        referrer_cursor = await db.execute(
            "SELECT id FROM users WHERE referral_code = ?", (referral_code,),
        )
        referrer = await referrer_cursor.fetchone()
        if not referrer:
            return False

        referred_cursor = await db.execute(
            "SELECT id, referred_by FROM users WHERE telegram_id = ?",
            (referred_telegram_id,),
        )
        referred = await referred_cursor.fetchone()
        if not referred or referred["referred_by"]:
            return False
        if referred["id"] == referrer["id"]:
            return False

        await db.execute(
            "UPDATE users SET referred_by = ?, credits = credits + ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (referrer["id"], signup_bonus, referred_telegram_id),
        )
        await db.execute(
            "INSERT OR IGNORE INTO referrals (referrer_id, referred_id, bonus_credits) VALUES (?, ?, ?)",
            (referrer["id"], referred["id"], signup_bonus),
        )
        await db.execute(
            "UPDATE users SET credits = credits + ?, referral_earned = referral_earned + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (inviter_bonus, inviter_bonus, referrer["id"]),
        )
        await db.commit()
        return True
'''

s = re.sub(
    r'async def process_referral\([\s\S]*?\n\nasync def mark_user_paid',
    process_func + '\n\nasync def mark_user_paid',
    s,
    flags=re.S,
)

commission_func = '''async def credit_first_payment_referral_bonus(
    telegram_id: int,
    transaction_credits: int,
    transaction_amount_rub: Optional[float] = None,
    bonus_percent: int = 30,
) -> dict:
    """Начисляет партнёрское вознаграждение: 30% первому уровню, 7% второму."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, referred_by, has_paid FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        user = await cursor.fetchone()
        if not user or not user["referred_by"] or user["has_paid"]:
            return {"mode": "none", "value": 0, "percent": 0}

        base_value = float(transaction_amount_rub if transaction_amount_rub is not None else transaction_credits)
        level1_bonus = round(base_value * 30 / 100.0, 2)
        level2_bonus = 0.0

        ref1_id = user["referred_by"]
        await db.execute(
            "UPDATE users SET partner_total_revenue_rub = partner_total_revenue_rub + ?, partner_balance_rub = partner_balance_rub + ?, partner_tier = 'basic', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (base_value, level1_bonus, ref1_id),
        )

        ref_cursor = await db.execute("SELECT referred_by FROM users WHERE id = ?", (ref1_id,))
        ref1 = await ref_cursor.fetchone()
        if ref1 and ref1["referred_by"]:
            ref2_id = ref1["referred_by"]
            level2_bonus = round(base_value * 7 / 100.0, 2)
            await db.execute(
                "UPDATE users SET partner_total_revenue_rub = partner_total_revenue_rub + ?, partner_balance_rub = partner_balance_rub + ?, partner_tier = 'basic', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (base_value, level2_bonus, ref2_id),
            )

        await db.execute(
            "UPDATE users SET has_paid = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (user["id"],),
        )
        await db.commit()
        return {"mode": "partner", "value": level1_bonus, "percent": 30, "level2_value": level2_bonus, "level2_percent": 7}
'''

s = re.sub(
    r'async def credit_first_payment_referral_bonus\([\s\S]*?\n\ndef get_partner_percent_by_tier',
    commission_func + '\n\ndef get_partner_percent_by_tier',
    s,
    flags=re.S,
)

s = re.sub(
    r'def get_partner_percent_by_tier\(tier: str\) -> int:\n[\s\S]*?\n\ndef get_partner_tier_by_total',
    '''def get_partner_percent_by_tier(tier: str) -> int:
    """Процент партнёрского вознаграждения 1 уровня."""
    return 30


def get_partner_tier_by_total''',
    s,
    flags=re.S,
)

s = re.sub(
    r'def get_partner_tier_by_total\(total_revenue_rub: float\) -> str:\n[\s\S]*?\n\nasync def accept_partner_agreement',
    '''def get_partner_tier_by_total(total_revenue_rub: float) -> str:
    """Единый базовый уровень партнёрки."""
    return "basic"


async def accept_partner_agreement''',
    s,
    flags=re.S,
)

# get_partner_overview should show the current user's own partner stats, not central master stats.
s = re.sub(
    r'target_user = \(\n\s*requested_user if requested_user\.partner_agreed_at else master_partner\n\s*\)',
    'target_user = requested_user',
    s,
)

if 'level2_count' not in s:
    s = s.replace(
        'withdrawal_cursor = await db.execute(',
        '''level2_cursor = await db.execute("""
            SELECT COUNT(*) as count
            FROM users u2
            JOIN users u1 ON u2.referred_by = u1.id
            WHERE u1.referred_by = ?
            """, (target_user_id,))
        level2_row = await level2_cursor.fetchone()

        withdrawal_cursor = await db.execute(''',
        1,
    )
    s = s.replace(
        '"referrals_count": referrals_row["count"] or 0,',
        '"referrals_count": referrals_row["count"] or 0,\n            "level1_count": referrals_row["count"] or 0,\n            "level2_count": level2_row["count"] or 0,',
        1,
    )

p.write_text(s, encoding="utf-8")
PY

python3 -m py_compile bot/handlers/common.py bot/database.py

echo "OK: common.py repaired and partner logic updated. Now run ./stop.sh && ./start.sh"
