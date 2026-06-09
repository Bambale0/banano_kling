import sqlite3

conn = sqlite3.connect('/root/banano_kling/bot.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
row = cur.execute(
    'SELECT id, telegram_id, credits, partner_balance_rub, prompt_repeat_balance_rub, partner_agreed_at, updated_at FROM users WHERE telegram_id = ?',
    (339795159,),
).fetchone()
print(dict(row) if row else None)
if row:
    rows = cur.execute(
        'SELECT id, user_id, amount_rub, status, created_at, updated_at FROM partner_withdrawals WHERE user_id = ? ORDER BY id DESC LIMIT 10',
        (row['id'],),
    ).fetchall()
    print([dict(r) for r in rows])
conn.close()
